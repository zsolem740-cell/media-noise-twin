"""Kérésépítés és válasz-besorolás szolgáltatónként (Gemini, Groq), HÁLÓZAT NÉLKÜL. Egy cím egy kérésben, közös prompt és séma.
A nyers szöveg csak a postText; az összeget és a skálázott értéket a kód számolja, nem a modell."""
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field

from . import prompt as P

CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
SECRET = re.compile(r"(AIza[0-9A-Za-z_\-]{10,}|gsk_[0-9A-Za-z]{10,}|Bearer\s+\S+|x-goog-api-key\s*[:=]?\s*\S*|[?&]key=\S+|api[_\-]?key\s*[:=]?\s*\S*)", re.I)
BLOCK_FINISH = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION", "IMAGE_SAFETY"}
BILLING = re.compile(r"billing|payment|upgrade|paid tier|insufficient funds", re.I)


class RequestError(Exception):
    pass


@dataclass
class Outcome:
    kind: str                   # ok, empty, invalid, truncated, blocked, quota_day, quota_minute, transient, billing, fatal
    detail: str = ""
    retry_after: float | None = None
    score: dict | None = None
    usage: dict = field(default_factory=dict)
    finish_reason: str | None = None
    model_returned: str | None = None


def sanitize(text, limit=300):
    return SECRET.sub("[REDACTED]", str(text))[:limit]


def sha256_text(t):
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def check_text(post):
    if not isinstance(post, str) or not post.strip():
        raise RequestError("a cím üres vagy nem szöveg")
    if CONTROL.search(post):
        raise RequestError("vezérlőkarakter a címben")
    if "<post>" in post or "</post>" in post:
        raise RequestError("a cím tartalmazza a határolót")


def user_text(post):
    return P.USER_TEMPLATE.format(postText=post)


def gemini_body(post, mcfg):
    check_text(post)
    g = mcfg["providers"]["gemini"]
    return {"systemInstruction": {"parts": [{"text": P.SYSTEM_INSTRUCTION}]},
            "contents": [{"role": "user", "parts": [{"text": user_text(post)}]}],
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": P.gemini_schema(mcfg["max_points_per_signal"]),
                                 "temperature": g["temperature"], "maxOutputTokens": g["max_output_tokens"]}}


def groq_body(post, mcfg):
    check_text(post)
    g = mcfg["providers"]["groq"]
    return {"model": g["model"], "messages": [{"role": "system", "content": P.SYSTEM_INSTRUCTION}, {"role": "user", "content": user_text(post)}],
            "temperature": g["temperature"], "max_completion_tokens": g["max_completion_tokens"], "reasoning_effort": g["reasoning_effort"],
            "response_format": P.groq_response_format(mcfg["max_points_per_signal"])}


BUILDERS = {"gemini": gemini_body, "groq": groq_body}


def body_sha256(body):
    return sha256_text(P.canonical_json(body))


def check_body(provider, body, post, mcfg):
    """Üres lista = a kérés pontosan az, aminek lennie kell (a prompt, a séma és a cím; semmi más)."""
    errs = []
    try:
        if body != BUILDERS[provider](post, mcfg):
            errs.append("a kérés nem egyezik az épített kérés tartalmával")
    except RequestError as e:
        errs.append(str(e))
    txt = json.dumps(body, ensure_ascii=False)
    if SECRET.search(txt.replace("api_key", "")):
        errs.append("kulcsra vagy hitelesítésre utaló minta a kérésben")
    return errs


# ---------------------------------------------------------------- válasz

def _words(s):
    return len(re.findall(r"\S+", s))


def validate_signals(obj, post, mcfg):
    """(score-szótár, hiba). A span a címnek szó szerinti (NFC-normalizált) részlete; 0 pontnál üres. Az összeget a kód számolja."""
    if not isinstance(obj, dict) or set(obj) != set(P.SIGNALS):
        return None, f"a kimenet kulcsai nem pontosan a négy jel: {sorted(obj) if isinstance(obj, dict) else type(obj).__name__}"
    nfc_post = unicodedata.normalize("NFC", post)
    sig, total = {}, 0
    for name in P.SIGNALS:
        s = obj[name]
        if not isinstance(s, dict) or set(s) != {"span", "reason", "score"}:
            return None, f"{name}: a mezők nem pontosan span, reason, score"
        sc, span, reason = s["score"], s["span"], s["reason"]
        if isinstance(sc, bool) or not isinstance(sc, int) or not 0 <= sc <= mcfg["max_points_per_signal"]:
            return None, f"{name}: a pont nem 0..{mcfg['max_points_per_signal']} egész"
        if not isinstance(reason, str) or _words(reason) > mcfg["max_reason_words"]:
            return None, f"{name}: az indoklás hosszabb {mcfg['max_reason_words']} szónál"
        if not isinstance(span, str):
            return None, f"{name}: a span nem szöveg"
        span = unicodedata.normalize("NFC", span)
        if sc == 0 and span != "":
            return None, f"{name}: 0 pontnál a span nem üres"
        if sc > 0 and (not span or span not in nfc_post):
            return None, f"{name}: a span nem szó szerinti részlete a címnek"
        sig[name] = {"score": sc, "reason": reason, "span": span}
        total += sc
    return {"signals": sig, "total": total, "scaled": total / P.MAX_TOTAL}, None


