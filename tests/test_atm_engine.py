"""A pontozás invariánsai. Szándékosan nem rögzítenek konkrét súlyokat vagy kulcsszavakat,
így a modell hangolása (sources.json, user.json, frissítés-csomagok) nem töri el őket – csak a valódi hibák."""
import math
from datetime import timedelta

import pytest

from src.core import atm_engine as E
from src.utils.config import BASE, load_config
from src.utils.time_helper import now_utc, to_iso_utc


@pytest.fixture(scope="module")
def cfg():
    c, _status = load_config(BASE, BASE.parent / "nincs_ilyen_user.json")
    return c


def item(i, title, region="HU-NAT", domain="pelda.hu", hours_ago=1):
    return {"id": f"t{i}", "title": title, "summary": "", "link": f"https://{domain}/{i}",
            "source": domain, "source_domain": domain, "region": region,
            "published": to_iso_utc(now_utc() - timedelta(hours=hours_ago))}


# --- S: szenzációszint -------------------------------------------------------

@pytest.mark.parametrize("title", ["", "Ülésezett a megyei közgyűlés", "SOKKOLÓ!!! BOTRÁNY!!! ELKÉPESZTŐ!!!", "a" * 2000])
def test_sensation_range(title):
    s = E.sensation_level(title)
    assert 0.0 <= s <= 1.0


def test_sensation_calm_vs_loud():
    calm = E.sensation_level("Ülésezett a megyei közgyűlés Szombathelyen")
    loud = E.sensation_level("SOKKOLÓ BOTRÁNY!!! Elképesztő, ami történt!")
    assert calm < loud


def test_exclamations_never_lower_score():
    base = "Megnyílt az új híd Körmenden"
    assert E.sensation_level(base + "!!!") >= E.sensation_level(base)


# --- ATM képlet ----------------------------------------------------------------

@pytest.mark.parametrize("mode", ["sqrt_int", "classic"])
def test_atm_zero_when_silent_or_fully_valid(mode):
    assert E.atm_value(1.0, 0.0, 0.5, mode) == 0
    assert E.atm_value(1.0, 0.8, 1.0, mode) == 0


@pytest.mark.parametrize("mode", ["sqrt_int", "classic"])
def test_atm_monotonic(mode):
    lo = E.atm_value(0.9, 0.2, 0.6, mode)
    assert E.atm_value(0.9, 0.6, 0.6, mode) >= lo      # hangosabb cím → nem kisebb
    assert E.atm_value(0.9, 0.2, 0.3, mode) >= lo      # kevésbé hiteles forrás → nem kisebb
    assert E.atm_value(1.0, 0.2, 0.6, mode) >= lo      # nagyobb régiósúly → nem kisebb


def test_atm_sqrt_int_is_integer_and_bounded():
    for g in (0, 0.5, 1):
        for s in (0, 0.3, 1):
            for v in (0, 0.45, 0.95):
                a = E.atm_value(g, s, v, "sqrt_int")
                assert isinstance(a, int) and 0 <= a <= 1000


def test_half_up_matches_js_rounding():
    assert E.half_up(0.5) == 1 and E.half_up(1.5) == 2 and E.half_up(2.5) == 3 and E.half_up(2.49) == 2


# --- V: forrásbizalom ------------------------------------------------------------

def test_learned_v_bounded_and_official_fixed():
    noisy = {"n": 1000, "mS": 0.9}
    v = E.learned_v(0.7, "local_press", noisy, gmean=0.05)
    assert 0.55 - 1e-9 <= v <= 0.7                       # legfeljebb 0,15-tel csökkenhet
    assert E.learned_v(0.95, "official", noisy, 0.05) == 0.95
    assert E.learned_v(0.7, "local_press", {"n": 5, "mS": 0.9}, 0.05) == 0.7   # kevés adatnál nem tanul


# --- teljes futás ----------------------------------------------------------------

def test_build_history_end_to_end(cfg):
    raw = [item(1, "Ülésezett a megyei közgyűlés"),
           item(2, "SOKKOLÓ BOTRÁNY!!! Elképesztő, ami történt", region="HU-VA"),
           item(3, "Ülésezett a megyei közgyűlés"),                       # ugyanaz a cím, ugyanattól a forrástól
           item(4, "Régi hír", hours_ago=24 * 30)]                        # a megőrzési időn kívül
    out = E.build_history(raw, [], cfg)
    ids = {i["id"] for i in out["items"]}
    assert "t4" not in ids
    assert len([i for i in out["items"] if i["title"] == "Ülésezett a megyei közgyűlés"]) == 1
    for i in out["items"]:
        for k in ("V", "S", "G"):
            assert 0.0 <= i[k] <= 1.0
        assert i["ATM"] >= 0 and not (isinstance(i["ATM"], float) and math.isnan(i["ATM"]))
    loud = next(i for i in out["items"] if i["id"] == "t2")
    calm = next(i for i in out["items"] if i["title"] == "Ülésezett a megyei közgyűlés")
    assert loud["ATM"] >= calm["ATM"]
    th = out["model"]["thresholds"]
    assert th["low"] < th["high"]
    assert out["summary"]["n_items"] == len(out["items"])


def test_build_history_keeps_old_items(cfg):
    first = E.build_history([item(1, "Első hír")], [], cfg)
    second = E.build_history([item(2, "Második hír")], first["items"], cfg, first["profiles"])
    assert {"t1", "t2"} <= {i["id"] for i in second["items"]}


def test_excluded_domains_dropped(cfg):
    ex = (cfg.get("exclude_domains") or [None])[0]
    if not ex:
        pytest.skip("nincs kizárt domain a beállításban")
    out = E.build_history([item(1, "Bármi", domain=ex), item(2, "Más")], [], cfg)
    assert {i["id"] for i in out["items"]} == {"t2"}
