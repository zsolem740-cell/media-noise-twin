"""Groq-kérés (csomagos, OpenAI-kompatibilis chat completions) felépítése és a válasz feldolgozása. HÁLÓZAT NÉLKÜL: ez a fájl nem küld és nem fogad semmit.

A címkézési szabályok SZÓ SZERINT a Gemini-ágéval azonosak (gemini_request.SYSTEM_INSTRUCTION, ez a fájl azt nem módosítja); a csomagolásról csak egy kiegészítő
bekezdés szól. Egy kérésben legfeljebb batch_size cím megy, helyi azonosítókkal (t1, t2, …); a korpusz-azonosítóra a kód képezi vissza.
Az összeget és a 0–1-es skálát a kód számolja, a modell nem."""
import json
import re
from dataclasses import dataclass, field

from . import gemini_request as gr
from . import scoring
from .isolation import has_hungarian_chars

BATCH_ADDENDUM = (
    "\nBatch mode: the user message contains several posts, each wrapped as <post id=\"tN\"> ... </post>. Assess every post independently of the others. "
    "Return one object with the key \"items\": a list with exactly one entry per post, in the same order. Every entry has the key \"id\" "
    "(copied exactly from the post tag) and the four signals, each with span, reason and score as described above."
)
SYSTEM_PROMPT = gr.SYSTEM_INSTRUCTION + BATCH_ADDENDUM                     # v1: a futtatott első változat, változatlanul
STRICT_ADDENDUM = (
    "\nStrict scoring rules (they narrow the rules above; when in doubt, score lower):\n"
    "- Judge only the linguistic wording of the post text. Never score a fact, a topic, a real-world event, a number or size as such, or what the underlying article might contain.\n"
    "- curiosity_gap: score above 0 only if the wording itself deliberately withholds the key information, e.g. a demonstrative or vague stand-in "
    "for the subject (\"This <noun> had a cute way of ...\") or an explicit teaser. A general question or an ordinary news statement is not enough on its own. "
    "Phrases like \"questions why\", \"playing a key role\" or \"has set off another debate\" are not enough on their own.\n"
    "- exaggeration: only linguistic exaggeration counts: hyperbole, superlatives, strikingly strong wording or idioms such as \"killed it\". "
    "A factual claim, a size, a number or a surprising topic does not count by itself.\n"
    "- emotional_pressure: only fear, anger, urgency, guilt or pressure that the wording of the text itself creates. A topic word such as a mention of race, police or an animal "
    "does not count by itself. Words like \"under fire\" or \"threatens\" count only if the phrasing really builds pressure.\n"
    "- formal_noise: only the formatting elements listed above count. A hashtag alone scores at most 1. An acronym such as TSA is not ALL-CAPS noise. "
    "An \"RT\" prefix is not on the list and does not count. Score 2 only for several clear formatting elements together.\n"
    "- For every signal: score 0, 1 or 2 and give a short reason. When the score is above 0, span must be an exact quote from the post; when the score is 0, span must be empty."
)
SYSTEM_PROMPT_V2 = gr.SYSTEM_INSTRUCTION + STRICT_ADDENDUM + BATCH_ADDENDUM  # v2: ugyanaz az alap, szigorító kiegészítéssel


def system_prompt(cfg):
    v = cfg["groq"].get("prompt_version", "v1")
    if v == "v1":
        return SYSTEM_PROMPT
    if v == "v2":
        return SYSTEM_PROMPT_V2
    raise RequestError(f"ismeretlen prompt_version: {v}")
POST_TEMPLATE = "<post id=\"{lid}\">\n{postText}\n</post>"
ALLOWED_TOP_KEYS = {"model", "messages", "temperature", "max_completion_tokens", "reasoning_effort", "response_format"}
KEY_PATTERNS = [r"gsk_[0-9A-Za-z]{10,}", r"api[_\-]?key", r"Bearer\s", r"Authorization", r"GROQ_API_KEY"]
LABEL_STRINGS = ("truthClass", "no-clickbait", "clickbait")
EXTRA_FORBIDDEN_KEYS = {"tools", "tool_choice", "total", "scaled", "truthClass", "stream", "user"}


class RequestError(Exception):
    pass


def local_ids(n):
    return [f"t{i}" for i in range(1, n + 1)]


def item_schema(cfg):
    sc = cfg["scoring"]
    one = {"type": "object", "additionalProperties": False, "required": ["span", "reason", "score"],
           "properties": {"span": {"type": "string"}, "reason": {"type": "string"},
                          "score": {"type": "integer", "enum": list(range(sc["max_points_per_signal"] + 1))}}}
    props = {"id": {"type": "string"}}
    props.update({k: json.loads(json.dumps(one)) for k in sc["signals"]})
    return {"type": "object", "additionalProperties": False, "required": ["id"] + list(sc["signals"]), "properties": props}


