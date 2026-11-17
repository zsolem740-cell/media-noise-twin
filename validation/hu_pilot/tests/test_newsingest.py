"""A hírgyűjtő offline feldolgozó próbái. Csak a repóba tett SZINTETIKUS fixture-öket és az ideiglenes mappába írt mintákat használja; hálózat nincs.
A hálózati zárat a közös autouse fixture adja (lásd test_network_guard.py): ezekben a tesztekben nem telepítünk zárat."""
import ast
import csv
import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

from validation.hu_pilot import newsingest as N
from validation.hu_pilot.paths import IsolationError

FIX = Path(__file__).resolve().parent / "fixtures" / "newsingest"
DOC = Path(N.__file__).resolve().parent / "docs" / "NEWSINGEST.md"
A, B = "01_synthetic_a.json", "02_nested/synthetic_b.json"
U = "https://x.example/a/b-c-d"


# ---------------------------------------------------------------- segédek

def put(root, rel, data):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, (bytes, bytearray)):
        p.write_bytes(data)
    elif isinstance(data, str):
        p.write_text(data, encoding="utf-8")
    else:
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def cap(records=None, links=None, **top):
    d = {"schema": 1, "synthetic": True}
    d.update(top)
    if records is not None:
        d["records"] = records
    if links is not None:
        d["links"] = links
    return d


def go(tmp_path, inp, name="res", extra=()):
    base = tmp_path / name
    rc = N.main(["--input-dir", str(inp), *extra], base=base)
    return rc, base / N.OUT_SUBDIR


