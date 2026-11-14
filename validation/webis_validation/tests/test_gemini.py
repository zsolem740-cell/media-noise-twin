"""Gemini smoke test hálózat nélkül: kérésépítés, kimenő kérés ellenőrzése, válasz-besorolás, modellválasztás, száraz próba, futtató hamis átvitellel."""
import copy
import json
import re
from pathlib import Path

import pytest

from validation.webis_validation import gemini_request as gr
from validation.webis_validation import gemini_smoke as gs
from validation.webis_validation import loader, run, sample, scoring, synthetic
from validation.webis_validation.isolation import MODULE_DIR

MODEL = "gemini-3.1-flash-lite"
TEXTS = [f"Headline number {i} about the town budget and new bridge" for i in range(20)]
INPUTS = [{"id": f"id{i:02d}", "postText": t} for i, t in enumerate(TEXTS)]


def mj(text, scores=(1, 0, 2, 0)):
    w = text.split()[0]
    return {n: {"span": w if s else "", "reason": "brief reason", "score": s} for n, s in zip(scoring.SIGNALS, scores)}


def api(obj=None, text=None, finish="STOP", usage=(800, 180, 0), parts=None, status=200, extra=None):
    cand = {"content": {"parts": parts if parts is not None else [{"text": text if text is not None else json.dumps(obj)}]}, "finishReason": finish}
    d = {"candidates": [cand], "usageMetadata": {"promptTokenCount": usage[0], "candidatesTokenCount": usage[1], "thoughtsTokenCount": usage[2], "totalTokenCount": sum(usage)},
         "modelVersion": MODEL, **(extra or {})}
    return gs.Raw(status, json.dumps(d), 120)


def err(status, message="x", details=None):
    return gs.Raw(status, json.dumps({"error": {"code": status, "message": message, "details": details or []}}), 50)


class Clock:
    def __init__(self):
        self.t, self.sleeps = 1000.0, []

    def monotonic(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


class Script:
    """Hamis átvitel: sorban adja a megadott válaszokat; ha elfogy, a default függvény szerint válaszol. Rögzíti a kimenő kéréseket."""
    def __init__(self, items=None, default=None):
        self.items, self.calls = list(items or []), []
        self.default = default or (lambda body, text: api(mj(text)))

    def __call__(self, model, body):
        self.calls.append((model, body))
        text = body["contents"][0]["parts"][0]["text"].removeprefix("<post>\n").removesuffix("\n</post>")
        if self.items:
            x = self.items.pop(0)
            if isinstance(x, Exception):
                raise x
            return x(text) if callable(x) else x
        return self.default(body, text)


def smoke(tmp_path, cfg, transport, inputs=INPUTS, model=MODEL, reference=None, clock=None):
    clock = clock or Clock()
    results = tmp_path / "results"
    rep = gs.run_smoke(inputs, transport, cfg, results / "smoke_gemini", results, model, reference, sleep=clock.sleep, monotonic=clock.monotonic)
    return rep, results / "smoke_gemini", clock


def jl(p):
    return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()]


# ------------------------------------------------------------------ kérésépítés

def test_body_has_only_the_three_allowed_keys_and_one_user_message(cfg):
    b = gr.build_body("Some headline here", cfg)
    assert set(b) == {"systemInstruction", "contents", "generationConfig"}
    assert len(b["contents"]) == 1 and b["contents"][0]["role"] == "user" and len(b["contents"][0]["parts"]) == 1
    assert b["contents"][0]["parts"][0] == {"text": "<post>\nSome headline here\n</post>"}
    assert b["systemInstruction"] == {"parts": [{"text": gr.SYSTEM_INSTRUCTION}]}
    assert set(b["generationConfig"]) == {"responseMimeType", "responseSchema", "temperature", "maxOutputTokens"} and b["generationConfig"]["responseMimeType"] == "application/json"
    assert b["generationConfig"]["temperature"] == 0 and "thinkingConfig" not in b["generationConfig"]


def test_body_depends_only_on_the_post_text(cfg):
    assert gr.build_body("Same text here", cfg) == gr.build_body("Same text here", cfg)
    a, b = gr.build_body("First text here", cfg), gr.build_body("Second text here", cfg)
    assert a["systemInstruction"] == b["systemInstruction"] and a["generationConfig"] == b["generationConfig"] and a != b