def response_format(cfg):
    """A kimenet sémája: items-lista, elemenként id + négy jel. Összeg és skálázott érték NINCS benne."""
    return {"type": "json_schema", "json_schema": {"name": "title_noise_batch", "strict": bool(cfg["groq"]["generation"].get("strict", True)),
                                                    "schema": {"type": "object", "additionalProperties": False, "required": ["items"],
                                                               "properties": {"items": {"type": "array", "items": item_schema(cfg)}}}}}


def build_body(items, cfg):
    """items = [(helyi azonosító, poszt szövege), …]. Egyetlen változó bemenet a posztok szövege; semmi más nem kerülhet bele."""
    g = cfg["groq"]
    if not items or len(items) > g["batch_size"]:
        raise RequestError(f"a csomag mérete 1..{g['batch_size']} lehet")
    lids = [lid for lid, _ in items]
    if lids != local_ids(len(items)):
        raise RequestError("a helyi azonosítók nem t1..tN sorrendben vannak")
    for _, text in items:
        if not isinstance(text, str) or not text.strip():
            raise RequestError("a postText üres vagy nem szöveg")
        if has_hungarian_chars(text):
            raise RequestError("magyar-specifikus betű a szövegben: nem Webis-adat")
        if gr.CONTROL.search(text):
            raise RequestError("vezérlőkarakter a szövegben")
        if "<post" in text or "</post>" in text:
            raise RequestError("a szöveg tartalmazza a határolót")
    gen = g["generation"]
    return {"model": g["model"],
            "messages": [{"role": "system", "content": system_prompt(cfg)}, {"role": "user", "content": user_text(items)}],
            "temperature": gen["temperature"], "max_completion_tokens": gen["max_completion_tokens"],
            "reasoning_effort": gen["reasoning_effort"], "response_format": response_format(cfg)}


def user_text(items):
    return "\n".join(POST_TEMPLATE.format(lid=lid, postText=t) for lid, t in items)


def check_request(body, items, cfg, leak_strings=()):
    """A kimenő kérés ellenőrzése. Üres lista = rendben."""
    errs = []
    if not isinstance(body, dict):
        return ["a kérés nem szótár"]
    if set(body) - ALLOWED_TOP_KEYS or ALLOWED_TOP_KEYS - set(body):
        errs.append(f"a felső szintű kulcsok nem pontosan a megengedettek: {sorted(set(body) ^ ALLOWED_TOP_KEYS)}")
    msgs = body.get("messages")
    if not isinstance(msgs, list) or len(msgs) != 2 or [m.get("role") if isinstance(m, dict) else None for m in msgs] != ["system", "user"] \
            or any(set(m) != {"role", "content"} for m in msgs):
        errs.append("a messages nem pontosan egy system és egy user üzenet")
    else:
        if msgs[0]["content"] != system_prompt(cfg):
            errs.append("a system üzenet nem a rögzített utasítás")
        if msgs[1]["content"] != user_text(items):
            errs.append("a user üzenet nem a rögzített sablon és a postText-ek")
    if body.get("model") != cfg["groq"]["model"]:
        errs.append("a modell nem a beállított")
    bad_keys = {k for k in gr._walk_keys(body) if k in set(scoring.FORBIDDEN_MODEL_FIELDS) | EXTRA_FORBIDDEN_KEYS}
    if bad_keys:
        errs.append(f"tiltott mezőnév a kérésben: {sorted(bad_keys)}")
    try:
        full = gr.canonical_json(body)
    except TypeError as e:
        return errs + [f"a kérés nem szerializálható: {e}"]
    allowed_user = json.dumps(user_text(items), ensure_ascii=False)[1:-1]
    fixed = full.replace(allowed_user, "")
    for pat in KEY_PATTERNS:
        if re.search(pat, full):
            errs.append(f"API-kulcsra vagy hitelesítésre utaló minta a kérésben: {pat}")
    if has_hungarian_chars(full):
        errs.append("magyar-specifikus karakter a kérésben")
    for lab in LABEL_STRINGS:
        if lab in fixed:
            errs.append(f"címkeszöveg a rögzített részben: {lab}")
    for s in leak_strings:
        if isinstance(s, str) and len(s) >= 12 and s in fixed:
            errs.append("a cikk- vagy emberi adat szövege a kérés rögzített részében van")
            break
    if not errs:
        try:
            if body != build_body(items, cfg):
                errs.append("a kérés nem egyezik a build_body eredményével")
        except RequestError as e:
            errs.append(str(e))
    return errs


# ---------------------------------------------------------------- válasz feldolgozása

@dataclass
class BatchOutcome:
    kind: str                       # ok, empty, truncated, invalid, quota_day, quota_minute, transient, fatal
    detail: str = ""
    retry_after: float | None = None
    usage: dict = field(default_factory=dict)
    finish_reason: str | None = None
    model: str | None = None
    results: dict = field(default_factory=dict)      # helyi azonosító -> score-objektum (csak az érvényesek)
    item_errors: dict = field(default_factory=dict)  # helyi azonosító -> ok (missing_id, invalid:…, duplicate…)
    stray: int = 0                                   # nem hozzárendelhető elemek (nincs vagy ismeretlen azonosító)


