"""Élő-ellenőr: hamis átvitellel (a közös hálózati zár aktív), valódi kapcsolat és valódi cím nélkül."""
import hashlib
import json
import urllib.error

import pytest

from validation.hu_pilot import livecheck
from validation.hu_pilot.live import pagecheck

HOST = "mz-pilot-abc123.pages.dev"
BASE = f"https://{HOST}"
TITLES = [f"Próbacím száma {i} különleges szavakkal" for i in range(3)]
SEL = {"anchor_ids": ["a1", "a2", "a3"], "measured_ids": ["m1"], "foreign_order": []}
GOOD_HEADERS = {"/": {"cache-control": "public, max-age=0, must-revalidate, no-cache", "x-robots-tag": "noindex, nofollow", "referrer-policy": "no-referrer"},
                "/atm_history.json": {"cache-control": "no-store", "x-robots-tag": "noindex, nofollow"}}


def neutral(i, t):
    return {"id": i, "title": t, "source": "pilot", "source_domain": "pilot.invalid", "link": "", "summary": "", "alert": False, "official": False,
            "ATM": 0, "G": 0, "S": 0, "S0": 0, "V": 0, "V0": 0, "lat": 0, "lng": 0}


def served(version="v47.12", pilot="stage1-anchors", ids=("a1", "a2", "a3")):
    feed = {"pilot": pilot, "items": [neutral(i, t) for i, t in zip(ids, TITLES)]}
    return {"/": f"<html>{version}</html>".encode(), "/js/modules/diag.js": b"// diag", "/robots.txt": b"User-agent: *\nDisallow: /\n",
            "/atm_history.json": json.dumps(feed).encode()}


def make_fetch(files, headers=None, status=None, final_host=None):
    calls = []

    def fetch(url):
        calls.append(url)
        path = url[len(BASE):] or "/"
        if path not in files:
            return {"status": 404, "headers": {}, "body": b"", "url": url}
        h = dict((headers or GOOD_HEADERS).get(path, {}))
        return {"status": (status or {}).get(path, 200), "headers": h, "body": files[path], "url": url if not final_host else f"https://{final_host}{path}"}
    fetch.calls = calls
    return fetch


def by_name(checks):
    return {c["check"]: c for c in checks}


def test_a_correct_deployment_passes_every_check(cfg):
    fetch = make_fetch(served())
    c = livecheck.run_checks(BASE, fetch, "1", SEL, None, cfg)
    assert all(x["ok"] for x in c), [x for x in c if not x["ok"]]
    assert all(u.startswith(BASE) for u in fetch.calls) and len(fetch.calls) == 4          # csak a főcím alatti, ismert fájlok GET-je


def test_old_app_version_is_reported(cfg):
    c = by_name(livecheck.run_checks(BASE, make_fetch(served(version="v47.10")), "1", SEL, None, cfg))
    assert not c["alkalmazas_verzioja"]["ok"] and "v47.12" in c["alkalmazas_verzioja"]["detail"]


def test_wrong_stage_feed_is_reported_even_when_the_app_is_right(cfg):
    c = by_name(livecheck.run_checks(BASE, make_fetch(served(pilot="stage2-measured")), "1", SEL, None, cfg))
    assert not c["feed_pilot_mezo"]["ok"]


def test_title_order_and_membership_are_checked(cfg):
    swapped = by_name(livecheck.run_checks(BASE, make_fetch(served(ids=("a2", "a1", "a3"))), "1", SEL, None, cfg))
    assert not swapped["cimek_pontosan_a_szakaszeiv_sorrendre_is"]["ok"]
    other = by_name(livecheck.run_checks(BASE, make_fetch(served(ids=("m1", "a2", "a3"))), "1", SEL, None, cfg))
    assert not other["cimek_pontosan_a_szakaszeiv_sorrendre_is"]["ok"] and "felesleges 1" in other["cimek_pontosan_a_szakaszeiv_sorrendre_is"]["detail"]