def tsv(out):
    with open(out / N.FILES["tsv"], encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def jsonl(out, key):
    blob = (out / N.FILES[key]).read_bytes().decode("utf-8")
    assert blob == "" or blob.endswith("\n")
    return [json.loads(line) for line in blob.split("\n")[:-1]]


def one(tmp_path, rec, name="r", **top):
    """Egyetlen rekord feldolgozása; (sorok, problémák, kilépési kód)."""
    inp = tmp_path / ("in_" + name)
    put(inp, "a.json", cap([rec], **top))
    rc, out = go(tmp_path, inp, name)
    return tsv(out), jsonl(out, "problems"), rc


def pairs(problems):
    return [(p["field"], p["reason"]) for p in problems]


def snapshot(out):
    return {k: (out / v).read_bytes() for k, v in N.FILES.items()}


@pytest.fixture
def fix_out(tmp_path):
    rc, out = go(tmp_path, FIX)
    assert rc == 0
    return out


# ---------------------------------------------------------------- a fixture-ök pontos eredménye (kézzel ellenőrzött várt értékek)

EXPECTED_ROWS = [
    ("https://hirportal.example/belfold/2026/01/14/a-polgarmester-uj-hidat-avatott-a-folyon", "A polgármester új hidat avatott a folyón",
     "2026-01-14T08:30:00+01:00", "rss", "rss", "ok"),
    ("https://hirportal.example/gazdasag/2026/01/14/uj-penzugyi-szabaly-lep-hatalyba", "Új pénzügyi szabály lép hatályba", "2026-01-14", "unknown", "unknown", "ok"),
    ("https://hirportal.example/kulfold/2026/01/13/nagy-tavolsagu-vonat-keses-az-alpokban", "", "2026-01-13T22:00:00Z", "missing", "page", "incomplete"),
    ("https://hirportal.example/sport/20260112_a-hazai-csapat-nyerte-a-bajnoki-dontot", 'A hazai csapat nyerte a "bajnoki" döntőt', "", "unknown", "missing", "incomplete"),
    ("https://hirportal.example/kultura/2026/01/12/unnepi-menet-es-tuzijatek-a-fovarosban", "Ünnepi menet és  tűzijáték", "", "unknown", "missing", "incomplete"),
    ("https://hirportal.example/elet/2026/01/11/hosszu-cim-rovid-lejarattal", "", "", "missing", "missing", "incomplete"),
    ("https://hirportal.example/rovat/belfold", "", "", "missing", "missing", "incomplete"),
    ("https://hirportal.example/gazdasag/2026/01/15/uj-hirek", "Cím valid", "2026-01-15", "unknown", "unknown", "incomplete"),
    ("https://hirportal.example/gazdasag/2026/01/16/harmadik", "", "2026-01-16", "missing", "rss", "incomplete"),
    ("https://hirportal.example/elet/hibas-tipusok", "", "", "missing", "missing", "incomplete"),
    ("https://hirportal.example/kulfold/2026/01/13/nagy-tavolsagu-vonat-keses-az-alpokban/", "", "", "missing", "missing", "incomplete"),
    ("https://hirportal.example/belfold/2026/01/14/a-polgarmester-uj-hidat-avatott-a-folyon?utm_source=minta", "", "", "missing", "missing", "incomplete"),
]
EXPECTED_PROBLEMS = [
    (A, 2, "title", "missing"), (A, 3, "published_at", "missing"), (A, 4, "published_at", "missing_timezone"), (A, 5, "title", "missing"),
    (A, 5, "published_at", "invalid_date"), (A, 6, "url", "invalid_url"), (A, 7, "url", "missing"), (A, 8, None, "invalid_record"), (A, 9, "url", "duplicate_url"),
    (A, 10, "title", "missing"), (A, 10, "published_at", "missing"),
    (B, 0, "url", "duplicate_url"), (B, 1, "title_source", "source_contradiction"), (B, 1, "date_source", "unknown_value"), (B, 1, "status", "unknown_value"),
    (B, 2, "title", "missing"), (B, 2, "title_source", "source_contradiction"), (B, 2, "status", "status_mismatch"),
    (B, 3, "title", "invalid_type"), (B, 3, "published_at", "invalid_type"), (B, 3, "source", "invalid_type"), (B, 3, "fetched_at", "invalid_date"),
    (B, 3, "titel", "unknown_field"), (B, 4, "url", "duplicate_url"), (B, 5, "title", "missing"), (B, 5, "published_at", "missing"),
    (B, 6, "title", "missing"), (B, 6, "published_at", "missing"),
]


def test_fixture_rows_are_exactly_the_hand_checked_expectation(fix_out):
    got = [(r["url"], r["title"], r["published_at"], r["title_source"], r["date_source"], r["status"]) for r in tsv(fix_out)]
    assert got == EXPECTED_ROWS


def test_fixture_problems_are_exactly_the_hand_checked_expectation(fix_out):
    got = [(p["input_file"], p["record_index"], p["field"], p["reason"]) for p in jsonl(fix_out, "problems")]
    assert got == EXPECTED_PROBLEMS


def test_fixture_run_exit_code_and_manifest(tmp_path, fix_out):
    man = json.loads((fix_out / N.FILES["manifest"]).read_text(encoding="utf-8"))
    assert man["counts"]["rows"] == 12 and man["counts"]["problems"] == 28 and man["counts"]["file_errors"] == 0 and man["contains_synthetic"] is True
    assert [i["input_file"] for i in man["inputs"]] == [A, B] and all(i["status"] == "ok" and i["synthetic"] is True for i in man["inputs"])
    for i in man["inputs"]:
        raw = (FIX / i["input_file"]).read_bytes()
        assert i["sha256"] == hashlib.sha256(raw).hexdigest() and i["bytes"] == len(raw)
    for name, digest in man["outputs"].items():
        assert digest == hashlib.sha256((fix_out / name).read_bytes()).hexdigest()


# ---------------------------------------------------------------- determinizmus

def test_repeated_run_is_byte_identical_for_every_output(tmp_path):
    a = snapshot(go(tmp_path, FIX, "one")[1])
    b = snapshot(go(tmp_path, FIX, "two")[1])
    assert a == b


def test_output_does_not_depend_on_where_the_input_directory_is(tmp_path):
    copy = tmp_path / "somewhere" / "else" / "copy"
    shutil.copytree(FIX, copy)
    a = snapshot(go(tmp_path, FIX, "one")[1])
    b = snapshot(go(tmp_path, copy, "two")[1])
    assert a == b
    blob = b"".join(a.values())
    assert str(tmp_path).encode() not in blob and b"/tmp" not in blob and b"/home" not in blob


def test_outputs_carry_no_run_time_or_random_id(tmp_path, monkeypatch):
    import datetime as dt
    real = dt.datetime

    class Boom(real):
        @classmethod
        def now(cls, *a, **k):
            raise AssertionError("a feldolgozás nem olvashatja az aktuális időt")

        @classmethod
        def utcnow(cls):
            raise AssertionError("a feldolgozás nem olvashatja az aktuális időt")
    monkeypatch.setattr(dt, "datetime", Boom)
    rc, out = go(tmp_path, FIX)
    assert rc == 0 and tsv(out)


def test_a_second_run_with_different_input_leaves_no_stale_rows_or_problems(tmp_path):
    go(tmp_path, FIX, "r")
    inp = tmp_path / "small"
    put(inp, "only.json", cap([{"url": U, "title": "Egy", "published_at": "2026-01-01"}]))
    rc, out = go(tmp_path, inp, "r")
    assert [r["url"] for r in tsv(out)] == [U] and jsonl(out, "problems") == [] and len(jsonl(out, "provenance")) == 1


# ---------------------------------------------------------------- deduplikálás: az első találat nyer, pontosan megmondott sorrendben

def test_first_hit_wins_across_files_and_the_dropped_content_is_not_used(tmp_path):
    inp = tmp_path / "in"
    put(inp, "b.json", cap([{"url": U, "title": "B cím", "published_at": "2026-02-02"}]))
    put(inp, "a.json", cap([{"url": U, "title": "A cím"}]))                 # a.json előbb jön, bár a b.json-t írtuk előbb
    rc, out = go(tmp_path, inp)
    assert [(r["title"], r["published_at"], r["status"]) for r in tsv(out)] == [("A cím", "", "incomplete")]       # a b.json dátuma nem hozzáfűződik
    dup = [p for p in jsonl(out, "problems") if p["reason"] == "duplicate_url"]
    assert dup == [{"url": U, "field": "url", "reason": "duplicate_url", "source": None, "input_file": "b.json", "record_index": 0}]
    assert jsonl(out, "provenance") == [{"url": U, "input_file": "a.json", "record_index": 0}]


def test_first_hit_wins_inside_a_file_and_records_come_before_links(tmp_path):
    inp = tmp_path / "in"
    put(inp, "a.json", cap([{"url": U, "title": "Első"}, {"url": U, "title": "Második"}], links=[U]))
    rc, out = go(tmp_path, inp)
    assert [r["title"] for r in tsv(out)] == ["Első"]
    assert [(p["record_index"], p["reason"]) for p in jsonl(out, "problems") if p["reason"] == "duplicate_url"] == [(1, "duplicate_url"), (2, "duplicate_url")]
    inp2 = tmp_path / "in2"
    put(inp2, "a.json", cap([{"url": U, "title": "Rekord"}], links=[U]))
    assert [r["title"] for r in tsv(go(tmp_path, inp2, "r2")[1])] == ["Rekord"]


def test_file_order_is_by_relative_path_not_by_creation_or_listing_order(tmp_path):
    inp = tmp_path / "in"
    put(inp, "z/last.json", cap([{"url": U, "title": "Z"}]))
    put(inp, "a/first.json", cap([{"url": U, "title": "A"}]))
    put(inp, "m.json", cap([{"url": U, "title": "M"}]))
    rc, out = go(tmp_path, inp)
    assert [r["title"] for r in tsv(out)] == ["A"] and jsonl(out, "provenance")[0]["input_file"] == "a/first.json"


def test_urls_are_never_rewritten_so_variants_stay_separate_rows(fix_out):
    urls = [r["url"] for r in tsv(fix_out)]
    assert "https://hirportal.example/kulfold/2026/01/13/nagy-tavolsagu-vonat-keses-az-alpokban/" in urls         # záró / megmarad, külön sor
    assert any(u.endswith("?utm_source=minta") for u in urls)                                                       # a paraméter megmarad, külön sor
    assert len(urls) == len(set(urls))


@pytest.mark.parametrize("a,b", [("https://X.example/p", "https://x.example/p"), ("https://x.example/p", "https://x.example/p/"),
                                 ("https://x.example/p", "https://x.example/p#f"), ("https://x.example/p", "http://x.example/p"), ("https://x.example:443/p", "https://x.example/p")])
def test_url_identity_is_exact_string_equality(tmp_path, a, b):
    inp = tmp_path / "in"
    put(inp, "a.json", cap([{"url": a}, {"url": b}]))
    rc, out = go(tmp_path, inp)
    assert [r["url"] for r in tsv(out)] == [a, b]                                                                    # egyik sem azonos, egyik sem íródott át


# ---------------------------------------------------------------- hiányzó és csak szóközből álló cím, hiányzó dátum

@pytest.mark.parametrize("title", [None, "", "   ", "\t\n", " \r\n\t ", "\N{LINE SEPARATOR}", "\N{NO-BREAK SPACE} \N{NO-BREAK SPACE}"])
def test_missing_or_whitespace_only_title_keeps_the_record_and_reports_it(tmp_path, title):
    rec = {"url": U, "published_at": "2026-01-01", "title": title}
    rows, problems, rc = one(tmp_path, rec)
    assert rc == 0 and [(r["url"], r["title"], r["title_source"], r["status"]) for r in rows] == [(U, "", "missing", "incomplete")]
    assert pairs(problems) == [("title", "missing")] and problems[0]["url"] == U and problems[0]["record_index"] == 0


def test_a_record_without_the_title_key_is_the_same_as_a_null_title(tmp_path):
    rows, problems, rc = one(tmp_path, {"url": U, "published_at": "2026-01-01"})
    assert rows[0]["title"] == "" and pairs(problems) == [("title", "missing")]


@pytest.mark.parametrize("date", [None, "", "  ", "\t"])
def test_missing_date_keeps_the_record_and_is_not_filled_from_the_url(tmp_path, date):
    url = "https://x.example/2026/01/14/hosszu-cim-sok-szoval"                       # az URL-ben dátum és szlug is van
    rows, problems, rc = one(tmp_path, {"url": url, "title": "Cím", "published_at": date})
    assert [(r["published_at"], r["date_source"], r["status"], r["title"]) for r in rows] == [("", "missing", "incomplete", "Cím")]
    assert pairs(problems) == [("published_at", "missing")]


def test_title_is_never_built_from_the_url_slug(tmp_path):
    rows, problems, rc = one(tmp_path, {"url": "https://x.example/2026/01/14/ez-egy-hosszu-szlug-cim"})
    assert rows[0]["title"] == "" and all("szlug" not in v for k, v in rows[0].items() if k != "url")


# ---------------------------------------------------------------- dátumformátum

@pytest.mark.parametrize("v", ["2026-01-14", "2026-02-28", "2024-02-29", "2026-01-14T08:30:00Z", "2026-01-14T08:30:00+01:00", "2026-01-14T08:30:00-12:30",
                               "2026-01-14T08:30:00.1Z", "2026-01-14T08:30:00.123456789+00:00", "2026-12-31T23:59:59Z"])
def test_check_date_accepts_and_keeps_the_value_unchanged(v):
    assert N.check_date(v) == (v, None)


@pytest.mark.parametrize("v,reason", [("2026-02-30", "invalid_date"), ("2025-02-29", "invalid_date"), ("2026-13-01", "invalid_date"), ("2026-00-10", "invalid_date"),
                                      ("2026-01-14T24:00:00Z", "invalid_date"), ("2026-01-14T23:60:00Z", "invalid_date"), ("2026-01-14T23:59:60Z", "invalid_date"),
                                      ("2026-01-14T08:30:00+24:00", "invalid_date"), ("2026-01-14T08:30:00+01:60", "invalid_date"),
                                      ("2026-01-14T08:30:00", "missing_timezone"), ("2026-01-14T08:30:00.5", "missing_timezone"),
                                      ("2026-01-14T08:30Z", "invalid_date"), ("2026-01-14t08:30:00z", "invalid_date"), ("2026-01-14 08:30:00Z", "invalid_date"),
                                      ("2026-01-14T08:30:00+0100", "invalid_date"), ("2026.01.14", "invalid_date"), ("20260114", "invalid_date"), ("tegnap", "invalid_date"),
                                      (" 2026-01-14", "invalid_date"), ("2026-01-14 ", "invalid_date"), ("２０２６-01-14", "invalid_date"), ("2026-01-14\n", "invalid_date"),
                                      (20260114, "invalid_type"), (2026.5, "invalid_type"), (True, "invalid_type"), (["2026-01-14"], "invalid_type"), ({}, "invalid_type"),
                                      (None, "missing"), ("", "missing"), ("   ", "missing")])
def test_check_date_rejects_with_a_fixed_reason(v, reason):
    assert N.check_date(v) == ("", reason)


def test_fetched_at_must_be_a_full_instant_with_a_zone_not_a_date():
    assert N.check_date("2026-01-14", True) == ("", "invalid_date")
    assert N.check_date("2026-01-14T08:30:00Z", True) == ("2026-01-14T08:30:00Z", None)


def test_invalid_published_at_keeps_the_record_with_an_empty_date_and_an_entry(tmp_path):
    rows, problems, rc = one(tmp_path, {"url": U, "title": "Cím", "published_at": "2026-01-14T08:30:00"})
    assert rows[0]["published_at"] == "" and rows[0]["date_source"] == "missing" and pairs(problems) == [("published_at", "missing_timezone")]


# ---------------------------------------------------------------- fetched_at

def test_fetched_at_is_only_what_the_input_recorded(tmp_path):
    rows, problems, rc = one(tmp_path, {"url": U, "title": "Cím", "published_at": "2026-01-01"})
    assert rows[0]["fetched_at"] == "" and not problems                                       # nincs a bemenetben: üres
    rows, _, _ = one(tmp_path, {"url": U}, "d", fetched_at="2026-01-15T10:00:00Z")
    assert rows[0]["fetched_at"] == "2026-01-15T10:00:00Z"                                    # a fájl alapértéke
    rows, _, _ = one(tmp_path, {"url": U, "fetched_at": "2026-02-01T00:00:00+01:00"}, "e", fetched_at="2026-01-15T10:00:00Z")
    assert rows[0]["fetched_at"] == "2026-02-01T00:00:00+01:00"                               # a rekord sajátja, változatlanul


def test_an_invalid_record_fetched_at_is_reported_and_not_replaced_by_the_default(tmp_path):
    rows, problems, rc = one(tmp_path, {"url": U, "fetched_at": "tegnap"}, fetched_at="2026-01-15T10:00:00Z")
    assert rows[0]["fetched_at"] == "" and ("fetched_at", "invalid_date") in pairs(problems)


def test_an_invalid_file_default_fetched_at_is_a_file_level_entry_and_rows_stay_empty(tmp_path):
    rows, problems, rc = one(tmp_path, {"url": U}, fetched_at="tegnap")
    assert rows[0]["fetched_at"] == "" and (None, "fetched_at", "invalid_date") in [(p["record_index"], p["field"], p["reason"]) for p in problems] and rc == 0


# ---------------------------------------------------------------- hibás mezőtípusok és szerkezetek

@pytest.mark.parametrize("field", ["title", "published_at", "source", "fetched_at", "title_source", "date_source", "status", "url"])
@pytest.mark.parametrize("bad", [1, 0, 1.5, True, False, ["x"], {"a": 1}])
def test_wrong_types_are_never_converted_to_text(tmp_path, field, bad):
    rec = {"url": U, "title": "Cím", "published_at": "2026-01-01"}
    rec[field] = bad
    rows, problems, rc = one(tmp_path, rec)
    blob = json.dumps(rows, ensure_ascii=False)
    if field == "url":
        assert rows == [] and [(p["field"], p["reason"], p["url"]) for p in problems] == [("url", "invalid_type", None)]
        return
    assert len(rows) == 1 and ("1" not in rows[0][field] and "True" not in rows[0][field] and "False" not in rows[0][field] and "['x']" not in blob and "{'a'" not in blob)
    assert (field, "invalid_type") in pairs(problems)
    if field in ("title", "published_at"):
        assert rows[0][field] == "" and rows[0]["status"] == "incomplete"


@pytest.mark.parametrize("content", [[], [1, 2], "szöveg", 5, None, True, [{"schema": 1, "synthetic": True, "records": []}]])
def test_top_level_must_be_an_object(tmp_path, content):
    inp = tmp_path / "in"
    put(inp, "bad.json", json.dumps(content))
    put(inp, "good.json", cap([{"url": U, "title": "Cím"}]))
    rc, out = go(tmp_path, inp)
    assert rc == 1
    assert [(p["input_file"], p["field"], p["reason"], p["record_index"], p["url"], p["source"]) for p in jsonl(out, "problems") if p["input_file"] == "bad.json"] == \
        [("bad.json", None, "invalid_structure", None, None, None)]
    assert [r["url"] for r in tsv(out)] == [U]                                                  # a másik fájl feldolgozódott


@pytest.mark.parametrize("top", [
    {"schema": "1", "synthetic": True, "records": []}, {"schema": 1.0, "synthetic": True, "records": []}, {"schema": True, "synthetic": True, "records": []},
    {"schema": 2, "synthetic": True, "records": []}, {"synthetic": True, "records": []}, {"schema": None, "synthetic": True, "records": []},
    {"schema": 1, "records": []}, {"schema": 1, "synthetic": "true", "records": []}, {"schema": 1, "synthetic": 1, "records": []}, {"schema": 1, "synthetic": None, "records": []},
    {"schema": 1, "synthetic": True}, {"schema": 1, "synthetic": True, "records": {}}, {"schema": 1, "synthetic": True, "records": "x"},
    {"schema": 1, "synthetic": True, "records": [], "links": "https://x.example/"}, {"schema": 1, "synthetic": True, "records": None},
    {"schema": 1, "synthetic": True, "links": {"a": 1}}])
def test_bad_top_level_structure_is_a_file_level_error(tmp_path, top):
    inp = tmp_path / "in"
    put(inp, "bad.json", top)
    rc, out = go(tmp_path, inp)
    assert rc == 1 and tsv(out) == []
    assert [(p["field"], p["reason"], p["record_index"]) for p in jsonl(out, "problems")] == [(None, "invalid_structure", None)]
    man = json.loads((out / N.FILES["manifest"]).read_text(encoding="utf-8"))
    assert man["inputs"][0]["status"] == "error" and man["counts"]["file_errors"] == 1


def test_either_container_alone_is_enough_and_unknown_top_level_keys_are_reported(tmp_path):
    inp = tmp_path / "in"
    put(inp, "l.json", cap(links=[U]))
    put(inp, "r.json", {**cap([{"url": U + "2", "title": "C"}]), "input_file": "HAMIS.json", "extra": 1})
    rc, out = go(tmp_path, inp)
    assert rc == 0 and [r["url"] for r in tsv(out)] == [U, U + "2"]
    assert [(p["input_file"], p["field"], p["reason"]) for p in jsonl(out, "problems") if p["reason"] == "unknown_field"] == \
        [("r.json", "extra", "unknown_field"), ("r.json", "input_file", "unknown_field")]
    assert {o["input_file"] for o in jsonl(out, "provenance")} == {"l.json", "r.json"}                  # a HAMIS.json állítás nem számít


@pytest.mark.parametrize("item", [None, 5, 1.5, True, "szöveg", ["x"], [], 0])
def test_a_non_object_in_records_is_an_invalid_record_entry(tmp_path, item):
    inp = tmp_path / "in"
    put(inp, "a.json", cap([{"url": U, "title": "Cím"}, item], source="Forrás"))
    rc, out = go(tmp_path, inp)
    assert rc == 0 and len(tsv(out)) == 1
    assert [(p["url"], p["field"], p["reason"], p["source"], p["input_file"], p["record_index"]) for p in jsonl(out, "problems") if p["reason"] == "invalid_record"] == \
        [(None, None, "invalid_record", "Forrás", "a.json", 1)]


@pytest.mark.parametrize("item", [None, 5, True, ["https://x.example/"], {"url": "https://x.example/"}])
def test_a_non_string_in_links_is_an_invalid_record_entry_with_a_continued_index(tmp_path, item):
    inp = tmp_path / "in"
    put(inp, "a.json", cap([{"url": U}], links=[item]))
    rc, out = go(tmp_path, inp)
    assert [(p["reason"], p["record_index"]) for p in jsonl(out, "problems") if p["reason"] == "invalid_record"] == [("invalid_record", 1)]


# ---------------------------------------------------------------- hibás URL

@pytest.mark.parametrize("url", ["https://example.com", "http://example.com/", "https://sub.example.hu/a/b?x=1&y=2#frag", "HTTPS://Example.COM/P", "http://127.0.0.1:8080/x",
                                 "https://x.example:443/p", "https://x.example/a%20b", "https://x.example/ékezetes-út", "https://x.example/?q=a+b"])
def test_check_url_accepts(url):
    assert N.check_url(url) is None


@pytest.mark.parametrize("url", ["nem url", "x.example/p", "//x.example/p", "ftp://x.example/p", "file:///etc/passwd", "javascript:alert(1)", "mailto:a@x.example",
                                 "https://", "https:///p", "https://x.example:/p", "https://x.example:0/p", "https://x.example:70000/p", "https://x.example:ab/p",
                                 "https://user@x.example/p", "https://user:pw@x.example/p", "https://-x.example/p", "https://x.example-/p", "https://.x.example/p",
                                 "https://x..example/p", "https://x.example./p", "https://árvíz.example/p", "https://[::1]/p", "https://x_y.example/p",
                                 "https://x.example/a b", "https://x.example/a\tb", "https://x.example/a\nb", "https://x.example/a\rb", "https://x.example/a\x00b",
                                 "https://x.example/a\N{LINE SEPARATOR}b", "https://x.example/a\N{NO-BREAK SPACE}b", " https://x.example/p", "https://x.example/p ", "https://x.example/p\n",
                                 "\thttps://x.example/p", "https://x.example/" + "a" * 2100, "http:/x.example/p", "https:x.example/p"])
def test_check_url_rejects_without_repairing(url):
    assert N.check_url(url) == "invalid_url"


@pytest.mark.parametrize("url,reason", [(None, "missing"), ("", "missing"), (5, "invalid_type"), (["https://x.example/"], "invalid_type"), (True, "invalid_type")])
def test_check_url_missing_and_wrong_type(url, reason):
    assert N.check_url(url) == reason


@pytest.mark.parametrize("bad", ["https://x.example/a\tb", "https://x.example/a\nb", " https://x.example/p", "https://x.example/p\n", "https://x.example/a\N{LINE SEPARATOR}b", "nem url", "ftp://x.example/p"])
def test_a_bad_url_is_not_repaired_not_exported_and_reported_with_the_raw_value(tmp_path, bad):
    rows, problems, rc = one(tmp_path, {"url": bad, "title": "Cím", "published_at": "2026-01-01"}, source="Forrás")
    assert rows == [] and rc == 0
    assert problems == [{"url": bad, "field": "url", "reason": "invalid_url", "source": "Forrás", "input_file": "a.json", "record_index": 0}]       # az eredeti, javítatlan érték


def test_a_missing_or_wrong_typed_url_has_a_null_url_in_the_entry_not_an_invented_placeholder(tmp_path):
    for i, rec in enumerate([{"title": "x"}, {"url": None}, {"url": ""}, {"url": 7}, {"url": ["a"]}]):
        rows, problems, rc = one(tmp_path, rec, f"u{i}")
        assert rows == [] and len(problems) == 1 and problems[0]["url"] is None and problems[0]["field"] == "url"
        assert problems[0]["reason"] in ("missing", "invalid_type") and "MISSING" not in json.dumps(problems)


def test_a_link_with_an_empty_string_is_a_missing_url(tmp_path):
    inp = tmp_path / "in"
    put(inp, "a.json", cap(links=["", "   "]))
    rc, out = go(tmp_path, inp)
    assert [(p["url"], p["reason"], p["record_index"]) for p in jsonl(out, "problems")] == [(None, "missing", 0), ("   ", "invalid_url", 1)]


# ---------------------------------------------------------------- sérült bemeneti fájl

@pytest.mark.parametrize("raw", [b"{nem json", b"", b"   ", b'{"schema": 1,', b"\xff\xfe\x00{", b"\xef\xbb\xbf" + json.dumps(cap([])).encode(),
                                 b'{"schema": 1, "schema": 1, "synthetic": true, "records": []}', b'{"schema": 1, "synthetic": true, "records": [NaN]}',
                                 b'{"schema": 1, "synthetic": true, "records": [Infinity]}', b"\x80\x81\x82"])
def test_a_corrupt_file_is_a_file_level_error_and_the_run_is_not_a_full_success(tmp_path, raw, capsys):
    inp = tmp_path / "in"
    put(inp, "b_corrupt.json", raw)
    put(inp, "a_good.json", cap([{"url": U, "title": "Cím", "published_at": "2026-01-01"}]))
    rc, out = go(tmp_path, inp)
    assert rc == 1
    assert [(p["input_file"], p["field"], p["reason"], p["record_index"]) for p in jsonl(out, "problems")] == [("b_corrupt.json", None, "invalid_json", None)]
    assert [r["url"] for r in tsv(out)] == [U]
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "completed_with_file_errors" and summary["file_errors"] == ["b_corrupt.json"]
    man = json.loads((out / N.FILES["manifest"]).read_text(encoding="utf-8"))
    assert {i["input_file"]: i["status"] for i in man["inputs"]} == {"a_good.json": "ok", "b_corrupt.json": "error"}


def test_a_symlink_pointing_outside_the_input_directory_is_not_read(tmp_path):
    secret = put(tmp_path / "outside", "other.json", cap([{"url": U, "title": "Kívülről"}]))
    inp = tmp_path / "in"
    inp.mkdir()
    try:
        (inp / "link.json").symlink_to(secret)
    except OSError:
        pytest.skip("a szimbolikus hivatkozás nem hozható létre")
    rc, out = go(tmp_path, inp)
    assert rc == 1 and tsv(out) == []
    assert [(p["input_file"], p["reason"]) for p in jsonl(out, "problems")] == [("link.json", "invalid_file")]


def test_only_lowercase_json_files_are_read_recursively(tmp_path):
    inp = tmp_path / "in"
    put(inp, "a/b/c.json", cap([{"url": U}]))
    put(inp, "x.JSON", cap([{"url": U + "9"}]))
    put(inp, "y.txt", "nem json")
    (inp / "dir.json").mkdir()
    rc, out = go(tmp_path, inp)
    assert rc == 0 and [o["input_file"] for o in jsonl(out, "provenance")] == ["a/b/c.json"]


# ---------------------------------------------------------------- mezőeredet, ellentmondás, ismeretlen érték, státusz

@pytest.mark.parametrize("claim", ["rss", "page", "manual", "unknown"])
def test_a_valid_claim_is_kept_for_a_present_value(tmp_path, claim):
    rows, problems, rc = one(tmp_path, {"url": U, "title": "Cím", "published_at": "2026-01-01", "title_source": claim, "date_source": claim})
    assert (rows[0]["title_source"], rows[0]["date_source"], rows[0]["status"]) == (claim, claim, "ok") and problems == []


def test_a_present_value_without_a_claim_gets_unknown_not_a_verified_origin(tmp_path):
    rows, problems, rc = one(tmp_path, {"url": U, "title": "Cím", "published_at": "2026-01-01"})
    assert (rows[0]["title_source"], rows[0]["date_source"]) == ("unknown", "unknown") and problems == []


@pytest.mark.parametrize("claim", ["rss", "page", "manual", "unknown"])
def test_a_source_claim_for_a_missing_title_or_date_is_a_contradiction_both_ways(tmp_path, claim):
    rows, problems, rc = one(tmp_path, {"url": U, "title_source": claim, "date_source": claim})
    assert (rows[0]["title_source"], rows[0]["date_source"]) == ("missing", "missing")
    assert pairs(problems) == [("title", "missing"), ("published_at", "missing"), ("title_source", "source_contradiction"), ("date_source", "source_contradiction")]


def test_the_claim_missing_for_a_present_value_is_a_contradiction_and_the_origin_becomes_unknown(tmp_path):
    rows, problems, rc = one(tmp_path, {"url": U, "title": "Cím", "published_at": "2026-01-01", "title_source": "missing", "date_source": "missing"})
    assert (rows[0]["title"], rows[0]["published_at"], rows[0]["title_source"], rows[0]["date_source"], rows[0]["status"]) == ("Cím", "2026-01-01", "unknown", "unknown", "incomplete")
    assert pairs(problems) == [("title_source", "source_contradiction"), ("date_source", "source_contradiction")]


def test_an_explicit_missing_claim_for_a_missing_value_is_consistent(tmp_path):
    rows, problems, rc = one(tmp_path, {"url": U, "title_source": "missing", "date_source": "missing"})
    assert pairs(problems) == [("title", "missing"), ("published_at", "missing")] and (rows[0]["title_source"], rows[0]["date_source"]) == ("missing", "missing")


def test_a_claim_for_an_invalid_not_missing_value_adds_no_extra_contradiction(tmp_path):
    rows, problems, rc = one(tmp_path, {"url": U, "title": 5, "published_at": "tegnap", "title_source": "rss", "date_source": "rss"})
    assert pairs(problems) == [("title", "invalid_type"), ("published_at", "invalid_date")] and (rows[0]["title_source"], rows[0]["date_source"]) == ("missing", "missing")


@pytest.mark.parametrize("claim", ["xyz", "RSS", "Rss", " rss", "feed", "input", "", "1"])
def test_an_unknown_claim_is_reported_and_never_copied_into_the_output(tmp_path, claim):
    rows, problems, rc = one(tmp_path, {"url": U, "title": "Cím", "published_at": "2026-01-01", "title_source": claim, "date_source": claim})
    expected = [("title_source", "unknown_value"), ("date_source", "unknown_value")]
    assert pairs(problems) == expected and (rows[0]["title_source"], rows[0]["date_source"]) == ("unknown", "unknown") and rows[0]["status"] == "incomplete"
    assert claim not in (rows[0]["title_source"], rows[0]["date_source"])


@pytest.mark.parametrize("claim", [1, True, ["rss"], {"a": 1}])
def test_a_non_text_claim_is_a_type_error_entry(tmp_path, claim):
    rows, problems, rc = one(tmp_path, {"url": U, "title": "Cím", "published_at": "2026-01-01", "title_source": claim})
    assert pairs(problems) == [("title_source", "invalid_type")] and rows[0]["title_source"] == "unknown"


@pytest.mark.parametrize("claimed,computed_title,expected", [
    ("ok", "Cím", []), ("incomplete", "", []), ("incomplete", "Cím", [("status", "status_mismatch")]), ("ok", "", [("status", "status_mismatch")]),
    ("done", "Cím", [("status", "unknown_value")]), ("OK", "Cím", [("status", "unknown_value")]), (1, "Cím", [("status", "invalid_type")]), (True, "", [("status", "invalid_type")])])
def test_the_status_is_computed_never_taken_from_the_input(tmp_path, claimed, computed_title, expected):
    rec = {"url": U, "published_at": "2026-01-01", "status": claimed}
    if computed_title:
        rec["title"] = computed_title
    rows, problems, rc = one(tmp_path, rec)
    want = "ok" if computed_title else "incomplete"
    assert rows[0]["status"] == want
    assert [x for x in pairs(problems) if x[0] == "status"] == expected


def test_status_is_incomplete_when_any_relevant_field_has_a_problem_even_if_title_and_date_are_valid(tmp_path):
    for i, extra in enumerate([{"source": ["x"]}, {"fetched_at": "tegnap"}, {"title_source": "xyz"}, {"date_source": "missing"}]):
        rows, problems, rc = one(tmp_path, {"url": U, "title": "Cím", "published_at": "2026-01-01", **extra}, f"s{i}")
        assert rows[0]["status"] == "incomplete", extra
    rows, problems, rc = one(tmp_path, {"url": U, "title": "Cím", "published_at": "2026-01-01", "valami": 1}, "ok")
    assert rows[0]["status"] == "ok" and pairs(problems) == [("valami", "unknown_field")]                       # ismeretlen kulcs nem rontja a státuszt


def test_every_exported_row_is_internally_consistent(fix_out):
    for r in tsv(fix_out):
        assert r["title_source"] in N.TITLE_SOURCES and r["date_source"] in N.DATE_SOURCES and r["status"] in N.STATUSES
        assert (r["title_source"] == "missing") == (r["title"] == "") and (r["date_source"] == "missing") == (r["published_at"] == "")
        if r["status"] == "ok":
            assert r["title"] and r["published_at"]
        assert N.check_url(r["url"]) is None
        if r["published_at"]:
            assert N.check_date(r["published_at"])[1] is None
        if r["fetched_at"]:
            assert N.check_date(r["fetched_at"], True)[1] is None


# ---------------------------------------------------------------- provenance több konténer esetén

def test_input_file_comes_from_the_real_relative_path_not_from_the_content(tmp_path):
    inp = tmp_path / "in"
    put(inp, "sub/dir/real.json", {**cap([{"url": U, "title": "Cím", "input_file": "HAMIS.json"}]), "input_file": "MASIK.json", "capture_id": "NEM_EZ.json"})
    rc, out = go(tmp_path, inp)
    assert {p["input_file"] for p in jsonl(out, "problems")} == {"sub/dir/real.json"}
    assert [o["input_file"] for o in jsonl(out, "provenance")] == ["sub/dir/real.json"]
    everything = "".join((out / n).read_text(encoding="utf-8") for n in N.FILES.values())
    assert "HAMIS" not in everything and "MASIK" not in everything and "NEM_EZ" not in everything               # a tartalom állításai sehol nem jelennek meg
    assert [(p["field"], p["reason"]) for p in jsonl(out, "problems") if p["reason"] == "unknown_field"] == [("input_file", "unknown_field"), ("input_file", "unknown_field")]


def test_record_index_continues_across_containers_and_is_unique_within_a_file(tmp_path):
    inp = tmp_path / "in"
    put(inp, "a.json", cap([{"url": U + "0"}, {"url": U + "1"}, 7], links=[U + "3", None, "ftp://x.example/"]))
    rc, out = go(tmp_path, inp)
    prov = {o["url"]: o["record_index"] for o in jsonl(out, "provenance")}
    assert prov == {U + "0": 0, U + "1": 1, U + "3": 3}
    by_index = {}
    for p in jsonl(out, "problems"):
        by_index.setdefault(p["record_index"], set()).add((p["url"], p["field"]))
    assert by_index[2] == {(None, None)} and by_index[4] == {(None, None)} and by_index[5] == {("ftp://x.example/", "url")}
    assert all(i is None or 0 <= i <= 5 for i in by_index)
    indexes = [o["record_index"] for o in jsonl(out, "provenance")] + [p["record_index"] for p in jsonl(out, "problems") if p["reason"] in ("invalid_record", "invalid_url", "duplicate_url")]
    assert len(indexes) == len(set(indexes))                                                       # a konténerek között nincs index-ütközés


def test_every_provenance_line_points_to_the_record_that_produced_the_row(fix_out):
    rows = tsv(fix_out)
    prov = jsonl(fix_out, "provenance")
    assert [p["url"] for p in prov] == [r["url"] for r in rows]
    for p in prov:
        data = json.loads((FIX / p["input_file"]).read_text(encoding="utf-8"))
        items = list(data.get("records", [])) + list(data.get("links", []))
        item = items[p["record_index"]]
        assert (item["url"] if isinstance(item, dict) else item) == p["url"]


def test_problem_entries_have_exactly_the_documented_keys_in_order_and_one_problem_per_line(fix_out):
    raw = (fix_out / N.FILES["problems"]).read_text(encoding="utf-8").split("\n")[:-1]
    assert len(raw) == len(EXPECTED_PROBLEMS)
    for line in raw:
        obj = json.loads(line)
        assert tuple(obj) == N.PROBLEM_KEYS and "\n" not in line
        assert obj["reason"] in N.REASONS and (obj["field"] is None or isinstance(obj["field"], str))
        assert obj["input_file"] and (obj["record_index"] is None or (type(obj["record_index"]) is int and obj["record_index"] >= 0))
    for line in (fix_out / N.FILES["provenance"]).read_text(encoding="utf-8").split("\n")[:-1]:
        assert tuple(json.loads(line)) == N.PROVENANCE_KEYS


def test_one_record_can_have_several_problem_lines(fix_out):
    probs = [p for p in jsonl(fix_out, "problems") if p["input_file"] == B and p["record_index"] == 3]
    assert len(probs) == 5 and len({(p["field"], p["reason"]) for p in probs}) == 5


def test_unknown_values_are_json_null_in_the_problem_list(fix_out):
    probs = jsonl(fix_out, "problems")
    nulls = [p for p in probs if p["url"] is None]
    assert nulls and all(p["reason"] in ("missing", "invalid_record") for p in nulls)
    assert any(p["source"] is None for p in probs) and not any(v in ("", "MISSING_URL", "NONE", "null", "None") for p in probs for v in p.values() if isinstance(v, str))


def test_problem_order_is_deterministic_and_follows_the_documented_sort(fix_out):
    probs = jsonl(fix_out, "problems")
    rank = {name: i for i, name in enumerate(N.COLUMNS)}
    key = lambda p: (p["input_file"], -1 if p["record_index"] is None else p["record_index"], rank.get(p["field"], 100) if p["field"] else -1, p["field"] or "", p["reason"])
    assert probs == sorted(probs, key=key)


# ---------------------------------------------------------------- TSV

def test_tsv_header_is_exact_and_every_line_has_the_same_number_of_columns(fix_out):
    blob = (fix_out / N.FILES["tsv"]).read_bytes()
    assert blob.startswith(b"url\ttitle\tpublished_at\tsource\ttitle_source\tdate_source\tfetched_at\tstatus\n")
    assert N.COLUMNS == ("url", "title", "published_at", "source", "title_source", "date_source", "fetched_at", "status")
    assert not blob.startswith(b"\xef\xbb\xbf") and b"\r" not in blob and blob.endswith(b"\n") and not blob.endswith(b"\n\n")
    physical = blob.split(b"\n")[:-1]
    assert len(physical) == len(tsv(fix_out)) + 1 == len(blob.decode("utf-8").splitlines())                    # egy rekord egy fizikai sor
    with open(fix_out / N.FILES["tsv"], encoding="utf-8", newline="") as fh:
        parsed = list(csv.reader(fh, delimiter="\t"))
    assert len(parsed) == len(physical) and all(len(r) == 8 for r in parsed) and parsed[0] == list(N.COLUMNS)


def test_quotes_accents_tabs_and_line_breaks_in_text_fields(tmp_path):
    title = 'Azt mondta: "Szia!"\tés\r\nmás\nsor, „idézet” – űŰőŐ éÉ'
    rows, problems, rc = one(tmp_path, {"url": U, "title": title, "published_at": "2026-01-01", "source": "Forrás\t„X”\n"})
    assert rows[0]["title"] == 'Azt mondta: "Szia!" és  más sor, „idézet” – űŰőŐ éÉ'                      # mindegyik tabulátor/\r/\n egy-egy szóköz
    assert rows[0]["source"] == "Forrás „X”" and problems == []
    raw = (tmp_path / "r" / N.OUT_SUBDIR / N.FILES["tsv"]).read_bytes().decode("utf-8")
    assert '"Azt mondta: ""Szia!"" ' in raw                                                                 # az idézést a csv modul végezte: a mező idézve, az idézőjel megkettőzve
    assert len(raw.split("\n")) == 3 and raw.count("\t") == 14                                             # fejléc + 1 sor + záró sortörés; soronként 7 tabulátor


@pytest.mark.parametrize("ch", ["\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\N{LINE SEPARATOR}", "\N{PARAGRAPH SEPARATOR}"])
def test_every_line_breaking_character_in_text_becomes_a_space(tmp_path, ch):
    rows, problems, rc = one(tmp_path, {"url": U, "title": f"a{ch}b"})
    assert rows[0]["title"] == "a b" and problems[0]["field"] == "published_at"
    raw = (tmp_path / "r" / N.OUT_SUBDIR / N.FILES["tsv"]).read_bytes().decode("utf-8")
    assert len(raw.splitlines()) == 2


@pytest.mark.parametrize("ch", ["\x00", "\x01", "\x07", "\x1f", "\x7f", chr(0xE000)])
def test_other_control_characters_make_the_text_invalid_not_silently_cleaned(tmp_path, ch):
    rows, problems, rc = one(tmp_path, {"url": U, "title": f"a{ch}b", "published_at": "2026-01-01"})
    assert rows[0]["title"] == "" and ("title", "control_character") in pairs(problems)


def test_text_length_limits(tmp_path):
    ok, _, _ = one(tmp_path, {"url": U, "title": "x" * N.MAX_TITLE, "source": "s" * N.MAX_SOURCE}, "ok")
    assert len(ok[0]["title"]) == N.MAX_TITLE and len(ok[0]["source"]) == N.MAX_SOURCE
    rows, problems, rc = one(tmp_path, {"url": U, "title": "x" * (N.MAX_TITLE + 1), "source": "s" * (N.MAX_SOURCE + 1)}, "long")
    assert rows[0]["title"] == "" and rows[0]["source"] == "" and {("title", "too_long"), ("source", "too_long")} <= set(pairs(problems))


def test_urls_in_the_tsv_are_exactly_the_input_urls(tmp_path):
    urls = ["https://x.example/a%20b?q=%22x%22&r=a+b#f", "https://x.example/ékezetes-út", 'https://x.example/idézőjel"van', "https://x.example/a,b;c"]
    inp = tmp_path / "in"
    put(inp, "a.json", cap([{"url": u, "title": "C"} for u in urls]))
    rc, out = go(tmp_path, inp)
    assert [r["url"] for r in tsv(out)] == urls


def test_the_tsv_roundtrips_through_the_csv_reader_for_awkward_values(tmp_path):
    titles = ['"', '""', '"x"', "a,b", "a;b", "a\"b\"c", "=1+1", "'", "\\", "a\\tb", "tab\there", "ő", "😀 emoji", " " * 3 + "x" + " " * 3]
    inp = tmp_path / "in"
    put(inp, "a.json", cap([{"url": f"{U}/{i}", "title": t} for i, t in enumerate(titles)]))
    rc, out = go(tmp_path, inp)
    expect = [t.replace("\t", " ").strip() for t in titles]
    assert [r["title"] for r in tsv(out)] == expect
    assert len((out / N.FILES["tsv"]).read_bytes().split(b"\n")) == len(titles) + 2


def test_write_tsv_accepts_only_text(tmp_path):
    row = {c: "" for c in N.COLUMNS}
    with pytest.raises(TypeError):
        N.write_tsv(tmp_path / "x.tsv", [{**row, "title": 5}])
    assert not (tmp_path / "x.tsv").exists()


def test_the_source_files_are_never_modified(tmp_path):
    before = {p.relative_to(FIX).as_posix(): p.read_bytes() for p in FIX.rglob("*") if p.is_file()}
    go(tmp_path, FIX)
    assert before == {p.relative_to(FIX).as_posix(): p.read_bytes() for p in FIX.rglob("*") if p.is_file()}


# ---------------------------------------------------------------- JSONL: üres hiánylista és felülírás

def test_an_error_free_run_writes_an_empty_problem_file_and_overwrites_the_old_content(tmp_path):
    out_dir = tmp_path / "res" / N.OUT_SUBDIR
    out_dir.mkdir(parents=True)
    for name in N.FILES.values():
        (out_dir / name).write_text("RÉGI TARTALOM\n" * 5, encoding="utf-8")
    inp = tmp_path / "in"
    put(inp, "a.json", cap([{"url": U, "title": "Cím", "published_at": "2026-01-01", "title_source": "rss", "date_source": "page", "source": "Forrás"}]))
    rc, out = go(tmp_path, inp)
    assert rc == 0 and out == out_dir
    assert (out / N.FILES["problems"]).exists() and (out / N.FILES["problems"]).read_bytes() == b""
    assert "RÉGI" not in "".join((out / n).read_text(encoding="utf-8") for n in N.FILES.values())
    assert [r["status"] for r in tsv(out)] == ["ok"] and len(jsonl(out, "provenance")) == 1


def test_an_empty_input_directory_writes_a_header_only_tsv_and_empty_jsonl_files(tmp_path):
    (tmp_path / "empty").mkdir()
    rc, out = go(tmp_path, tmp_path / "empty")
    assert rc == 0 and (out / N.FILES["tsv"]).read_bytes() == b"url\ttitle\tpublished_at\tsource\ttitle_source\tdate_source\tfetched_at\tstatus\n"
    assert (out / N.FILES["problems"]).read_bytes() == b"" and (out / N.FILES["provenance"]).read_bytes() == b""


def test_jsonl_keeps_accents_and_keeps_line_separators_out_of_the_physical_lines(tmp_path):
    bad = "https://x.example/a\N{LINE SEPARATOR}b\N{PARAGRAPH SEPARATOR}c\u0085d"
    inp = tmp_path / "in"
    put(inp, "ékezetes_név.json", cap([{"url": bad}, {"url": U, "source": 5}], source="Hírportál (űrlap)"))
    rc, out = go(tmp_path, inp)
    text = (out / N.FILES["problems"]).read_text(encoding="utf-8")
    assert "\N{LINE SEPARATOR}" not in text and "\N{PARAGRAPH SEPARATOR}" not in text and "\u0085" not in text and "\\u2028" in text
    assert len(text.splitlines()) == len(text.split("\n")) - 1 == len(jsonl(out, "problems"))
    assert "ékezetes_név.json" in text and "Hírportál (űrlap)" in text
    assert jsonl(out, "problems")[0]["url"] == bad


# ---------------------------------------------------------------- értékkészletek és dokumentáció

def test_documented_value_sets_are_fixed_and_the_documentation_lists_each(fix_out):
    assert N.TITLE_SOURCES == N.DATE_SOURCES == ("rss", "page", "manual", "unknown", "missing") and N.STATUSES == ("ok", "incomplete")
    text = DOC.read_text(encoding="utf-8")
    for v in N.TITLE_SOURCES + N.STATUSES + N.REASONS + N.COLUMNS + N.PROBLEM_KEYS + N.PROVENANCE_KEYS + tuple(N.FILES.values()):
        assert f"`{v}`" in text, v
    for p in jsonl(fix_out, "problems"):
        assert p["reason"] in N.REASONS


def test_every_documented_reason_is_asserted_by_at_least_one_test_in_this_file():
    src = Path(__file__).read_text(encoding="utf-8")
    missing = [r for r in N.REASONS if f'"{r}"' not in src]                          # minden dokumentált ok szerepel legalább egy konkrét állításban
    assert not missing, missing


# ---------------------------------------------------------------- elkülönítés, használat, fixture-ök

def test_output_outside_the_results_dir_is_refused_and_nothing_is_written(tmp_path):
    outside = tmp_path / "elsewhere"
    assert N.main(["--input-dir", str(FIX), "--out-dir", str(outside)], base=tmp_path / "res") == 2
    assert not outside.exists()
    with pytest.raises(IsolationError):
        N.run(FIX, tmp_path / "res" / ".." / "x", tmp_path / "res")


def test_nested_input_and_output_directories_are_refused(tmp_path):
    res = tmp_path / "res"
    inp = res / "nested_in"
    put(inp, "a.json", cap([{"url": U}]))
    assert N.main(["--input-dir", str(inp), "--out-dir", str(res / "nested_in" / "out")], base=res) == 2
    assert N.main(["--input-dir", str(res), "--out-dir", str(res / "out")], base=res) == 2


def test_usage_errors_and_missing_input_directory_exit_with_2_and_write_nothing(tmp_path):
    assert N.main([], base=tmp_path / "res") == 2
    assert N.main(["--input-dir", str(tmp_path / "nincs")], base=tmp_path / "res") == 2
    (tmp_path / "file.json").write_text("{}", encoding="utf-8")
    assert N.main(["--input-dir", str(tmp_path / "file.json")], base=tmp_path / "res") == 2
    assert not (tmp_path / "res").exists()


def test_default_output_goes_under_the_results_dir_only(tmp_path):
    before = set(tmp_path.rglob("*"))
    rc, out = go(tmp_path, FIX)
    new = set(tmp_path.rglob("*")) - before
    assert out == tmp_path / "res" / "newsingest" and all(p == tmp_path / "res" or (tmp_path / "res") in p.parents for p in new)
    assert {p.name for p in out.iterdir()} == set(N.FILES.values())
    assert not [p for p in FIX.rglob("*") if p.name in N.FILES.values()]                         # a fixture-könyvtárba nem kerül generált kimenet


def test_repo_fixtures_are_small_marked_synthetic_and_free_of_secrets_and_real_hosts():
    files = sorted(FIX.rglob("*.json"))
    assert [p.relative_to(FIX).as_posix() for p in files] == [A, B]
    assert "results" not in FIX.relative_to(Path(N.__file__).resolve().parent).parts
    for p in files:
        text = p.read_text(encoding="utf-8")
        d = json.loads(text)
        assert d["synthetic"] is True and "SZINTETIKUS" in d["_note"] and len(text) < 4000
        assert not re.search(r"(?i)api[_-]?key|secret|token|password|bearer|gsk_|AIza|@", text)
        for h in re.findall(r"https?://([^/\"\s]+)", text):
            assert h.lower().split(":")[0].endswith(".example"), h


def test_module_imports_only_allowed_standard_library_and_pilot_paths_and_never_calls_str():
    src = Path(N.__file__).read_text(encoding="utf-8")
    names, str_calls = set(), []
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            names |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            names.add(("." * n.level) + (n.module or ""))
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "str":
            str_calls.append(n.lineno)
    assert names == {"argparse", "csv", "datetime", "hashlib", "json", "re", "sys", "unicodedata", "pathlib", ".paths"}
    assert "environ" not in src and "getenv" not in src
    assert not str_calls, f"tilos a str() hívás (nincs automatikus szöveggé alakítás): {str_calls}"