def test_thinking_config_is_added_only_when_configured(cfg):
    c = copy.deepcopy(cfg)
    c["gemini"]["generation"]["thinking_config"] = {"thinkingLevel": "MINIMAL"}
    assert gr.build_body("Some headline here", c)["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "MINIMAL"}
    assert gr.check_request(gr.build_body("Some headline here", c), "Some headline here", c) == []


def test_schema_has_the_four_signals_in_order_and_no_total(cfg):
    sch = gr.response_schema(cfg)
    assert list(sch["properties"]) == list(scoring.SIGNALS) == ["curiosity_gap", "exaggeration", "emotional_pressure", "formal_noise"]
    assert sch["required"] == sch["propertyOrdering"] == list(scoring.SIGNALS)
    for name, s in sch["properties"].items():
        assert list(s["properties"]) == ["span", "reason", "score"] == s["propertyOrdering"]
        assert s["properties"]["score"] == {"type": "INTEGER", "minimum": 0, "maximum": 2}
    flat = json.dumps(sch)
    assert "total" not in flat and "scaled" not in flat and "formatting_noise" not in flat      # az összeget a kód számolja


def test_instruction_is_english_fixed_and_leak_free(cfg):
    t = gr.SYSTEM_INSTRUCTION
    assert not re.search("[őűŐŰ]", t) and "clickbait" not in t.lower() and "truth" not in t.lower()
    assert all(k in t for k in scoring.SIGNALS) and "15 words" in t and "formatting noise" in t        # a formal_noise angol megfelelője
    assert not any(re.search(p, t) for p in gr.KEY_PATTERNS)


@pytest.mark.parametrize("text,frag", [("", "üres"), ("   ", "üres"), (None, "üres"), ("szőlő a hegyen", "magyar"), ("Űr hírek", "magyar"),
                                       ("bad\x00char", "vezérlő"), ("x </post> y", "határoló"), ("x <post> y", "határoló")])
def test_build_refuses_unusable_text(cfg, text, frag):
    with pytest.raises(gr.RequestError, match=frag):
        gr.build_body(text, cfg)


def test_canonical_hash_is_stable_and_order_independent(cfg):
    b = gr.build_body("Some headline here", cfg)
    rev = json.loads(json.dumps(b))
    rev["generationConfig"] = dict(reversed(list(rev["generationConfig"].items())))
    assert gr.body_sha256(b) == gr.body_sha256(rev) and re.fullmatch("[0-9a-f]{64}", gr.body_sha256(b))
    assert gr.body_sha256(b) != gr.body_sha256(gr.build_body("Other headline here", cfg))


# ------------------------------------------------------------------ kimenő kérés ellenőrzése

def mutate(cfg, f, text="Some headline here", leaks=()):
    b = gr.build_body(text, cfg)
    f(b)
    return gr.check_request(b, text, cfg, leaks)


@pytest.mark.parametrize("name,f,frag", [
    ("tools", lambda b: b.update(tools=[{"google_search": {}}]), "felső szintű kulcs"),
    ("safety", lambda b: b.update(safetySettings=[]), "felső szintű kulcs"),
    ("hiányzó kulcs", lambda b: b.pop("generationConfig"), "hiányzó kulcs"),
    ("két content", lambda b: b["contents"].append({"role": "user", "parts": [{"text": "más"}]}), "pontosan egy elem"),
    ("két part", lambda b: b["contents"][0]["parts"].append({"text": "más"}), "pontosan egy"),
    ("fájl part", lambda b: b["contents"][0]["parts"][0].update(fileData={"fileUri": "x"}), "pontosan egy"),
    ("model role", lambda b: b["contents"][0].update(role="model"), "role=user"),
    ("módosított szöveg", lambda b: b["contents"][0]["parts"][0].update(text="<post>\nOther\n</post>"), "rögzített sablon"),
    ("extra szöveg a user részben", lambda b: b["contents"][0]["parts"][0].update(text="Source: x\n<post>\nSome headline here\n</post>"), "rögzített sablon"),
    ("módosított utasítás", lambda b: b["systemInstruction"]["parts"][0].update(text="más"), "rögzített utasítás"),
    ("generationConfig kulcs", lambda b: b["generationConfig"].update(tools=[]), "generationConfig"),
    ("tiltott mezőnév", lambda b: b["generationConfig"]["responseSchema"]["properties"].update(truthClass={"type": "STRING"}), "tiltott mezőnév"),
    ("összeg a sémában", lambda b: b["generationConfig"]["responseSchema"]["properties"].update(total={"type": "INTEGER"}), "tiltott mezőnév"),
    ("API-kulcs minta", lambda b: b["contents"][0]["parts"][0].update(text="<post>\nSome headline here AIzaSyA1234567890abcdefghij\n</post>"), "hitelesítésre"),
    ("kulcs fejléc", lambda b: b["systemInstruction"]["parts"][0].update(text=gr.SYSTEM_INSTRUCTION + " x-goog-api-key"), "hitelesítésre"),
    ("magyar karakter", lambda b: b["systemInstruction"]["parts"][0].update(text=gr.SYSTEM_INSTRUCTION + " őr"), "magyar-specifikus"),
])
def test_check_request_catches(cfg, name, f, frag):
    out = mutate(cfg, f)
    assert out and any(frag in e for e in out), (name, out)


def test_valid_body_passes_and_non_dict_is_rejected(cfg):
    assert mutate(cfg, lambda b: None) == []
    assert gr.check_request("nem szótár", "x", cfg) == ["a kérés nem szótár"]


def test_leak_strings_may_equal_the_post_text_but_not_appear_elsewhere(cfg):
    title = "Council approves the new bridge budget after long debate"
    assert gr.check_request(gr.build_body(title, cfg), title, cfg, leak_strings=[title]) == []        # a poszt szövege megengedett akkor is, ha egyezik a cikkcímmel
    b = gr.build_body("Other headline here", cfg)
    b["systemInstruction"]["parts"][0]["text"] += " " + title
    out = gr.check_request(b, "Other headline here", cfg, leak_strings=[title])
    assert any("rögzített részében" in e for e in out)
    assert gr.check_request(gr.build_body("Other headline here", cfg), "Other headline here", cfg, leak_strings=["short"]) == []     # 12 karakternél rövidet nem vizsgál


def test_label_strings_in_the_fixed_part_are_flagged(cfg, monkeypatch):
    monkeypatch.setattr(gr, "SYSTEM_INSTRUCTION", gr.SYSTEM_INSTRUCTION + " no-clickbait")
    b = gr.build_body("Some headline here", cfg)
    assert any("címkeszöveg" in e for e in gr.check_request(b, "Some headline here", cfg))


# ------------------------------------------------------------------ válasz-besorolás

def parse(raw, text="Headline number 1 about money", cfg=None):
    return gr.parse_response(raw.status, raw.text, text, "id1", cfg)


def test_ok_response_total_and_scale_are_computed_by_the_code(cfg):
    obj = mj("Headline number 1 about money", (2, 1, 0, 1))
    o = parse(api(obj), cfg=cfg)
    assert o.kind == "ok" and o.score["total"] == 4 and o.score["scaled"] == 0.5 and o.score["source"] == cfg["source"] and o.score["id"] == "id1"
    assert scoring.validate_score(o.score, "Headline number 1 about money", cfg) == []
    assert o.usage == {"promptTokenCount": 800, "candidatesTokenCount": 180, "thoughtsTokenCount": 0, "totalTokenCount": 980} and o.model_version == MODEL


def test_thought_parts_are_ignored(cfg):
    o = parse(api(parts=[{"text": "internal reasoning", "thought": True}, {"text": json.dumps(mj("Headline number 1 about money"))}]), cfg=cfg)
    assert o.kind == "ok"


@pytest.mark.parametrize("name,f", [
    ("modell összeget ad", lambda o: o.update(total=5)),
    ("modell skálázott értéket ad", lambda o: o.update(scaled=0.6)),
    ("hiányzó jel", lambda o: o.pop("formal_noise")),
    ("más nevű jel", lambda o: (o.pop("formal_noise"), o.update(formatting_noise=o_sig()))),
    ("extra mező a jelben", lambda o: o["exaggeration"].update(extra=1)),
    ("hiányzó mező a jelben", lambda o: o["exaggeration"].pop("span")),
    ("szöveges pont", lambda o: o["curiosity_gap"].update(score="2")),
    ("tartományon kívüli pont", lambda o: o["curiosity_gap"].update(score=3)),
    ("tört pont", lambda o: o["curiosity_gap"].update(score=1.5)),
    ("logikai pont", lambda o: o["curiosity_gap"].update(score=True)),
    ("a részlet nincs a címben", lambda o: o["curiosity_gap"].update(span="nincs benne")),
    ("pozitív pont üres részlettel", lambda o: o["curiosity_gap"].update(span="")),
    ("nulla pont részlettel", lambda o: o["exaggeration"].update(span="Headline")),
    ("hosszú indoklás", lambda o: o["curiosity_gap"].update(reason=" ".join(["w"] * 16))),
])
def test_invalid_model_outputs_are_classified_invalid(cfg, name, f):
    obj = mj("Headline number 1 about money")
    f(obj)
    o = parse(api(obj), cfg=cfg)
    assert o.kind == "invalid" and o.score is None, (name, o)


def o_sig():
    return {"span": "", "reason": "x", "score": 0}


def test_non_object_and_broken_json_outputs(cfg):
    for text in ("{rossz", "[]", "42", '"szöveg"', "null"):
        assert parse(api(text=text), cfg=cfg).kind == "invalid", text


def test_empty_candidates_and_empty_text(cfg):
    assert parse(gs.Raw(200, json.dumps({"candidates": []}), 1), cfg=cfg).kind == "empty"
    assert parse(gs.Raw(200, "{}", 1), cfg=cfg).kind == "empty"
    assert parse(api(text="  "), cfg=cfg).kind == "empty"
    assert parse(api(parts=[]), cfg=cfg).kind == "empty"


@pytest.mark.parametrize("fr", ["SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"])
def test_candidate_blocks_are_blocked_not_zero_scores(cfg, fr):
    o = parse(api(text="", finish=fr), cfg=cfg)
    assert o.kind == "blocked" and o.finish_reason == fr and o.score is None


def test_prompt_block_and_truncation_and_odd_finish(cfg):
    pb = gs.Raw(200, json.dumps({"promptFeedback": {"blockReason": "PROHIBITED_CONTENT"}, "usageMetadata": {"promptTokenCount": 5}}), 1)
    o = parse(pb, cfg=cfg)
    assert o.kind == "blocked" and o.block_reason == "PROHIBITED_CONTENT" and o.usage == {"promptTokenCount": 5}
    assert parse(api(text='{"curiosity_gap":', finish="MAX_TOKENS"), cfg=cfg).kind == "truncated"
    assert parse(api(obj=mj("Headline number 1 about money"), finish="OTHER"), cfg=cfg).kind == "invalid"


@pytest.mark.parametrize("raw,kind,delay", [
    (err(429, "quota", [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]), "quota_day", None),
    (err(429, "quota", [{"violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]}, {"retryDelay": "12s"}]), "quota_minute", 12.0),
    (err(429, "You exceeded your quota, limit per day reached"), "quota_day", None),
    (err(429, "slow down"), "quota_minute", None),
    (err(429, "x", [{"retryDelay": "7.5s"}]), "quota_minute", 7.5),
    (err(500), "transient", None), (err(503), "transient", None), (err(504), "transient", None),
    (err(400, "bad schema"), "fatal", None), (err(401), "fatal", None), (err(403), "fatal", None), (err(404, "model not found"), "fatal", None),
    (gs.Raw(502, "<html>bad gateway</html>", 1), "transient", None), (gs.Raw(400, "nem json", 1), "fatal", None),
])
def test_http_errors_are_classified(cfg, raw, kind, delay):
    o = parse(raw, cfg=cfg)
    assert o.kind == kind and o.retry_after == delay and o.score is None


# ------------------------------------------------------------------ modellválasztás

def listing(*names, methods=("generateContent", "countTokens")):
    return {"models": [{"name": f"models/{n}", "supportedGenerationMethods": list(methods)} for n in names]}


def test_choose_prefers_3_5_then_3_1_flash_lite(cfg):
    assert gs.choose_model(listing("gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-3.6-flash"), cfg) == "gemini-3.5-flash-lite"
    assert gs.choose_model(listing("gemini-3.6-flash", "gemini-3.1-flash-lite"), cfg) == "gemini-3.1-flash-lite"


def test_choose_accepts_suffixed_names_and_prefers_exact(cfg):
    assert gs.choose_model(listing("gemini-3.5-flash-lite-preview-11-2026"), cfg) == "gemini-3.5-flash-lite-preview-11-2026"
    assert gs.choose_model(listing("gemini-3.5-flash-lite-preview-11-2026", "gemini-3.5-flash-lite"), cfg) == "gemini-3.5-flash-lite"


def test_choose_skips_unusable_models(cfg):
    assert gs.choose_model(listing("gemini-3.5-flash-lite-tts", "gemini-3.1-flash-lite-image", "gemini-3.1-flash-lite"), cfg) == "gemini-3.1-flash-lite"
    with pytest.raises(gs.NeedUserDecision):
        gs.choose_model(listing("gemini-3.5-flash-lite", methods=("embedContent",)), cfg)
    assert gs.choose_model(listing("gemini-3.5-flash-lite", "gemini-3.5-flash-lite-live"), cfg) == "gemini-3.5-flash-lite"


def test_only_3_6_or_3_8_flash_stops_and_asks(cfg):
    for names in (("gemini-3.6-flash",), ("gemini-3.8-flash",), ("gemini-3.6-flash", "gemini-3.8-flash", "gemini-2.5-flash")):
        with pytest.raises(gs.NeedUserDecision, match="Állj meg és kérdezz") as e:
            gs.choose_model(listing(*names), cfg)
        assert "napi kerete kb. 20" in str(e.value) and all(n in str(e.value) for n in names if re.match(r"gemini-3\.[68]-flash", n))


def test_no_usable_model_stops_and_asks(cfg):
    for payload in (listing(), {}, None, listing("gemini-2.5-pro"), listing("gemini-3.5-flash")):
        with pytest.raises(gs.NeedUserDecision, match="Állj meg és kérdezz"):
            gs.choose_model(payload, cfg)


# ------------------------------------------------------------------ kiválasztás

def fake_records(counts=(30, 30, 30, 30)):
    out, i = [], 0
    for n, base in zip(counts, (0.05, 0.3, 0.55, 0.85)):
        for k in range(n):
            out.append(loader.Record(id=f"r{i:03d}", text=f"headline {i}", human_mean=base + (k % 5) * 0.01, human_median=base, judgments=(base,) * 5, n_annotators=5))
            i += 1
    return out


def test_select_five_per_stratum_round_robin_and_deterministic(cfg):
    recs = fake_records()
    ids = [r.id for r in recs]
    order, st = gs.select_smoke(recs, ids, cfg)
    assert len(order) == 20 == len(set(order))
    names = [s["name"] for s in cfg["sample"]["strata"]]
    assert [st[x] for x in order] == names * 5                              # váltakozó sorrend: korai leállásnál is minden réteg szerepel
    assert {n: sum(1 for x in order if st[x] == n) for n in names} == {n: 5 for n in names}
    assert gs.select_smoke(recs, list(reversed(ids)), cfg)[0] == order
    c2 = copy.deepcopy(cfg)
    c2["gemini"]["smoke"]["seed"] += 1
    assert gs.select_smoke(recs, ids, c2)[0] != order


def test_select_needs_enough_items_in_every_stratum(cfg):
    recs = fake_records((30, 30, 30, 4))
    with pytest.raises(sample.SampleError, match="csak 4 elem"):
        gs.select_smoke(recs, [r.id for r in recs], cfg)


def test_select_only_from_the_given_sample_ids(cfg):
    recs = fake_records()
    sample_ids = [r.id for r in recs if int(r.id[1:]) % 2 == 0]
    order, _ = gs.select_smoke(recs, sample_ids, cfg)
    assert set(order) <= set(sample_ids)


# ------------------------------------------------------------------ száraz próba végponttól végpontig

@pytest.fixture
def dry(tmp_path, cfg):
    data, results = tmp_path / "data", tmp_path / "results"
    results.mkdir()
    synthetic.write_corpus(data, n=1500, seed=9)
    c = copy.deepcopy(cfg)
    c["sample"].update(size=80, strata=[dict(s, target=20) for s in cfg["sample"]["strata"]])
    run.do_sample(c, data, results)
    rep = run.do_gemini_dryrun(c, data, results)
    return c, data, results, rep


def test_dryrun_end_to_end(dry):
    c, data, results, rep = dry
    assert rep["status"] == "OK" and rep["verification_errors"] == [] and rep["build_errors"] == [] and rep["n_requests"] == 20
    assert rep["strata_counts"] == {s["name"]: 5 for s in c["sample"]["strata"]} and rep["no_network"] and rep["api_key_used"] is False and rep["model"] is None
    out = results / "smoke_gemini"
    assert sorted(p.name for p in out.iterdir()) == ["dryrun_check.json", "requests_dryrun.jsonl", "selected_inputs.jsonl"]
    rows, inputs = jl(out / "requests_dryrun.jsonl"), jl(out / "selected_inputs.jsonl")
    assert len(rows) == 20 and all(set(r) == {"index", "id", "body_sha256", "body"} for r in rows) and all(list(x) == ["id", "postText"] for x in inputs)
    assert [r["index"] for r in rows] == list(range(20)) and [r["id"] for r in rows] == [x["id"] for x in inputs]
    raw = (out / "requests_dryrun.jsonl").read_text(encoding="utf-8")
    assert not any(re.search(p, raw) for p in gr.KEY_PATTERNS) and "truth" not in raw and "targetTitle" not in raw and "a cikk címe" not in raw
    assert not re.search("[őűŐŰ]", raw)
    for r, x in zip(rows, inputs):
        assert r["body"] == gr.build_body(x["postText"], c) and r["body_sha256"] == gr.body_sha256(r["body"])


def test_dryrun_files_stay_in_the_results_dir(dry):
    _, data, results, _ = dry
    assert {p.name for p in (results / "smoke_gemini").iterdir()} <= {"dryrun_check.json", "requests_dryrun.jsonl", "selected_inputs.jsonl"}
    assert not list(data.glob("*gemini*"))


def test_verification_catches_tampered_rows(dry):
    c, data, results, _ = dry
    out = results / "smoke_gemini"
    rows, inputs = jl(out / "requests_dryrun.jsonl"), jl(out / "selected_inputs.jsonl")
    strata_of = jl_dict(out / "dryrun_check.json")["strata_of"]
    assert gs.verify_dryrun_rows(rows, inputs, c, strata_of) == []

    def bad(f, frag):
        r2 = copy.deepcopy(rows)
        f(r2)
        errs = gs.verify_dryrun_rows(r2, inputs, c, strata_of)
        assert errs and any(frag in e for e in errs), (frag, errs)

    bad(lambda r: r[0]["body"].update(tools=[]), "felső szintű kulcs")
    bad(lambda r: r[1]["body"]["contents"].append({"role": "user", "parts": [{"text": "x"}]}), "pontosan egy elem")
    bad(lambda r: r[2]["body"]["contents"][0]["parts"][0].update(text="<post>\nmás\n</post>"), "rögzített sablon")
    bad(lambda r: r[3]["body"]["generationConfig"]["responseSchema"]["properties"].update(truthClass={}), "tiltott mezőnév")
    bad(lambda r: r[4].update(body_sha256="0" * 64), "body_sha256")
    bad(lambda r: r[5].update(extra=1), "mezői nem pontosan")
    bad(lambda r: r.pop(), "a kérések száma")
    bad(lambda r: r.reverse(), "sorrendje")
    bad(lambda r: r[6]["body"]["systemInstruction"]["parts"][0].update(text=gr.SYSTEM_INSTRUCTION + " szőlő"), "magyar-specifikus")
    bad(lambda r: r[7]["body"]["systemInstruction"]["parts"][0].update(text=gr.SYSTEM_INSTRUCTION + " x-goog-api-key: AIzaSyA1234567890abcdef"), "hitelesítésre")
    errs = gs.verify_dryrun_rows(rows, inputs, c, {**strata_of, rows[0]["id"]: "0.75-1"})
    assert any("rétegenkénti darabszám" in e for e in errs)


def jl_dict(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def test_dryrun_leak_detection_uses_the_article_and_human_fields(dry):
    c, data, results, _ = dry
    rows = jl(results / "smoke_gemini" / "requests_dryrun.jsonl")
    inputs = jl(results / "smoke_gemini" / "selected_inputs.jsonl")
    leak = "Secret article paragraph that must never reach the model"
    rows[0]["body"]["systemInstruction"]["parts"][0]["text"] += " " + leak
    errs = gs.verify_dryrun_rows(rows, inputs, c, leaks={rows[0]["id"]: [leak]})
    assert any("rögzített részében" in e for e in errs)


def test_leak_strings_collect_article_and_truth_fields():
    inst = {"targetTitle": "T title long enough", "targetDescription": "D", "targetKeywords": "a,b", "targetParagraphs": ["P one is long enough", "P two"], "targetCaptions": ["C"]}
    tr = {"truthMean": 0.4666667, "truthMedian": 0.3333, "truthMode": 0.0, "truthJudgments": [0.0, 1.0]}
    s = gs.leak_strings_for(inst, tr)
    assert "T title long enough" in s and "P one is long enough" in s and "0.4666667" in s and "0.4667" in s and str([0.0, 1.0]) in s


def test_build_dryrun_reports_unbuildable_titles_instead_of_writing_them(cfg):
    rows, errors = gs.build_dryrun([{"id": "a", "postText": "Fine headline here"}, {"id": "b", "postText": "szőlő hírek"}, {"id": "c", "postText": ""}], cfg)
    assert [r["id"] for r in rows] == ["a"] and [e["id"] for e in errors] == ["b", "c"]


# ------------------------------------------------------------------ futtató hamis átvitellel

def test_all_ok_run(tmp_path, cfg):
    tr = Script()
    rep, out, clock = smoke(tmp_path, cfg, tr, reference={x["id"]: i / 20 for i, x in enumerate(INPUTS)})
    assert rep["n_valid"] == 20 and rep["requests_sent"] == 20 and rep["retries"] == 0 and rep["pass"] and rep["stop_reason"] is None
    assert rep["model_requested"] == MODEL and rep["model_versions_seen"] == [MODEL] and rep["tier"] == "free" and rep["cost_usd"] == 0.0 and rep["cost_if_paid_usd"] is None
    assert rep["tokens"] == {"promptTokenCount": 16000, "candidatesTokenCount": 3600, "thoughtsTokenCount": 0, "totalTokenCount": 19600}
    assert clock.sleeps == [13.0] * 19                                   # az első kérés előtt nincs várakozás, utána 13 s közök
    assert rep["latency_ms"] == {"min": 120, "median": 120, "max": 120} and re.fullmatch("[0-9a-f]{64}", rep["prompt_sha256"]) and re.fullmatch("[0-9a-f]{64}", rep["schema_sha256"])
    assert rep["descriptive_vs_truthMean"]["n"] == 20 and "kevés" not in rep["descriptive_vs_truthMean"]["note"]
    scores = jl(out / "scores.jsonl")
    assert [s["id"] for s in scores] == [x["id"] for x in INPUTS]
    for s, x in zip(scores, INPUTS):
        assert set(s) == {"id", "source", "signals", "total", "scaled"} and s["total"] == 3 and s["scaled"] == 3 / 8
        assert scoring.validate_score(s, x["postText"], cfg) == []
    raw = jl(out / "raw_responses.jsonl")
    assert len(raw) == 20 and set(raw[0]) == {"id", "attempt", "http_status", "latency_ms", "finishReason", "promptFeedback_blockReason", "usageMetadata", "text"}
    assert not (out / "errors.jsonl").exists()
    assert json.loads((out / "smoke_report.json").read_text(encoding="utf-8")) == json.loads(json.dumps(rep))


def test_only_the_post_text_goes_out_in_every_request(tmp_path, cfg):
    tr = Script()
    smoke(tmp_path, cfg, tr)
    assert len(tr.calls) == 20 and {m for m, _ in tr.calls} == {MODEL}
    for (_, body), x in zip(tr.calls, INPUTS):
        assert body == gr.build_body(x["postText"], cfg) and gr.check_request(body, x["postText"], cfg) == []
        assert x["id"] not in json.dumps(body)                           # az azonosító sem megy ki


def test_invalid_output_is_retried_once_then_recorded(tmp_path, cfg):
    bad = api(obj={**mj(TEXTS[0]), "total": 5})
    tr = Script([bad, bad])
    rep, out, _ = smoke(tmp_path, cfg, tr)
    assert rep["requests_sent"] == 21 and rep["retries"] == 1 and rep["n_valid"] == 19 and rep["n_failed"] == 1 and rep["errors_by_kind"] == {"invalid": 2} and rep["pass"]
    errs = jl(out / "errors.jsonl")
    assert [(e["id"], e["attempt"], e["kind"]) for e in errs] == [("id00", 1, "invalid"), ("id00", 2, "invalid")]
    assert "id00" not in {s["id"] for s in jl(out / "scores.jsonl")}      # az érvénytelen nem kerül a pontszámok közé és nincs „javítva”


def test_broken_json_then_valid_on_retry(tmp_path, cfg):
    tr = Script([api(text="{rossz json")])
    rep, out, _ = smoke(tmp_path, cfg, tr)
    assert rep["n_valid"] == 20 and rep["requests_sent"] == 21 and rep["retries"] == 1 and rep["n_failed"] == 0
    assert [s["id"] for s in jl(out / "scores.jsonl")][0] == "id00"


def test_timeout_is_retried_with_backoff(tmp_path, cfg):
    tr = Script([gs.TransportTimeout()])
    rep, out, clock = smoke(tmp_path, cfg, tr)
    assert rep["n_valid"] == 20 and rep["requests_sent"] == 21 and rep["retries"] == 1 and 2 in clock.sleeps
    assert jl(out / "raw_responses.jsonl")[0] == {"id": "id00", "attempt": 1, "http_status": None, "timeout": True}


def test_repeated_timeouts_give_up_after_max_retries(tmp_path, cfg):
    tr = Script([gs.TransportTimeout()] * 3)
    rep, out, clock = smoke(tmp_path, cfg, tr)
    assert rep["n_failed"] == 1 and rep["n_valid"] == 19 and rep["requests_sent"] == 22 and rep["retries"] == 2
    assert 2 in clock.sleeps and 8 in clock.sleeps and rep["errors_by_kind"] == {"transient": 3}


def test_server_errors_are_retried(tmp_path, cfg):
    rep, _, _ = smoke(tmp_path, cfg, Script([err(503), err(500)]))
    assert rep["n_valid"] == 20 and rep["requests_sent"] == 22 and rep["retries"] == 2


def test_minute_quota_waits_for_retry_delay(tmp_path, cfg):
    q = err(429, "slow", [{"violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]}, {"retryDelay": "21s"}])
    rep, _, clock = smoke(tmp_path, cfg, Script([q]))
    assert rep["n_valid"] == 20 and rep["requests_sent"] == 21 and 21.0 in clock.sleeps and rep["stop_reason"] is None


def test_daily_quota_stops_the_whole_run(tmp_path, cfg):
    q = err(429, "x", [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}])
    tr = Script([None] * 0)
    tr.items = [lambda t: api(mj(t))] * 3 + [q]
    rep, out, _ = smoke(tmp_path, cfg, tr)
    assert rep["stop_reason"] == "quota_day" and rep["n_valid"] == 3 and rep["requests_sent"] == 4 and len(tr.calls) == 4 and rep["n_not_attempted"] == 17 and not rep["pass"]
    assert jl(out / "errors.jsonl")[-1]["kind"] == "quota_day"


def test_safety_blocks_are_counted_separately_and_not_retried(tmp_path, cfg):
    pb = gs.Raw(200, json.dumps({"promptFeedback": {"blockReason": "SAFETY"}}), 1)
    tr = Script([api(text="", finish="SAFETY"), pb])
    rep, out, _ = smoke(tmp_path, cfg, tr)
    assert rep["n_blocked"] == 2 and rep["n_valid"] == 18 and rep["requests_sent"] == 20 and rep["retries"] == 0 and rep["pass"]
    assert {s["id"] for s in jl(out / "scores.jsonl")}.isdisjoint({"id00", "id01"})        # blokkolt cím nem kap 0 pontot


def test_truncated_output_is_not_retried(tmp_path, cfg):
    rep, _, _ = smoke(tmp_path, cfg, Script([api(text='{"curiosity_gap": {"span": "x"', finish="MAX_TOKENS")]))
    assert rep["n_failed"] == 1 and rep["requests_sent"] == 20 and rep["errors_by_kind"] == {"truncated": 1}


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_fatal_http_errors_stop_the_run(tmp_path, cfg, status):
    tr = Script([err(status, "config problem")])
    rep, _, _ = smoke(tmp_path, cfg, tr)
    assert rep["stop_reason"] == "fatal" and rep["requests_sent"] == 1 and len(tr.calls) == 1 and rep["n_valid"] == 0 and rep["n_not_attempted"] == 20 and not rep["pass"]


def test_request_cap_includes_retries(tmp_path, cfg):
    tr = Script(default=lambda body, text: api(obj={"curiosity_gap": {}}))            # mindig érvénytelen
    rep, _, _ = smoke(tmp_path, cfg, tr)
    assert rep["requests_sent"] == 25 == len(tr.calls) and rep["stop_reason"] == "request_cap" and rep["n_valid"] == 0 and not rep["pass"]


def test_run_is_resumable_and_never_resends_finished_titles(tmp_path, cfg):
    q = err(429, "x", [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}])
    first = Script()
    first.items = [lambda t: api(mj(t))] * 5 + [q]
    smoke(tmp_path, cfg, first)
    second = Script()
    rep, out, _ = smoke(tmp_path, cfg, second)
    assert len(second.calls) == 15 and rep["n_valid"] == 20 and rep["stop_reason"] is None
    ids = [s["id"] for s in jl(out / "scores.jsonl")]
    assert ids == [x["id"] for x in INPUTS] and len(set(ids)) == 20


def test_run_refuses_wrong_size_and_disallowed_models_before_any_call(tmp_path, cfg):
    tr = Script()
    with pytest.raises(ValueError, match="fix 20"):
        smoke(tmp_path, cfg, tr, inputs=INPUTS[:19])
    with pytest.raises(ValueError):
        smoke(tmp_path, cfg, tr, inputs=INPUTS + INPUTS[:1])                          # nincs „nagyobb” futás
    for model in ("gemini-3.6-flash", "gemini-3.8-flash", "gemini-2.5-pro", "gemini-3.5-flash"):
        with pytest.raises(gs.NeedUserDecision, match="Állj meg és kérdezz"):
            smoke(tmp_path, cfg, tr, model=model)
    assert tr.calls == []
    smoke(tmp_path / "ok", cfg, Script(), model="gemini-3.5-flash-lite-preview-1")   # a jelölt utótagos neve is megengedett


def test_cost_is_zero_on_free_tier_and_computed_when_paid(tmp_path, cfg):
    c = copy.deepcopy(cfg)
    c["gemini"]["prices_usd_per_million"].update(input=0.5, output=3.0)
    rep, _, _ = smoke(tmp_path, c, Script())
    assert rep["cost_usd"] == 0.0 and rep["cost_if_paid_usd"] == pytest.approx((16000 * 0.5 + 3600 * 3.0) / 1e6)
    c["gemini"]["tier"] = "paid"
    rep2, _, _ = smoke(tmp_path / "b", c, Script(default=lambda b, t: api(mj(t), usage=(800, 180, 1000))))
    assert rep2["cost_usd"] == pytest.approx((16000 * 0.5 + (3600 + 20000) * 3.0) / 1e6) and rep2["tokens"]["thoughtsTokenCount"] == 20000


def test_pass_needs_eighteen_valid_and_no_stop(tmp_path, cfg):
    bad = api(text="{")
    rep, _, _ = smoke(tmp_path, cfg, Script([bad, bad, bad, bad, bad, bad]))         # három cím veszik el (mindegyik kétszer érvénytelen)
    assert rep["n_valid"] == 17 and rep["n_failed"] == 3 and not rep["pass"]


def test_runner_writes_only_into_the_results_dir(tmp_path, cfg):
    _, out, _ = smoke(tmp_path, cfg, Script())
    assert {p.name for p in tmp_path.iterdir()} == {"results"} and out.parent == tmp_path / "results"
    with pytest.raises(Exception, match="eredménytárba"):
        gs.run_smoke(INPUTS, Script(), cfg, tmp_path / "kivul", tmp_path / "results", MODEL)


# ------------------------------------------------------------------ nincs hálózati kód

def test_no_network_code_exists_in_the_gemini_modules():
    for name in ("gemini_request.py", "gemini_smoke.py"):
        src = (MODULE_DIR / name).read_text(encoding="utf-8")
        for bad in ("urlopen", "import socket", "http.client", "import requests", "import urllib", "import httpx", "aiohttp", "subprocess", "os.environ", "getenv"):
            assert bad not in src, (name, bad)


def test_no_real_transport_is_exposed_by_the_cli():
    src = (MODULE_DIR / "run.py").read_text(encoding="utf-8")
    assert "gemini-dryrun" in src and "run_smoke" not in src                          # a CLI csak a száraz próbát indítja


# ------------------------------------------------------------------ a postText változatlanul megy ki

@pytest.mark.parametrize("text", [
    "RT @CNNPolitics: The U.S. sees #ISIS wives playing a key role in their operations, @barbarastarrcnn reports http://t",      # RT @fiók: előtag, @említés, csonka link
    "RT @BBCNewsMagazine: John Lennon was paid in chocolate biscuits for a BBC show in 1975 #thingId",
    "Watch this now http://t",
    "  leading and trailing spaces stay  ",
    "Double  spaces   and\ttabs stay",
    "Line one\nline two stays",
])
def test_post_text_goes_out_unchanged(cfg, text):
    b = gr.build_body(text, cfg)
    assert b["contents"][0]["parts"][0]["text"] == "<post>\n" + text + "\n</post>"        # nincs tisztítás, vágás, előtag-eltávolítás
    assert gr.check_request(b, text, cfg) == []


def test_source_name_is_never_a_separate_field_but_may_be_inside_the_post_text(cfg):
    text = "RT @CNNPolitics: Senate votes on the new bill today"
    b = gr.build_body(text, cfg)
    assert "CNNPolitics" in b["contents"][0]["parts"][0]["text"]                         # a poszt szövegében szerepelhet
    fixed = json.dumps(b, ensure_ascii=False).replace(json.dumps("<post>\n" + text + "\n</post>", ensure_ascii=False)[1:-1], "")
    assert "CNNPolitics" not in fixed                                                    # külön mezőben, a rögzített részben nem
    b["generationConfig"]["publisher"] = "CNN"
    assert any("generationConfig" in e for e in gr.check_request(b, text, cfg))
    for key in ("source", "source_domain", "publisher"):
        b2 = gr.build_body(text, cfg)
        b2[key] = "CNN"
        assert gr.check_request(b2, text, cfg), key


def test_no_safety_settings_are_ever_added_and_blocks_are_not_retried(tmp_path, cfg):
    assert "safetySettings" not in gr.build_body("Some headline here", cfg) and "safetySettings" not in gr.build_body("Some headline here", cfg)["generationConfig"]
    b = gr.build_body("Some headline here", cfg)
    b["safetySettings"] = [{"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"}]
    assert any("felső szintű kulcs" in e for e in gr.check_request(b, "Some headline here", cfg))        # a lazítás a kimenő kérés ellenőrzésén elbukik
    tr = Script([api(text="", finish="SAFETY")])
    rep, out, _ = smoke(tmp_path, cfg, tr)
    assert rep["n_blocked"] == 1 and rep["retries"] == 0 and rep["requests_sent"] == 20 and rep["errors_by_kind"] == {"blocked": 1}
    assert [e["kind"] for e in jl(out / "errors.jsonl")] == ["blocked"]


def test_unchanged_post_text_reaches_the_transport_in_the_run(tmp_path, cfg):
    texts = ["RT @CNNPolitics: Headline one here http://t"] + TEXTS[1:]
    inputs = [{"id": f"id{i:02d}", "postText": t} for i, t in enumerate(texts)]
    tr = Script()
    smoke(tmp_path, cfg, tr, inputs=inputs)
    assert tr.calls[0][1]["contents"][0]["parts"][0]["text"] == "<post>\nRT @CNNPolitics: Headline one here http://t\n</post>"
