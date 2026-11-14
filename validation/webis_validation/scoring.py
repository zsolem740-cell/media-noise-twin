"""Az AI-kimenet ellenőrzése (négy jel, 0–2 pont, rövid indoklás, a címből idézett részlet) és a modell bemenetének korlátozása."""
import re

SIGNALS = ("curiosity_gap", "exaggeration", "emotional_pressure", "formal_noise")
MAX_TOTAL = 8
# Amit a modell soha nem kaphat meg: a cikk, a forrás, az emberi pontszám, korábbi AI-pontszám, más szavazók.
FORBIDDEN_MODEL_FIELDS = ("targetTitle", "targetDescription", "targetKeywords", "targetParagraphs", "targetCaptions", "postMedia",
                          "truthJudgments", "truthMean", "truthMedian", "truthMode", "truthClass", "publisher", "source_domain",
                          "human_mean", "human_median", "judgments", "prior_score", "votes")


def build_model_input(record):
    """A modell bemenete: kizárólag az azonosító és a poszt szövege, a korpusz mezőnevén (postText; itt szöveg, az eredeti egyelemű lista eleme)."""
    return {"id": record.id, "postText": record.text}


def to_scaled(total):
    """Kezdeti, nem bizonyított feltevés: lineáris átváltás, pont / 8."""
    return total / MAX_TOTAL


def _words(s):
    return len(re.findall(r"\S+", s))


def validate_score(obj, text, cfg):
    """Hibák listája (üres, ha az objektum érvényes). A span-ellenőrzés a címhez képest történik."""
    sc = cfg["scoring"]
    errs = []
    if not isinstance(obj, dict):
        return ["az objektum nem szótár"]
    extra = set(obj) - {"id", "source", "signals", "total", "scaled"}
    missing = {"id", "source", "signals", "total", "scaled"} - set(obj)
    if extra:
        errs.append(f"ismeretlen mező: {sorted(extra)}")
    if missing:
        errs.append(f"hiányzó mező: {sorted(missing)}")
        return errs
    if not isinstance(obj["id"], str) or not obj["id"]:
        errs.append("az id nem üres szöveg")
    if obj["source"] != cfg["source"]:
        errs.append(f"a source csak {cfg['source']} lehet")
    sig = obj["signals"]
    if not isinstance(sig, dict) or set(sig) != set(sc["signals"]):
        errs.append(f"a signals kulcsai pontosan: {list(sc['signals'])}")
        return errs
    total = 0
    for name in sc["signals"]:
        s = sig[name]
        if not isinstance(s, dict) or set(s) != {"score", "reason", "span"}:
            errs.append(f"{name}: a mezők pontosan score, reason, span")
            continue
        score = s["score"]
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= sc["max_points_per_signal"]:
            errs.append(f"{name}: a pont 0, 1 vagy 2 egész")
            continue
        total += score
        if not isinstance(s["reason"], str) or _words(s["reason"]) > sc["max_reason_words"]:
            errs.append(f"{name}: az indoklás legfeljebb {sc['max_reason_words']} szó")
        if not isinstance(s["span"], str):
            errs.append(f"{name}: a span szöveg")
        elif score == 0 and s["span"] != "":
            errs.append(f"{name}: 0 pontnál a span üres")
        elif score > 0 and (not s["span"] or s["span"] not in text):
            errs.append(f"{name}: a span nem szó szerinti részlete a címnek")
    if isinstance(obj["total"], bool) or not isinstance(obj["total"], int) or obj["total"] != total:
        errs.append(f"a total nem egyezik a jelek összegével ({total})")
    if not isinstance(obj["scaled"], (int, float)) or abs(obj["scaled"] - to_scaled(obj["total"] if isinstance(obj["total"], int) else total)) > 1e-9:
        errs.append("a scaled nem total / 8")
    return errs