def _retry_hint(msg):
    """„try again in 3h2m” / „7.5s” / „1m30.5s” jellegű szolgáltatói jelzés másodpercben (nincs jelzés: None)."""
    m = re.search(r"try again in\s+(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+(?:\.\d+)?)s)?", msg, re.I)
    if m and (m.group(1) or m.group(2) or m.group(3)):
        return float(m.group(3) or 0) + 60 * float(m.group(2) or 0) + 3600 * float(m.group(1) or 0)
    return None


def classify_error(provider, status, d, retry_header=None):
    err = d.get("error", {}) if isinstance(d, dict) else {}
    msg = sanitize(err.get("message", ""), 200)
    code = str(err.get("code", ""))
    ra = None
    if retry_header not in (None, ""):
        try:
            ra = float(retry_header)
        except (TypeError, ValueError):
            ra = None
    quota_ids = []
    for det in err.get("details") or []:
        for v in (det.get("violations") or []) if isinstance(det, dict) else []:
            quota_ids.append(str(v.get("quotaId") or v.get("quotaMetric") or ""))
        m = re.match(r"^\s*([0-9.]+)s\s*$", str(det.get("retryDelay", ""))) if isinstance(det, dict) else None
        if m and ra is None:
            ra = float(m.group(1))
    if ra is None:
        ra = _retry_hint(msg)
    if status == 429:
        low = msg.lower()
        if any("PerDay" in q for q in quota_ids) or "per day" in low or "(tpd)" in low or "(rpd)" in low:
            return Outcome("quota_day", f"napi kvóta: {msg}", retry_after=ra)
        return Outcome("quota_minute", f"percenkénti kvóta: {msg}", retry_after=ra)
    if status >= 500:
        return Outcome("transient", f"HTTP {status}: {msg}")
    if provider == "groq" and status == 400 and code == "json_validate_failed":
        return Outcome("invalid", "a szolgáltató szerint a kimenet nem felel meg a sémának")
    if status in (400, 402, 403) and BILLING.search(msg):
        return Outcome("billing", f"HTTP {status}: számlázási vagy csomag-üzenet: {msg}")
    return Outcome("fatal", f"HTTP {status}: {msg}")


def _usage(provider, d):
    if provider == "gemini":
        u = d.get("usageMetadata") or {}
        m = {"prompt_tokens": u.get("promptTokenCount"), "completion_tokens": u.get("candidatesTokenCount"), "reasoning_tokens": u.get("thoughtsTokenCount"), "total_tokens": u.get("totalTokenCount")}
    else:
        u = d.get("usage") or {}
        m = {"prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"), "total_tokens": u.get("total_tokens"),
             "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens")}
    return {k: v for k, v in m.items() if isinstance(v, int)}


def parse_response(provider, status, raw_text, post, mcfg, retry_header=None):
    try:
        d = json.loads(raw_text)
    except (TypeError, ValueError):
        return Outcome("transient" if status >= 500 else "fatal", f"HTTP {status}: a válasz nem JSON")
    if status != 200:
        return classify_error(provider, status, d, retry_header)
    usage = _usage(provider, d)
    if provider == "gemini":
        mv = d.get("modelVersion")
        pf = d.get("promptFeedback") or {}
        if pf.get("blockReason"):
            return Outcome("blocked", f"a kérést blokkolták: {pf['blockReason']}", usage=usage, model_returned=mv)
        cands = d.get("candidates") or []
        if not cands:
            return Outcome("empty", "nincs candidate és nincs blockReason", usage=usage, model_returned=mv)
        fr = cands[0].get("finishReason")
        if fr in BLOCK_FINISH:
            return Outcome("blocked", f"a választ blokkolták: {fr}", finish_reason=fr, usage=usage, model_returned=mv)
        if fr == "MAX_TOKENS":
            return Outcome("truncated", "a kimenet elérte a maxOutputTokens-t", finish_reason=fr, usage=usage, model_returned=mv)
        if fr not in (None, "STOP"):
            return Outcome("invalid", f"váratlan finishReason: {fr}", finish_reason=fr, usage=usage, model_returned=mv)
        parts = (cands[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought"))
    else:
        mv = d.get("model")
        ch = (d.get("choices") or [None])[0]
        if not isinstance(ch, dict):
            return Outcome("empty", "nincs choices a válaszban", usage=usage, model_returned=mv)
        fr = ch.get("finish_reason")
        if fr == "length":
            return Outcome("truncated", "a kimenet elérte a max_completion_tokens-t", finish_reason=fr, usage=usage, model_returned=mv)
        text = (ch.get("message") or {}).get("content")
    if not isinstance(text, str) or not text.strip():
        return Outcome("empty", "üres szöveges kimenet", finish_reason=fr, usage=usage, model_returned=mv)
    try:
        obj = json.loads(text)
    except ValueError:
        return Outcome("invalid", "a modell kimenete nem érvényes JSON", finish_reason=fr, usage=usage, model_returned=mv)
    score, err = validate_signals(obj, post, mcfg)
    if err:
        return Outcome("invalid", sanitize(err), finish_reason=fr, usage=usage, model_returned=mv)
    return Outcome("ok", score=score, finish_reason=fr, usage=usage, model_returned=mv)