def _usage(d):
    u = d.get("usage") or {}
    out = {k: u.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens") if isinstance(u.get(k), int)}
    r = (u.get("completion_tokens_details") or {}).get("reasoning_tokens")
    if isinstance(r, int):
        out["reasoning_tokens"] = r
    return out


def _retry_after_from_message(msg):
    m = re.search(r"try again in\s+(?:(\d+)m)?\s*([0-9.]+)s", msg, re.I)
    if m:
        return float(m.group(2)) + 60 * float(m.group(1) or 0)
    return None


def classify_error(status, d, retry_after_header=None):
    """Nem 200-as válasz besorolása. A 429 napi korlátja (TPD/RPD) leállás, a percenkéntié várakozás; az 5xx átmeneti; a 400 json_validate_failed érvénytelen kimenet."""
    err = d.get("error", {}) if isinstance(d, dict) else {}
    msg = str(err.get("message", ""))[:300]
    code = str(err.get("code", ""))
    ra = None
    try:
        ra = float(retry_after_header) if retry_after_header not in (None, "") else None
    except (TypeError, ValueError):
        ra = None
    if ra is None:
        ra = _retry_after_from_message(msg)
    if status == 429:
        low = msg.lower()
        if "per day" in low or "(tpd)" in low or "(rpd)" in low:
            return BatchOutcome("quota_day", f"napi korlát: {msg}", retry_after=ra)
        return BatchOutcome("quota_minute", f"percenkénti korlát: {msg}", retry_after=ra)
    if status >= 500:
        return BatchOutcome("transient", f"HTTP {status}: {msg}")
    if status == 400 and code == "json_validate_failed":
        return BatchOutcome("invalid", "a szolgáltató szerint a kimenet nem felel meg a sémának (json_validate_failed)")
    return BatchOutcome("fatal", f"HTTP {status}: {msg}")


def parse_response(status, raw_text, items, cfg, retry_after_header=None):
    """A HTTP-válasz besorolása és (siker esetén) az elemenkénti ellenőrzés. items = [(helyi azonosító, szöveg), …]."""
    try:
        d = json.loads(raw_text)
    except (TypeError, ValueError):
        return BatchOutcome("transient" if status >= 500 else "fatal", f"HTTP {status}: a válasz nem JSON")
    if status != 200:
        return classify_error(status, d, retry_after_header)
    usage, model = _usage(d), d.get("model")
    choices = d.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return BatchOutcome("empty", "nincs choices a válaszban", usage=usage, model=model)
    ch = choices[0]
    fr = ch.get("finish_reason")
    content = (ch.get("message") or {}).get("content")
    if fr == "length":
        return BatchOutcome("truncated", "a kimenet elérte a max_completion_tokens-t", usage=usage, finish_reason=fr, model=model)
    if not isinstance(content, str) or not content.strip():
        return BatchOutcome("empty", "üres szöveges kimenet", usage=usage, finish_reason=fr, model=model)
    try:
        obj = json.loads(content)
    except ValueError:
        return BatchOutcome("invalid", "a modell kimenete nem érvényes JSON", usage=usage, finish_reason=fr, model=model)
    if not isinstance(obj, dict) or set(obj) != {"items"} or not isinstance(obj["items"], list):
        return BatchOutcome("invalid", "a kimenet nem pontosan {\"items\": [...]}", usage=usage, finish_reason=fr, model=model)
    out = BatchOutcome("ok", usage=usage, finish_reason=fr, model=model)
    texts = dict(items)
    seen = set()
    for it in obj["items"]:
        lid = it.get("id") if isinstance(it, dict) else None
        if not isinstance(lid, str) or not lid:
            out.stray += 1                                             # hiányzó azonosító: nem rendelhető egyetlen címhez sem
            continue
        if lid not in texts:
            out.stray += 1                                             # ismeretlen azonosító
            continue
        if lid in seen:
            out.item_errors[lid] = "duplicate_id"
            out.results.pop(lid, None)
            continue
        seen.add(lid)
        built, err = gr._validate_model_json({k: v for k, v in it.items() if k != "id"}, content, cfg)
        if err:
            out.item_errors[lid] = f"invalid: {err}"
            continue
        score = {"id": lid, "source": cfg["source"], **built}
        errs = scoring.validate_score(score, texts[lid], cfg)
        if errs:
            out.item_errors[lid] = "invalid: " + "; ".join(errs)
        else:
            out.results[lid] = score
    for lid, _ in items:
        if lid not in seen:
            out.item_errors.setdefault(lid, "missing_id")             # a csomagból hiányzik a cím azonosítója
    for lid in [k for k, v in out.item_errors.items() if v == "duplicate_id"]:
        out.results.pop(lid, None)
    return out