def test_headers_that_do_not_take_effect_are_reported(cfg):
    bad = {"/": {"cache-control": "max-age=3600"}, "/atm_history.json": {"cache-control": "max-age=3600"}}
    c = by_name(livecheck.run_checks(BASE, make_fetch(served(), headers=bad), "1", SEL, None, cfg))
    for k in ("lap_cache_control_no_cache", "lap_noindex", "lap_referrer_policy_no_referrer", "feed_cache_control_no_store"):
        assert not c[k]["ok"], k


def test_non_neutral_rows_are_reported(cfg):
    files = served()
    feed = json.loads(files["/atm_history.json"])
    feed["items"][0]["source"] = "Valódi Forrás"
    feed["items"][1]["ATM"] = 55
    files["/atm_history.json"] = json.dumps(feed).encode()
    c = by_name(livecheck.run_checks(BASE, make_fetch(files), "1", SEL, None, cfg))
    assert not c["sorok_semlegesek_nincs_forras_link_pontszam"]["ok"]


def test_preview_address_is_flagged(cfg):
    preview = f"https://abcd1234.{HOST}"
    fetch_files = served()

    def fetch(url):
        return {"status": 200, "headers": GOOD_HEADERS.get(url[len(preview):] or "/", {}), "body": fetch_files.get(url[len(preview):] or "/", b""), "url": url}
    c = by_name(livecheck.run_checks(preview, fetch, "1", SEL, None, cfg))
    assert not c["fo_cim_nem_elonezeti"]["ok"]
    assert by_name(livecheck.run_checks(BASE, make_fetch(served()), "1", SEL, None, cfg))["fo_cim_nem_elonezeti"]["ok"]


def test_redirect_to_another_host_is_flagged(cfg):
    c = by_name(livecheck.run_checks(BASE, make_fetch(served(), final_host="masik.example"), "1", SEL, None, cfg))
    assert not c["lap_elerheto_es_nem_iranyit_at_masik_gepre"]["ok"]


def test_unreachable_page_stops_early_with_one_clear_failure(cfg):
    def boom(url):
        raise urllib.error.URLError("nincs kapcsolat")
    c = livecheck.run_checks(BASE, boom, "1", SEL, None, cfg)
    assert by_name(c)["lap_elerheto"]["ok"] is False and "URLError" in by_name(c)["lap_elerheto"]["detail"]
    nf = livecheck.run_checks(BASE, make_fetch({}), "1", SEL, None, cfg)
    assert by_name(nf)["lap_elerheto"]["detail"] == "HTTP 404"


def test_non_json_feed_is_reported_without_crashing(cfg):
    files = served()
    files["/atm_history.json"] = b"<html>nem json</html>"
    c = by_name(livecheck.run_checks(BASE, make_fetch(files), "1", SEL, None, cfg))
    assert not c["feed_olvashato_json"]["ok"]


def test_without_a_stage_the_feed_is_only_shown_not_compared(cfg):
    c = by_name(livecheck.run_checks(BASE, make_fetch(served()), None, None, None, cfg))
    assert c["feed_pilot_mezo_megvan"]["ok"] and "cimek_pontosan_a_szakaszeiv_sorrendre_is" not in c


def test_served_bytes_are_compared_with_the_manifest_when_there_is_one(cfg):
    files = served()
    good = {"files": {"index.html": hashlib.sha256(files["/"]).hexdigest(), "atm_history.json": hashlib.sha256(files["/atm_history.json"]).hexdigest()}}
    assert by_name(livecheck.run_checks(BASE, make_fetch(files), "1", SEL, good, cfg))["kiszolgalt_fajlok_bajtra_a_jegyzek_szerintiek"]["ok"]
    bad = {"files": dict(good["files"], **{"atm_history.json": "0" * 64})}
    c = by_name(livecheck.run_checks(BASE, make_fetch(files), "1", SEL, bad, cfg))["kiszolgalt_fajlok_bajtra_a_jegyzek_szerintiek"]
    assert not c["ok"] and "atm_history.json" in c["detail"]
    empty = by_name(livecheck.run_checks(BASE, make_fetch(files), "1", SEL, {"files": {}}, cfg))["kiszolgalt_fajlok_bajtra_a_jegyzek_szerintiek"]
    assert not empty["ok"]                                          # jegyzék fájllenyomatok nélkül nem igazol semmit


