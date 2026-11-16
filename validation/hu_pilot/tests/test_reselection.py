"""Újrakiválasztás rögzített horgonyokkal: a leszavazott 20 cím változatlan marad, a mérési és külföldi címek az aktuális feedből jönnek, a horgonyok nélkül."""
import copy
import json

import pytest

from validation.hu_pilot import analysis, run, selection
from .conftest import backup
from .test_four_voters import write_exports


def wide_cfg(cfg, items, keep_free=1):
    """A mérési címek majdnem az egész készletet kiveszik, így minden nem kizárt cím biztosan kiválasztódik: a kizárás hiánya látszik."""
    c = copy.deepcopy(cfg)
    pool, _ = selection.eligible(items, cfg)
    c["sizes"]["measured_enriched"] = 0
    c["sizes"]["measured_random"] = len(pool) - 22 - keep_free
    c["filters"]["source_cap_total"] = 10 ** 6
    return c, pool


def old_anchor_rows(feed_path, n=20):
    """A "régi" horgonyok: nem szerepelnek a mostani feedben (más azonosító, más cím)."""
    return [(f"regi{i:02d}", f"Teljesen más régi horgonycím száma {i} egészen különleges szavakkal {i * 7919}") for i in range(n)]


def exports_for(tmp_path, rows, voters="ABCD", kind="fact"):
    votes = {v: [(i, kind) for i, _ in rows] for v in voters}
    return write_exports(tmp_path, votes)


def test_fixed_anchors_are_kept_verbatim_and_measured_titles_exclude_them(tmp_path, cfg, feed_path):
    items = selection.load_feed(feed_path)[1]
    rows = [(items[k]["id"], items[k]["title"]) for k in range(20)]                       # a mostani feedből való horgonyok: ki kell zárni őket a mérésből
    fixed = [{"id": i, "title": t} for i, t in rows]
    s = selection.select(items, cfg, fixed_anchors=fixed)
    assert [a["id"] for a in s["anchors"]] == [i for i, _ in rows] and [a["title"] for a in s["anchors"]] == [t for _, t in rows]
    meas = {m["id"] for m in s["measured"]}
    assert len(meas) == 30 and not meas & {i for i, _ in rows}
    nt = [selection.norm(m["title"]) for m in s["measured"]]
    assert not any(selection.norm(t) == n for _, t in rows for n in nt)
    assert s["excluded"]["rogzitett_horgony_duplikatum"] >= 20


def test_near_duplicate_of_a_fixed_anchor_is_not_chosen_for_measurement(cfg, feed_path):
    items = selection.load_feed(feed_path)[1]
    base = items[5]["title"]
    fixed = [{"id": f"x{k}", "title": f"Egyedi horgony {k} {k * 31337}"} for k in range(19)] + [{"id": "x19", "title": base + " "}]
    s = selection.select(items, cfg, fixed_anchors=fixed)
    assert items[5]["id"] not in {m["id"] for m in s["measured"]}


def test_anchor_with_same_id_but_different_title_still_blocks_that_id(cfg, feed_path):
    items = selection.load_feed(feed_path)[1]
    c, pool = wide_cfg(cfg, items)
    target = pool[3]
    fixed = [{"id": target["id"], "title": "Egészen más cím nulla 4243"}] + [{"id": f"z{k}", "title": f"Különleges horgony {k} {k * 7717}"} for k in range(1, 20)]
    base = selection.select(items, c, fixed_anchors=fixed[1:] + [{"id": "zz", "title": "Még egy különleges cím 99991"}])
    assert target["id"] in {m["id"] for m in base["measured"]}                    # a kizárás nélkül a cím kiválasztódna
    s = selection.select(items, c, fixed_anchors=fixed)
    assert target["id"] not in {m["id"] for m in s["measured"]}


