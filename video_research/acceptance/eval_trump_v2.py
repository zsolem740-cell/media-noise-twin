"""A trump-v2 esetkészlet kiértékelője. A v1 kiértékelőt (eval_trump_v1) NEM módosítja: arra épül, és három dolgot cserél vagy ad hozzá:

  1. Valódi időbélyegek: a forrás SRT-je valódi másodpercekkel jön; minden hivatkozás időbélyegének az idézetet tartalmazó első szegmens kezdetével kell egyeznie (kemény kapu).
     (A v1 'egyszerű szövegnél null' szabálya itt nem érvényes, ezért a v1 erre vonatkozó üzeneteit kiszűrjük.)
  2. Szigorú L1 (K3a+K4): az E2/E3 helyén UGYANAZON a lead-en kell lennie (a) a modelltől származó, nem üres needs_check-nek (megnevezett hiányzó ellenőrzés) ÉS (b) a modelltől származó
     ellenőrzési kérdésnek. Önmagában nem elég: a "But…" miatti automatikus minősítő-nyom, a fordítás-hiány miatti automatikus nyom, a részleges relevancia, az általános "ellenőrizendő nyom" indok,
     és az, ha csak az ok vagy csak a kérdés a modellé. A kérdés tartalmi megfelelése (forrás/módszer) továbbra is emberi megítélés.
  3. Segédjelzés számok átvitelére: az állítás számjegyes számai (pl. 2025) szerepelnek-e az idézetben; ha nem, jelzés (aux, nem kemény kapu). KIVÉTEL a tartalmi minősítésben: a 2025 átvitele az E3-ra TARTALMI HIBA GYANÚ
     (`content_flags`), amely a `hard_ok` értékétől függetlenül emberi elbírálást kér; a modul nem mondja ki a tartalmi ítéletet.

Két réteg (mint a v1-ben): `hard` programozottan eldönthető kapuk; `aux` szinonimalistás/heurisztikus segédjelzések; a TARTALMI megítélés (jelentés, hatókör, feltétel) emberi.
A modul sosem mond ki "megfelelt" tartalmi ítéletet.
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

from ..adapters.base import AdapterRegistry
from ..config import Settings
from ..db import Store, make_engine, migrate
from ..extraction import _norm
from ..importer import import_job
from ..models import JobStatus, Limits, ResearchReport
from ..pipeline import Pipeline
from ..worker import Worker
from .eval_trump_v1 import _has, evaluate_trump, hard_ok, render_review  # noqa: F401  (hard_ok, render_review újra exportálva)

# A pipeline (extraction._validate_items) jelenleg ÖT helyen képez nyom-okot: a modell needs_check szövege (ez a megnevezett hiányzó ellenőrzés) és négy RÖGZÍTETT szöveg. Ez a modul
# tiltólistás EREDETBECSLÉSSEL dolgozik: aminek az eleje (szóköz nélkül) a négy rögzített szöveg valamelyike, az nem megnevezett ellenőrzés; ami más, azt a modell needs_check-jének vesszük.
# MEGVALÓSÍTÁSI KORLÁT: ez NEM kimerítő eredetbizonyítás (a pipeline nem ad szerkezeti eredetjelzőt). A tesztekben lévő szöveg- és számosság-ellenőrzés (4 szöveg, 5 képzési hely)
# dokumentált REGRESSZIÓS VÉDŐHÁLÓ: a változást jelzi, azt nem bizonyítja, hogy minden jövőbeli ok-típust helyesen osztályozunk.
AUTO_QUALIFIER_REASON = "a következő mondat feltételt vagy cáfolatot tartalmazhat"        # automatikus: a következő "But…" mondat
AUTO_UNTRANSLATED_REASON = "nincs magyar fordítás"                                         # automatikus: az állítás megegyezik az idegen nyelvű idézettel
AUTO_PARTIAL_REASON = "csak részben releváns a kérdéshez"                                  # a modell relevancia-ítélete, NEM megnevezett ellenőrzés
AUTO_GENERIC_LEAD_REASON = "a modell ellenőrizendő nyomként jelölte"                       # általános jelölés, NEM megnevezett ellenőrzés
NOT_A_NAMED_CHECK_REASONS = (AUTO_QUALIFIER_REASON, AUTO_UNTRANSLATED_REASON, AUTO_PARTIAL_REASON, AUTO_GENERIC_LEAD_REASON)
PIPELINE_REASON_SITES = 5                                                                  # reasons.append(...) helyek száma az extraction._validate_items-ben (4 rögzített + needs_check)
# Automatikus kérdések (a modell nem adott kérdést):
AUTO_QUALIFIER_VQ = "Módosítja-e vagy cáfolja-e az állítást a következő mondat"
AUTO_UNTRANSLATED_VQ = "Mi a magyar tartalma ennek az idézetnek"
AUTO_VQS = (AUTO_QUALIFIER_VQ, AUTO_UNTRANSLATED_VQ)
# Szűkített, forrásirányú jelzőszavak az L1 kérdéséhez (a v1 listájából kivéve: "becslés", "számít": túl általánosak, tévesen forrásirányúnak vettek évszám- vagy számkérdéseket).
ORIGIN_MARKERS = ("forrás", "honnan", "ki számol", "módszer", "alapul")
V1_NULL_TS_MSG = "egyszerű szövegnél null az elvárt"
_NUM = re.compile(r"\d[\d.,]*\d|\d")


def run_case_v2(case: dict, llm, tmp: Path | None = None) -> dict:
    """A runner.run_case mása, de a VALÓDI időbélyeges SRT-t adja át (a runner szintetikus 6 s-os rácsot generálna)."""
    tmp = tmp or Path(tempfile.mkdtemp())
    engine = make_engine(f"sqlite:///{tmp / (case['id'] + '.db')}")
    migrate(engine)
    store, settings = Store(engine), Settings(limits=Limits())
    pipe = Pipeline(store, settings, AdapterRegistry(production=False), llm, sleep=lambda _x: None, poll_interval=0, semantic=getattr(llm, "kind", "") == "ai")
    jid, _ = import_job(store, settings, question=case["question"], transcript_text=case["srt"], fmt=case["fmt"], language=case["lang"], title="Teszt átirat", video_url=None,
                        known_information=case.get("known"))
    w = Worker(store, pipe, settings, name="acc")
    w.run_once()
    store.set_status(jid, JobStatus.queued, approved_plan=store.get_field(jid, "plan"))
    w.run_once()
    return {"job": store.get_job(jid), "report": ResearchReport.model_validate_json(store.get_field(jid, "report")), "llm": llm, "store": store, "jid": jid}


def _numbers(text: str) -> set[str]:
    return {re.sub(r"[.,]", "", m) for m in _NUM.findall(text)}


def unsupported_numbers(statement: str, refs) -> list[str]:
    """Az állítás számjegyes számai, amelyek a találat hivatkozásainak idézeteiben nincsenek. Vizsgált idézetek: a találat MINDEN hivatkozása, vagyis a fő (support) ÉS a minősítő (qualifier)
    hivatkozások is; az összehasonlítás az idézetek számjegyes számainak UNIÓJA ellen megy. (Következmény: ha egy szám csak a minősítő-hivatkozás idézetében szerepel, nem jelzi.)"""
    quote_nums = set().union(*[_numbers(r.supporting_quote) for r in refs]) if refs else set()
    return sorted(_numbers(statement) - quote_nums)


def is_model_named_check_with_question(f) -> bool:
    """Az L1 szerkezeti kapuja EGY lead-re: van modelltől származó, NEM ÜRES megnevezett ellenőrzés (ok) ÉS modelltől származó, NEM ÜRES kérdés. Mindkettőt .strip() után vizsgálja,
    tehát az üres és a csak szóközös ok/kérdés nem számít modelltől származónak. (A pipeline is levágja a szóközt a needs_check-en és a kérdésen, és üres needs_check-et nem vesz fel okként;
    a kiértékelő ezt függetlenül is megköveteli.)"""
    q = (getattr(f, "verification_question", None) or "").strip()
    if not q or q.startswith(AUTO_VQS):
        return False
    for r in (getattr(f, "lead_reasons", None) or []):
        r = (r or "").strip()
        if r and not r.startswith(NOT_A_NAMED_CHECK_REASONS):
            return True
    return False


def expected_start(case: dict, quote: str):
    """Az idézetet tartalmazó legkisebb szegmensablak első szegmensének kezdete (a pipeline locate_quote logikája szerint)."""
    norms = [_norm(t) for t in case["segments"]]
    q = _norm(quote)
    for width in range(1, 7):
        for i in range(0, len(norms) - width + 1):
            if q in " ".join(norms[i:i + width]):
                return case["starts_s"][i]
    return None


def evaluate_trump_v2(case: dict, res: dict) -> dict:
    base = evaluate_trump(case, res)
    hard = {k: list(v) for k, v in base["hard"].items()}
    hard["timestamp_bad"] = []
    aux = [a for a in base["aux"] if not a.startswith("L1:")]
    hard["source_link_bad"] = [m for m in hard["source_link_bad"] if V1_NULL_TS_MSG not in m]
    hard["missed"] = [m for m in hard["missed"] if not m.startswith("L1")]
    findings = list(res["report"].findings)
    lang, lead = case["lang"], case["lead"]
    expected = case["expected"]

    def sup(f):
        return " ".join(_norm(r.supporting_quote) for r in f.source_references if r.role == "support")

    def hit(e, f):
        return all(_norm(a) in sup(f) for a in e["anchors"][lang])

    anchor_items = [x for x in expected if x["id"] in lead["anchors_any"]]
    leads = [f for f in findings if f.disposition.value == "lead" and any(hit(x, f) for x in anchor_items) and (f.verification_question or "").strip()]
    # L1 (K3a+K4): UGYANAZON a lead-en kell lennie a modelltől származó, nem üres needs_check-nek (megnevezett ellenőrzés) ÉS a modelltől származó kérdésnek.
    model_leads = [f for f in leads if is_model_named_check_with_question(f)]
    if not model_leads:
        hard["missed"].append(f"{lead['id']} ({lead['what_hu']}): nincs olyan lead az E2/E3 helyén, amelyen a modelltől származó, nem üres needs_check ÉS a modelltől származó kérdés együtt van")
        if leads:
            aux.append(f"L1: van lead az E2/E3 helyén ({', '.join(f.id for f in leads)}), de nincs rajta modelltől származó needs_check és kérdés együtt "
                       "(automatikus kiegészítés, részleges relevancia, általános nyomjelölés, vagy csak az ok / csak a kérdés a modellé): ez nem teljesíti az L1-et")
    elif not any(_has(f.verification_question, ORIGIN_MARKERS) for f in model_leads):
        aux.append("L1: az ellenőrzési kérdés nem utal a becslés forrására/módszerére (szinonimalista, nem ítélet; emberi megítélés kell)")

    content_flags: list[str] = []
    eid_of = {fid: eid for eid, fid in base["assignment"].items()}
    for f in findings:
        for ref in f.source_references:
            want = expected_start(case, ref.supporting_quote)
            if want is None:
                continue                                    # az idézet hiányát a v1 kapu már jelzi
            if ref.timestamp is None or abs(ref.timestamp - want) > 0.0015:
                hard["timestamp_bad"].append(f"{f.id}: időbélyeg {ref.timestamp} (elvárt: {want}) az idézetnél: „{ref.supporting_quote[:40]}”")
        extra = unsupported_numbers(f.statement_hu, f.source_references)
        tag = eid_of.get(f.id, f.id)
        if tag == "E3" and "2025" in extra:
            msg = (f"E3: TARTALMI HIBA GYANÚ: a 2025 az E3 idézetében nincs (jogosulatlan átvitel az E2-ről); a hard_ok ettől függetlenül igaz lehet, emberi elbírálás kell: „{f.statement_hu[:60]}”")
            aux.append(msg)
            content_flags.append(msg)
        elif extra:
            aux.append(f"{tag}: az állítás számai {extra} az idézetekben nincsenek (más mondatból átvitt szám/évszám? ellenőrizd): „{f.statement_hu[:60]}”")

    rows = []
    for row in base["review_rows"]:
        if row["id"] == lead["id"]:
            f = model_leads[0] if model_leads else None
            row = dict(row, found=f is not None, bucket=f.report_bucket if f else None, statement_hu=f.statement_hu if f else None,
                       quotes=[r.supporting_quote for r in f.source_references if r.role == "support"] if f else [],
                       verification_question=f.verification_question if f else None)
        row = dict(row, flags=[a for a in aux if a.startswith(row["id"] + ":")])
        rows.append(row)
    judgement = "függőben (emberi megítélés)" + ("; TARTALMI HIBA GYANÚ: lásd content_flags, a hard_ok ettől független" if content_flags else "")
    return {"hard": hard, "aux": aux, "assignment": base["assignment"], "review_rows": rows, "content_flags": content_flags, "human_content_judgement": judgement}