@pytest.mark.parametrize("url", ["http://mz.pages.dev", "https://user:pw@mz.pages.dev", "https://mz.pages.dev/index.html", "https://mz.pages.dev/?x=1", "https://", "https://mz.pages.dev:8443", "localhost", "https://mz.pages.dev/\nhttp://x.example"])
def test_unsafe_or_wrong_addresses_are_refused(url):
    with pytest.raises(ValueError):
        livecheck.normalize_url(url)


def test_address_without_scheme_is_https_and_trailing_slash_is_fine():
    assert livecheck.normalize_url("mz.pages.dev") == "https://mz.pages.dev"
    assert livecheck.normalize_url("https://mz.pages.dev/") == "https://mz.pages.dev"


def test_main_prints_a_summary_without_titles_and_returns_the_right_exit_code(tmp_path, cfg, capsys):
    ok = livecheck.main([BASE], fetch=make_fetch(served()))
    out = capsys.readouterr().out
    assert ok == 0 and "RENDBEN" in out and not any(t in out for t in TITLES)
    bad = livecheck.main([BASE], fetch=make_fetch(served(version="v47.10")))
    assert bad == 1 and "HIBA: ne szavaztass" in capsys.readouterr().out


def test_main_with_stage_reads_selection_and_manifest_from_results(tmp_path, cfg, capsys):
    (tmp_path / cfg["files"]["selection"]).write_text(json.dumps(SEL), encoding="utf-8")
    assert livecheck.main([BASE, "--stage", "1", "--results", str(tmp_path)], fetch=make_fetch(served())) == 0
    assert "a szakasz jegyzéke nincs meg" in capsys.readouterr().out
    wrong = livecheck.main([BASE, "--stage", "2", "--results", str(tmp_path)], fetch=make_fetch(served()))
    assert wrong == 1


def test_main_refuses_bad_input_and_missing_selection_with_exit_2(tmp_path, capsys):
    assert livecheck.main(["http://x.pages.dev"], fetch=make_fetch({})) == 2
    assert livecheck.main([BASE, "--stage", "1", "--results", str(tmp_path / "nincs")], fetch=make_fetch(served())) == 2
    assert "NEM OLVASHATÓ" in capsys.readouterr().err


def test_default_fetch_sends_a_generic_client_name_and_no_personal_data(monkeypatch):
    seen = {}

    class R:
        status, headers = 200, {"Cache-Control": "no-store"}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n=None):
            return b"x"

        def geturl(self):
            return "https://mz.pages.dev/"

    def fake_urlopen(req, timeout=None):
        seen["headers"], seen["method"], seen["url"], seen["timeout"] = dict(req.header_items()), req.get_method(), req.full_url, timeout
        return R()
    monkeypatch.setattr(pagecheck.urllib.request, "urlopen", fake_urlopen)
    r = pagecheck.default_fetch("https://mz.pages.dev/")
    assert seen["method"] == "GET" and seen["headers"] == {"User-agent": "hu-pilot-livecheck"} and seen["timeout"] == pagecheck.TIMEOUT
    assert r["status"] == 200 and r["headers"] == {"cache-control": "no-store"}


def test_default_fetch_is_blocked_by_the_shared_network_guard():
    with pytest.raises((RuntimeError, urllib.error.URLError)):
        pagecheck.default_fetch("https://example.com/")


def test_the_entry_point_wires_the_real_fetcher_and_the_logic_module_has_no_network_code():
    import inspect
    assert "livecheck.main(sys.argv[1:], default_fetch)" in inspect.getsource(pagecheck)
    src = inspect.getsource(livecheck)
    assert "urllib" not in src and "socket" not in src and "validation.hu_pilot.live" not in src