def test_jaccard_near_duplicate_with_a_changed_word_is_excluded(cfg, feed_path):
    items = selection.load_feed(feed_path)[1]
    c, pool = wide_cfg(cfg, items)
    target = next(it for it in pool if len(it["title"].split()) > 5)
    words = target["title"].split()
    changed = " ".join(words[:-1] + ["valami"])
    assert selection.norm(changed) != selection.norm(target["title"])
    assert selection.jaccard(selection.norm(changed), selection.norm(target["title"])) >= cfg["filters"]["jaccard_dup"]
    others = [{"id": f"y{k}", "title": f"Különleges horgony {k} {k * 7717}"} for k in range(19)]
    free = selection.select(items, c, fixed_anchors=others + [{"id": "y19", "title": "Teljesen eltérő cím 12345 67890"}])
    assert target["id"] in {m["id"] for m in free["measured"]}
    s = selection.select(items, c, fixed_anchors=others + [{"id": "y19", "title": changed}])
    assert target["id"] not in {m["id"] for m in s["measured"]}


def test_wrong_number_of_fixed_anchors_is_refused(cfg, feed_path):
    items = selection.load_feed(feed_path)[1]
    with pytest.raises(ValueError, match="horgonyok száma"):
        selection.select(items, cfg, fixed_anchors=[{"id": "a", "title": "x"}] * 19)


def test_do_select_with_exports_writes_old_anchors_into_stage1_and_records_reselection(tmp_path, cfg, feed_path):
    rows = old_anchor_rows(feed_path)
    # a hamis exportban a cím is kell: write_exports címet generál, ezért saját mentést írunk
    exp = tmp_path / "exp.json"
    exp.write_text(json.dumps(backup("A", [(i, "fact") for i, _ in rows])), encoding="utf-8")
    data = json.loads(exp.read_text(encoding="utf-8"))
    for v, (i, t) in zip(data["votes"], rows):
        v["title"] = t
    exp.write_text(json.dumps(data), encoding="utf-8")
    res = tmp_path / "res"
    out = run.do_select(cfg, feed_path, base=res, anchors_from=[exp])
    assert out["anchors"] == 20 and out["measured"] == 30
    sel = json.loads((res / "selection.json").read_text(encoding="utf-8"))
    assert sel["anchor_ids"] == [i for i, _ in rows] and sel["reselection"]["anchors_fixed_from"] and len(sel["reselection"]["anchor_ids_sha256"]) == 64
    stage1 = json.loads((res / "pilot_stage1_anchors.json").read_text(encoding="utf-8"))
    assert [x["title"] for x in stage1["items"]] == [t for _, t in rows]
    stage2 = json.loads((res / "pilot_stage2_measured.json").read_text(encoding="utf-8"))
    assert not {x["id"] for x in stage2["items"]} & set(sel["anchor_ids"]) and len(stage2["items"]) == 30
    again = tmp_path / "res2"
    run.do_select(cfg, feed_path, base=again, anchors_from=[exp])
    assert (again / "selection.json").read_text(encoding="utf-8") == (res / "selection.json").read_text(encoding="utf-8")


def test_exports_with_wrong_count_or_conflicting_titles_are_refused(tmp_path, cfg):
    def mk(rows):
        p = tmp_path / f"e{len(rows)}{rows[0][1][:3]}.json"
        d = backup("A", [(i, "fact") for i, _ in rows])
        for v, (i, t) in zip(d["votes"], rows):
            v["title"] = t
        p.write_text(json.dumps(d), encoding="utf-8")
        return p
    few = [(f"i{k}", f"cím {k}") for k in range(19)]
    with pytest.raises(ValueError, match="19 különböző"):
        run.anchors_from_exports([mk(few)], cfg)
    ok = [(f"i{k}", f"cím {k}") for k in range(20)]
    other = [("i0", "MÁS cím")] + ok[1:]
    with pytest.raises(ValueError, match="két különböző cím"):
        run.anchors_from_exports([mk(ok), mk(other)], cfg)
    assert [a["id"] for a in run.anchors_from_exports([mk(ok)], cfg)] == [i for i, _ in ok]


def test_existing_selection_is_still_not_overwritten(tmp_path, cfg, feed_path):
    res = tmp_path / "res"
    run.do_select(cfg, feed_path, base=res)
    with pytest.raises(FileExistsError):
        run.do_select(cfg, feed_path, base=res)
