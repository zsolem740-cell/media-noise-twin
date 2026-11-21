"""A hírgyűjtő időkerete: lassú vagy hibás forrásnál időben megáll, és a már megvolt elemekkel folytatja (nincs hálózat, hamis óra)."""
import json
from pathlib import Path

import pytest
import yaml

from src.collectors import google_news as gn

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>%s - Forras</title><link>https://example.test/%s</link><pubDate>Sat, 21 Nov 2026 10:00:00 GMT</pubDate>
<source url="https://forras.test">Forras</source></item></channel></rss>"""
LANG = {"hl": "hu", "gl": "HU", "ceid": "HU:hu"}


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class FakeResp:
    def __init__(self, content=b"", status=200):
        self.content, self.status = content, status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")


class FakeSession:
    """Minden lekérés `cost` másodpercet 'vesz el' a hamis órából; a 'fail' előtagú URL-ek hibát adnak."""
    def __init__(self, clock, cost, fail_all=False):
        self.clock, self.cost, self.fail_all, self.calls = clock, cost, fail_all, []

    def get(self, url, **kw):
        self.calls.append(url)
        self.clock.t += self.cost
        if self.fail_all:
            raise RuntimeError("503 too many error responses")
        n = len(self.calls)
        return FakeResp(RSS % (f"Cim {n}".encode(), f"{n}".encode()))


def cfg(n_queries=6, pages=0):
    region = {"code": "HU-X", "lang": LANG, "queries": [f"q{i}" for i in range(n_queries)]}
    page_cfg = [{"url": f"https://hivatalos.test/{i}", "name": "H", "scope": "s", "region": "HU-X"} for i in range(pages)]
    return {"regions": [region], "official_pages": page_cfg}


def run(session, clock, c, **kw):
    stats = {}
    items = gn.collect(c, session, clock=clock, stats=stats, **kw)
    return items, stats


def test_idokereten_belul_minden_lekeres_lefut_es_nincs_hianyjelzes():
    clk = Clock()
    s = FakeSession(clk, cost=10)
    items, stats = run(s, clk, cfg(6), feed_budget=360, total_budget=480)
    assert len(s.calls) == 6 and len(items) == 6
    assert stats == {"skipped_feeds": 0, "skipped_pages": 0, "incomplete": False}


def test_a_feed_keret_kimerulese_utan_nem_indul_uj_lekeres_de_a_meglevo_elemek_megmaradnak():
    clk = Clock()
    s = FakeSession(clk, cost=100)
    items, stats = run(s, clk, cfg(6), feed_budget=250, total_budget=1000)
    assert len(s.calls) == 3            # 0, 100, 200 s < 250; a 300 s-nál már megáll
    assert len(items) == 3
    assert stats["skipped_feeds"] == 3 and stats["incomplete"] is True


def test_a_hivatalos_oldalak_a_feed_keret_kimerulese_utan_is_lekerhetok_a_teljes_keretig(capsys):
    clk = Clock()
    s = FakeSession(clk, cost=100)
    c = cfg(6, pages=2)
    # a hivatalos oldal tartalma nem értelmezhető (hamis válasz), de a lekérés megtörténik
    items, stats = run(s, clk, c, feed_budget=250, total_budget=1000)
    assert sum(1 for u in s.calls if "hivatalos.test" in u) == 2
    assert stats["skipped_pages"] == 0 and stats["skipped_feeds"] == 3


def test_a_teljes_keret_kimerulese_utan_a_hivatalos_oldalak_kimaradnak():
    clk = Clock()
    s = FakeSession(clk, cost=100)
    items, stats = run(s, clk, cfg(6, pages=3), feed_budget=250, total_budget=320)
    assert sum(1 for u in s.calls if "hivatalos.test" in u) == 1    # 300 s < 320: az első még elindul, a többi nem
    assert stats["skipped_pages"] == 2


def test_hibas_lassu_forrasnal_is_megall_es_nem_dob_kivetelt(capsys):
    clk = Clock()
    s = FakeSession(clk, cost=55, fail_all=True)      # a 2026-11-19-i napló: kb. 55 s egy lekérés, mind hibás
    items, stats = run(s, clk, cfg(13), feed_budget=360, total_budget=480)
    assert items == []
    assert len(s.calls) == 7                          # 0, 55, ... 330 s < 360
    assert stats["skipped_feeds"] == 6 and stats["incomplete"] is True
    err = capsys.readouterr().err
    assert "időkeret" in err and "6 hírforrás-lekérés kimaradt" in err


def test_a_futas_a_regiok_kozott_is_megall():
    clk = Clock()
    s = FakeSession(clk, cost=100)
    c = {"regions": [
        {"code": "A", "lang": LANG, "queries": ["a1", "a2"]},
        {"code": "B", "lang": LANG, "queries": ["b1", "b2"]},
    ], "official_pages": []}
    items, stats = run(s, clk, c, feed_budget=150, total_budget=1000)
    assert len(s.calls) == 2 and stats["skipped_feeds"] == 2


# ---------- alapértékek és környezeti beállítás ----------
@pytest.mark.parametrize("raw,want", [("", 360.0), ("  ", 360.0), ("abc", 360.0), ("-5", 360.0), ("0", 360.0),
                                       ("inf", 360.0), ("nan", 360.0), ("90", 90.0), (" 12.5 ", 12.5)])
def test_budget_from_env(monkeypatch, raw, want):
    monkeypatch.setenv("X_BUDGET", raw)
    assert gn.budget_from_env("X_BUDGET", 360.0) == want


def test_a_kulcsot_a_kornyezet_adja_ha_nincs_megadva_parameter(monkeypatch):
    monkeypatch.setenv("MEDIA_NOISE_FEED_BUDGET_S", "150")
    monkeypatch.setenv("MEDIA_NOISE_TOTAL_BUDGET_S", "1000")
    clk = Clock()
    s = FakeSession(clk, cost=100)
    stats = {}
    gn.collect(cfg(6), s, clock=clk, stats=stats)
    assert len(s.calls) == 2 and stats["skipped_feeds"] == 4


def test_az_alapkeretek_a_munkafolyamat_idokorlatan_belul_vannak_tartalekkal():
    wf = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github/workflows/media-noise.yml").read_text(encoding="utf-8"))
    job_s = wf["jobs"]["build"]["timeout-minutes"] * 60
    assert gn.FEED_BUDGET_S < gn.TOTAL_BUDGET_S
    assert gn.TOTAL_BUDGET_S <= job_s - 180, "a gyűjtés után legalább 3 perc kell a cikkelemzésnek, az ATM-nek és a mentésnek"


# ---------- kimenet ----------
def _main(monkeypatch, tmp_path, collect_stats):
    out = tmp_path / "latest.json"
    monkeypatch.setattr(gn, "OUT", out)
    monkeypatch.setattr(gn, "ROOT", tmp_path)
    monkeypatch.setattr(gn, "load_config", lambda: ({"regions": []}, {"warning": None, "user": False, "applied": []}))
    monkeypatch.setattr(gn, "make_session", lambda: object())

    def fake_collect(cfg_, session, *, stats=None, **kw):
        stats.update(collect_stats)
        return []
    monkeypatch.setattr(gn, "collect", fake_collect)
    assert gn.main() == 0
    return json.loads(out.read_text(encoding="utf-8"))


def test_a_kimenet_jelzi_ha_az_idokeret_miatt_hianyos(monkeypatch, tmp_path):
    p = _main(monkeypatch, tmp_path, {"skipped_feeds": 4, "skipped_pages": 1, "incomplete": True})
    assert p["incomplete"] is True and p["skipped_feeds"] == 4 and p["skipped_pages"] == 1 and p["count"] == 0


def test_hianytalan_futas_kimenete_valtozatlan_nincs_uj_kulcs(monkeypatch, tmp_path):
    p = _main(monkeypatch, tmp_path, {"skipped_feeds": 0, "skipped_pages": 0, "incomplete": False})
    assert set(p) == {"fetched_at", "count", "items"}


def test_a_keret_hatara_pontosan_ott_all_meg_ahol_az_ido_eleri():
    clk = Clock()
    s = FakeSession(clk, cost=100)
    items, stats = run(s, clk, cfg(6), feed_budget=200, total_budget=1000)
    assert len(s.calls) == 2       # 0 és 100 s: indul; a 200 s-nál (== keret) már nem
    clk2 = Clock()
    s2 = FakeSession(clk2, cost=100)
    items2, stats2 = run(s2, clk2, cfg(6, pages=3), feed_budget=1000, total_budget=500)
    assert len(s2.calls) == 6 and stats2["skipped_pages"] == 3     # a 6 feed után 600 s > 500 s: a hivatalos oldalak nem indulnak
