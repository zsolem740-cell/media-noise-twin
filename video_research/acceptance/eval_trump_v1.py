"""A trump-v1 esetkészlet kiértékelője (a `runner.py` kiértékelőjétől KÜLÖN, azt nem módosítja).

Két réteg, szándékosan szétválasztva:
  1. `hard`: programozottan eldönthető kapuk (megvan-e az elvárt tétel az alátámasztó idézet kifejezéseivel; az idézet és a forráskapcsolat valódi-e; nincs „ellenőrzött" jelzés;
     az E2 és E3 nincs egy állításba vonva; az E1 nincs minden országra általánosítva; zaj nem önálló találat; a megszakadt mondat nincs ténnyé kiegészítve; a nyom kérdéssel jár).
  2. `aux`: SZINONIMALISTÁS segédjelzések (hiányzik-e a feltételre, hatókörre, időpontra, állítás-jellegre utaló szó). Ezek NEM ítéletek, csak figyelmeztetések az emberi értékelőnek:
     a lista nem teljes, egy szinonima hiánya nem hiba, megléte nem bizonyítja a jelentés helyességét.
A TARTALMI megfelelést (jelentés, hatókör, feltétel) az ember dönti el a `review_rows` / `render_review` alapján. Ez a modul sosem mond ki „megfelelt" tartalmi ítéletet.
A modell saját kivonata nem az egyetlen alap: az elvárás a lefagyasztott kézi szövegből jön (`cases_trump_v1.py`), nem a modell kimenetéből.
"""
from __future__ import annotations

from ..extraction import _norm

STRICT_SEPARATE = ("E2", "E3")                 # a lefagyasztott elvárás szerint külön marad
M1200 = ("1200", "1 200", "1.200", "1,200", "ezerkétszáz", "ezer kétszáz")
M4000 = ("4000", "4 000", "4.000", "4,000", "négyezer")
MARK = dict(
    plan=("terv", "szándék"), china=("kín",), y2025=("2025",), typical=("átlagos", "tipikus"),
    cond=("kerülnének", "kerülne", "kerülhet", "feltétel", "ha ", "esetén", "várhatóan", "becslés", "lehet", "elvileg"),
    upper=("legfeljebb", "akár", "maximum", "legalább"), e3cond=("ha ", "ígéret", "betart", "esetén", "amennyiben"),
    attrib=("szerint", "állítja", "beszélő", "mondja", "szerző", "úgy véli", "véleménye", "szerinte"),
    intent=("javasol", "jelezte", "szándék", "tervez", "javaslat", "jelzi"),
    enacted=("kivetette", "kivetett", "bevezette", "bevezetett", "életbe lépett", "életbe lépő", "hatályba"),
    complete=("segít", "elősegít", "megkönnyít", "lehetővé"), hedge=("hiányos", "megszakad", "nem teljes", "csonka", "talán"),
    wealth=("vagyonátadás", "szupergazd", "wealth"),
    origin=("forrás", "honnan", "ki számol", "módszer", "számít", "becslés", "alapul"),
)


def _has(text: str, words) -> bool:
    t = text.casefold()
    return any(w in t for w in words)


def _support_text(f) -> str:
    return " ".join(_norm(r.supporting_quote) for r in f.source_references if r.role == "support")


