"""Nyelvi modell NÉLKÜLI, extraktív alapút: a kérdés kulcsszavaihoz leginkább illő átirat-szegmenseket választja ki, SZÓ SZERINT.

Ez nem fordít és nem foglal össze: a `statement_hu` magyar átirat esetén a szegmens szövege; más nyelvű átiratnál az eredeti nyelvű szöveg,
`[eredeti nyelv: xx]` jelöléssel és korláttal (magyar fordítás modell nélkül nincs). A kimenet ugyanazon a programozott idézet-ellenőrzésen megy át,
mint egy modellé. A kategória kulcsszavas heurisztika (tool/product/method nem ismerhető fel megbízhatóan, ezért nincs ilyen).
Az `LLMClient` felületet valósítja meg, hogy a pipeline változtatás nélkül használhassa; a `plan` és `semantic` hívásokat elutasítja."""
from __future__ import annotations

import re

from .extraction import OPEN, CLOSE, _norm
from .llm import LLMResult, LLMUnavailable

_SEG = re.compile(r"^\[(?P<id>[^\]]+)\] (?P<text>.+)$", re.M)
_Q = re.compile(r"Kutatási kérdés: (.*)")
_LANG = re.compile(r"Átirat nyelve: (\S+)")
_WARN = ("probléma", "hiba", "gond", "elakad", "nem működik", "korlát", "veszély", "kockázat", "problem", "issue", "bug", "drain", "fail", "risk", "limit")
_REC = ("ajánl", "érdemes", "használd", "javaslom", "recommend", "should", "you need to")
_STOP = {"keress", "gyűjtsd", "kérdés", "kutatás", "videó", "videók", "youtube", "tiktok", "említett", "mutass", "melyek", "milyen", "hogyan"}
TOP_N = 8


def _keywords(question: str) -> list[str]:
    return [w[:6] for w in _norm(question).split() if len(w) > 3 and w not in _STOP]


class ExtractiveBaselineLLM:
    name = "extractive-baseline"

    def complete_json(self, *, system: str, user: str, schema_name: str, max_tokens: int) -> LLMResult:
        if schema_name != "findings":
            raise LLMUnavailable("az extraktív alapút csak kinyerést végez (nincs terv- és szemantikai ellenőrző modell)")
        qm = _Q.search(user)
        kws = _keywords(qm.group(1) if qm else "")
        lang = (_LANG.search(user).group(1) if _LANG.search(user) else "hu")
        body = user.split(OPEN, 1)[1].rsplit(CLOSE, 1)[0] if OPEN in user else ""
        scored = []
        for m in _SEG.finditer(body):
            t, n = m.group("text"), _norm(m.group("text"))
            score = sum(1 for k in kws if k in n)
            if score and len(n) >= 12:
                scored.append((score, m.group("id"), t, n))
        scored.sort(key=lambda x: (-x[0], x[1]))
        findings = []
        for score, sid, t, n in scored[:TOP_N]:
            cat = "warning" if any(w in n for w in _WARN) else "recommendation" if any(w in n for w in _REC) else "claim"
            lims = ["Extraktív kivonat modell nélkül: a szegmens szó szerinti szövege, nem összefoglalás; a kérdéssel való relevanciát kulcsszó-egyezés adja."]
            stmt = t if lang.startswith("hu") else f"[eredeti nyelv: {lang}] {t}"
            if not lang.startswith("hu"):
                lims.append("Magyar fordítás nincs: az állítás az eredeti nyelvű átirati szöveg.")
            findings.append({"category": cat, "statement_hu": stmt, "quotes": [{"segment_id": sid, "quote": t}], "limitations": lims})
        return LLMResult({"findings": findings}, 0)
