"""Már látott (próbakör) címek kizárása: sem a horgonyok, sem a mérési címek között nem szerepelhetnek. Hamis exportokkal, hálózat és valódi szavazói adat nélkül."""
import json

import pytest

from validation.hu_pilot import run, selection
from .conftest import backup
from .test_reselection import wide_cfg


def trial_export(tmp_path, items, name="proba.json", voter="A"):
    """Hamis próba-export: a megadott feed-elemek címével. A szavazó betűje és a szavazat a kizárás szempontjából közömbös."""
    d = backup(voter, [(it["id"], "fact") for it in items])
    for v, it in zip(d["votes"], items):
        v["title"] = it["title"]
    p = tmp_path / name
    p.write_text(json.dumps(d), encoding="utf-8")
    return p


def test_excluded_titles_are_never_chosen_but_would_be_without_exclusion(cfg, feed_path):
    items = selection.load_feed(feed_path)[1]
    base = selection.select(items, cfg)
    seen = [{"id": it["id"], "title": it["title"]} for it in base["measured"]]   # a "próbakör": kizárás nélkül pontosan ezek választódnak ki (determinisztikus), a kizárás hatása látszik
    s = selection.select(items, cfg, excluded=seen)
    got = {a["id"] for a in s["anchors"]} | {m["id"] for m in s["measured"]}
    assert len(s["anchors"]) == 20 and len(s["measured"]) == 30 and not got & {e["id"] for e in seen}
    assert s["excluded"]["kizart_lathato_cim"] >= 30


def test_too_small_pool_after_exclusion_stops_with_an_error(cfg, feed_path):
    items = selection.load_feed(feed_path)[1]
    pool, _ = selection.eligible(items, cfg)
    with pytest.raises(ValueError, match="nincs elég megfelelő cím"):
        selection.select(items, cfg, excluded=[{"id": it["id"], "title": it["title"]} for it in pool])


def test_near_duplicate_of_a_seen_title_is_excluded_too(cfg, feed_path):
    items = selection.load_feed(feed_path)[1]
    c, pool = wide_cfg(cfg, items)
    target = next(it for it in pool if len(it["title"].split()) > 5)
    changed = " ".join(target["title"].split()[:-1] + ["valami"])
    assert selection.jaccard(selection.norm(changed), selection.norm(target["title"])) >= cfg["filters"]["jaccard_dup"]
    free = selection.select(items, c)
    assert target["id"] in {a["id"] for a in free["anchors"]} | {m["id"] for m in free["measured"]}
    s = selection.select(items, c, excluded=[{"id": "x", "title": changed}])
    assert target["id"] not in {a["id"] for a in s["anchors"]} | {m["id"] for m in s["measured"]}


def test_without_exclusion_the_selection_is_unchanged(cfg, feed_path):
    items = selection.load_feed(feed_path)[1]
    a, b = selection.select(items, cfg), selection.select(items, cfg, excluded=None)
    assert a == b and "kizart_lathato_cim" not in a["excluded"]
    assert selection.select(items, cfg, excluded=[]) == a


def test_do_select_excludes_the_trial_titles_and_records_only_a_count_and_hash(tmp_path, cfg, feed_path):
    items = selection.load_feed(feed_path)[1]
    plain = tmp_path / "plain"
    run.do_select(cfg, feed_path, base=plain)
    first = json.loads((plain / "selection.json").read_text(encoding="utf-8"))
    trial_ids = first["measured_ids"]                                # a "próbakör" pontosan a korábbi 30 mérési cím
    by = {it["id"]: it for it in items}
    exp = trial_export(tmp_path, [by[i] for i in trial_ids])
    res = tmp_path / "res"
    out = run.do_select(cfg, feed_path, base=res, exclude_from=[exp])
    assert out["anchors"] == 20 and out["measured"] == 30
    sel = json.loads((res / "selection.json").read_text(encoding="utf-8"))
    assert not set(sel["measured_ids"]) & set(trial_ids) and not set(sel["anchor_ids"]) & set(trial_ids)
    assert sel["exclusion"]["seen_titles"] == 30 and len(sel["exclusion"]["ids_sha256"]) == 64
    raw = (res / "selection.json").read_text(encoding="utf-8")
    assert not any(i in sel["exclusion"].values() for i in trial_ids) and "title" not in sel["exclusion"]
    assert all(by[i]["title"] not in raw for i in trial_ids)         # a kizárt cím szövege nincs a jegyzékben
    for stage in ("pilot_stage1_anchors.json", "pilot_stage2_measured.json"):
        ids = {x["id"] for x in json.loads((res / stage).read_text(encoding="utf-8"))["items"]}
        assert not ids & set(trial_ids)
    again = tmp_path / "res2"
    run.do_select(cfg, feed_path, base=again, exclude_from=[exp])
    assert (again / "selection.json").read_text(encoding="utf-8") == raw        # determinisztikus


def test_exports_without_any_title_are_refused(tmp_path):
    p = tmp_path / "ures.json"
    d = backup("A", [])
    p.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(ValueError, match="nincs egyetlen cím sem"):
        run.titles_from_exports([p])


def test_existing_selection_is_not_overwritten_with_exclusion_either(tmp_path, cfg, feed_path):
    items = selection.load_feed(feed_path)[1]
    exp = trial_export(tmp_path, items[:5])
    res = tmp_path / "res"
    run.do_select(cfg, feed_path, base=res, exclude_from=[exp])
    with pytest.raises(FileExistsError):
        run.do_select(cfg, feed_path, base=res, exclude_from=[exp])


def test_cli_exclude_from_is_wired(tmp_path, cfg, feed_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(run, "do_select", lambda cfg_, **kw: seen.update(kw) or {"ok": 1})
    assert run.main(["select", "--exclude-from", "a.json", "b.json"]) == 0
    assert seen == {"exclude_from": ["a.json", "b.json"]}