def evaluate_trump(case: dict, res: dict) -> dict:
    lang, r = case["lang"], res["report"]
    expected = case["expected"]
    findings = list(r.findings)
    sup = {f.id: _support_text(f) for f in findings}

    def hit(e, f) -> bool:
        return all(_norm(a) in sup[f.id] for a in e["anchors"][lang])

    assign, used, shared = {}, set(), {}
    for e in expected:
        cands = [f for f in findings if f.id not in used and hit(e, f)]
        cands.sort(key=lambda f: sum(hit(x, f) for x in expected))        # a legkevesebb elvárást fedő tétel előnyben: ne a többszörös idézetű vigye el
        if cands:
            assign[e["id"]] = cands[0]
            used.add(cands[0].id)
        else:
            sh = next((f for f in findings if hit(e, f)), None)
            if sh is not None:
                shared[e["id"]] = sh

    hard: dict[str, list[str]] = {k: [] for k in ("missed", "wrongly_included", "source_link_bad", "verification", "merged_estimates", "scope_generalized",
                                                  "broken_sentence_completed", "leads_have_question", "status", "no_result")}
    aux: list[str] = []
    for e in expected:
        if e["id"] in assign:
            continue
        if e["id"] in shared and e["id"] not in STRICT_SEPARATE:
            aux.append(f"{e['id']}: külön tétel nincs; ugyanazt az idézetet egy másik tétel (azonos találat) fedi: emberi megítélés kell, hogy az állítás mindkettőt hordozza-e")
        else:
            hard["missed"].append(f"{e['id']} ({e['what_hu']})" + (" — csak egy, az E2-t és E3-at együtt idéző tétel fedi" if e["id"] in shared else ""))

    lead = case["lead"]
    anchor_items = [x for x in expected if x["id"] in lead["anchors_any"]]
    l1 = [f for f in findings if f.disposition.value == "lead" and any(hit(x, f) for x in anchor_items) and (f.verification_question or "").strip()]
    if not l1:
        hard["missed"].append(f"{lead['id']} ({lead['what_hu']}): nincs LEAD besorolású, ellenőrzési kérdéssel ellátott tétel az E2/E3 helyén")
    else:
        if not any(_has(f.verification_question, MARK["origin"]) for f in l1):
            aux.append("L1: az ellenőrzési kérdés nem utal a becslés forrására/módszerére (szinonimalista: nem ítélet; emberi megítélés kell)")

    assigned_ids = {f.id for f in assign.values()}
    noise = case["noise"]
    for f in findings:
        if f.id in assigned_ids:
            continue
        if any(hit(x, f) for x in anchor_items):
            aux.append(f"{f.id}: ismétlődő/további tétel az E2/E3 helyén ({f.report_bucket}): „{f.statement_hu[:70]}”")
            continue
        tag = "zaj önálló találatként" if any(_norm(n) in sup[f.id] for n in noise) else "nem elvárt tétel"
        hard["wrongly_included"].append(f"{tag} ({f.report_bucket}/{f.category.value}): „{f.statement_hu[:70]}”")

    full = _norm(" ".join(case["segments"]))
    video_id = r.source_list[0]["video_source_id"] if r.source_list else None
    for f in findings:
        for ref in f.source_references:
            if _norm(ref.supporting_quote) not in full:
                hard["source_link_bad"].append(f"{f.id}: az idézet nincs az átiratban")
            if ref.timestamp is not None:
                hard["source_link_bad"].append(f"{f.id}: időbélyeg {ref.timestamp} (egyszerű szövegnél null az elvárt)")
            if ref.video_source_id != video_id:
                hard["source_link_bad"].append(f"{f.id}: rossz videó-azonosító")
        if f.verification_status != "not_externally_verified" or f.evidence_status.value not in ("source_claim", "repeated_across_sources"):
            hard["verification"].append(f"{f.id}: verification_status={f.verification_status}, evidence_status={f.evidence_status.value}")
        st = f.statement_hu
        if _has(st, M1200) and _has(st, M4000):
            hard["merged_estimates"].append(f"{f.id}: az állítás az 1200 és a 4000 dolláros becslést is tartalmazza: „{st[:80]}”")
        if f.disposition.value == "lead" and not (f.verification_question or "").strip():
            hard["leads_have_question"].append(f.id)
        if lang == "hu" and ("segíthetnének" in sup[f.id] or "facilitate" in sup[f.id]) and _has(st, MARK["complete"]) and not _has(st, MARK["hedge"]):
            hard["broken_sentence_completed"].append(f"{f.id}: a megszakadt mondat (nincs fő ige) kiegészítve, hiányosság jelzése nélkül: „{st[:80]}”")
        if _has(st, MARK["wealth"]) and not _has(st, MARK["attrib"]):
            aux.append(f"{f.id}: a vagyonátadás/szupergazdag megfogalmazás beszélői megítélés jelölése nélkül szerepel (ténynek olvasható?)")
    if "E1" in assign:
        st = assign["E1"].statement_hu
        if not _has(st, ("kanad",)) and not _has(st, ("mexik",)):
            hard["scope_generalized"].append(f"E1: az állítás nem nevezi meg Kanadát és Mexikót (általánosítás minden országra?): „{st[:80]}”")
    if res["job"].status.value != "completed":
        hard["status"].append(f"státusz {res['job'].status.value} (elvárt: completed)")
    if r.no_result_note:
        hard["no_result"].append("no_result_note be van állítva, de találatot várunk")

    # --- szinonimalistás segédjelzések az elvárt tételekre (NEM ítéletek) ---
    def flag(eid, cond, msg):
        if eid in assign and cond(assign[eid].statement_hu):
            aux.append(f"{eid}: {msg}")
    flag("E1", lambda s: not _has(s, MARK["plan"]), "nincs jelölve, hogy terv, nem életbe lépett (ellenőrizd)")
    flag("E1", lambda s: _has(s, MARK["enacted"]) and not _has(s, MARK["plan"]), "életbe lépettként olvasható")
    flag("E1", lambda s: not _has(s, MARK["china"]), "a Kínára vonatkozó további emelés nem szerepel az állításban")
    flag("E2", lambda s: not _has(s, MARK["y2025"]), "a 2025-ös időpont nem szerepel")
    flag("E2", lambda s: not _has(s, MARK["typical"]), "a tipikus/átlagos háztartás nem szerepel")
    flag("E2", lambda s: not _has(s, MARK["cond"]), "nincs jelölve a feltételesség")
    flag("E3", lambda s: not _has(s, MARK["upper"]), "a felső határ (akár/legfeljebb) nem szerepel: pontos becslésnek olvasható?")
    flag("E3", lambda s: not _has(s, MARK["e3cond"]), "a feltétel (korábbi ígéretek beváltása / minden országra vám) nem szerepel")
    flag("E4", lambda s: not _has(s, MARK["attrib"]), "nincs jelölve, hogy a beszélő állítása")
    flag("E5", lambda s: not _has(s, MARK["intent"]), "a szándék/javaslat jellege nem szerepel (döntésnek olvasható?)")
    if all(k in assign for k in STRICT_SEPARATE) and assign["E2"].id == assign["E3"].id:
        hard["merged_estimates"].append("E2 és E3 ugyanaz a tétel")

    rows = []
    for e in expected + [dict(id=lead["id"], what_hu=lead["what_hu"], condition_hu=lead["condition_hu"])]:
        f = l1[0] if e["id"] == lead["id"] and l1 else assign.get(e["id"])
        rows.append(dict(id=e["id"], what_hu=e["what_hu"], condition_hu=e["condition_hu"], found=f is not None,
                         bucket=f.report_bucket if f else None, statement_hu=f.statement_hu if f else None,
                         quotes=[r_.supporting_quote for r_ in f.source_references if r_.role == "support"] if f else [],
                         verification_question=f.verification_question if f else None,
                         flags=[a for a in aux if a.startswith(e["id"] + ":")]))
    return {"hard": hard, "aux": aux, "assignment": {k: v.id for k, v in assign.items()}, "review_rows": rows, "human_content_judgement": "függőben (emberi megítélés)"}


def hard_ok(ev: dict) -> bool:
    return not any(ev["hard"].values())


def render_review(case: dict, res: dict, ev: dict) -> str:
    r, job = res["report"], res["job"]
    lines = [f"### {case['id']} — {case['title']}", "", f"**Kérdés:** {case['question']}", f"**Állapot:** {job.status.value}, elemzés: {r.analysis_method}", "",
             "**Elvárt tételek (lefagyasztott kézi elvárás) és a kimenet** — a tartalmi megfelelést (jelentés, hatókör, feltétel) az ember dönti el:", ""]
    for row in ev["review_rows"]:
        lines.append(f"- **{row['id']}** {row['what_hu']}")
        lines.append(f"    megőrzendő: {row['condition_hu']}")
        if not row["found"]:
            lines.append("    kimenet: NINCS megfelelő tétel")
            continue
        lines.append(f"    kimenet [{row['bucket']}]: {row['statement_hu']}")
        for q in row["quotes"]:
            lines.append(f"    idézet: „{q}”")
        if row["verification_question"]:
            lines.append(f"    ellenőrzési kérdés: {row['verification_question']}")
        for fl in row["flags"]:
            lines.append(f"    ⚠ segédjelzés (szinonimalista, nem ítélet): {fl}")
    others = [a for a in ev["aux"] if not any(a.startswith(x["id"] + ":") for x in ev["review_rows"])]
    if others:
        lines += ["", "Egyéb segédjelzések: " + "; ".join(others)]
    if r.filter_log:
        lines += ["", "Szűrési napló: " + "; ".join(f"[{e.reason_code.value}] „{e.snippet[:50]}”" for e in r.filter_log)]
    bad = {k: v for k, v in ev["hard"].items() if v}
    lines += ["", "**Automatikus kapuk:** " + ("mind teljesült" if not bad else "ELTÉRÉS: " + "; ".join(f"{k}: {v}" for k, v in bad.items())),
             "**Tartalmi megítélés:** " + ev["human_content_judgement"], ""]
    return "\n".join(lines)


def pair_summary(evs: dict[str, dict]) -> str:
    """Az A és a B eset különbsége a lefagyasztott három ponton (E1 hatókör, E3 felső határ, megszakadt mondat): a jelzések egymás mellett, az ítélet az emberé."""
    out = ["### A–B összevetés (jelzések; az ítélet emberi)"]
    for key, title in (("E1", "E1 hatókör és terv-jelleg"), ("E3", "E3 felső határ és feltétel")):
        for cid, ev in evs.items():
            fl = [a for a in ev["aux"] if a.startswith(key + ":")] + [h for k in ("scope_generalized", "merged_estimates") for h in ev["hard"][k] if h.startswith(key)]
            out.append(f"- {title} — {cid}: " + ("; ".join(fl) if fl else "nincs jelzés"))
    for cid, ev in evs.items():
        h = ev["hard"]["broken_sentence_completed"]
        out.append(f"- megszakadt mondat — {cid}: " + ("; ".join(h) if h else "nincs jelzés"))
    return "\n".join(out) + "\n"
