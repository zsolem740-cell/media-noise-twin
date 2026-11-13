"""A pilot címeinek kiválasztása a hírmentésből: 20 horgony + 30 mérési (15 véletlen + 15 formai jegyekkel dúsított). Modellpontszámot nem használ.

A kiválasztás determinisztikus (rögzített mag). A szűrés kizárja a hivatalos és riasztás típusú tételeket, a duplikátumokat és közel-duplikátumokat,
a túl rövid és túl hosszú címeket, és csak olyan címet enged, amelyet a felület a forrás-domain nélkül is magyarnak ismer fel."""
import json
import random
import re
import unicodedata
from pathlib import Path

from .lang import detect_lang

CAPS = re.compile(r"\b[^\W\d_a-záéíóöőúüű]{4,}\b")     # legalább 4 betűs, csupa nagybetűs szó
QUOTE = re.compile(r"[\"„”“]")


def norm(title):
    t = unicodedata.normalize("NFKC", str(title)).lower()
    return " ".join(re.findall(r"[^\W_]+", t))


def source_key(src):
    s = str(src or "").lower().strip()
    s = re.sub(r"^(https?://)?(www\.)?", "", s).strip("/ ")
    s = re.sub(r"^[|#\s-]+", "", s)
    return s or "?"


def features(title):
    return {"exclamation": "!" in title, "caps": bool(CAPS.search(title)), "question": "?" in title, "quote": bool(QUOTE.search(title))}


def jaccard(a, b):
    a, b = set(a.split()), set(b.split())
    return len(a & b) / len(a | b) if a and b else 0.0


def load_feed(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return d, d.get("items", [])


def eligible(items, cfg):
    f = cfg["filters"]
    out, seen, reasons = [], [], {"nem_magyar": 0, "hivatalos_vagy_riasztas": 0, "hossz": 0, "duplikatum": 0, "hianyzo": 0}
    for it in sorted(items, key=lambda r: str(r.get("id"))):
        t = it.get("title")
        if not isinstance(t, str) or not t.strip() or not it.get("id"):
            reasons["hianyzo"] += 1
            continue
        if it.get("official") or it.get("alert"):
            reasons["hivatalos_vagy_riasztas"] += 1
            continue
        if not f["min_len"] <= len(t) <= f["max_len"] or "\n" in t:
            reasons["hossz"] += 1
            continue
        if detect_lang(t, "") != "hu":
            reasons["nem_magyar"] += 1
            continue
        n = norm(t)
        if any(n == s or jaccard(n, s) >= f["jaccard_dup"] for s in seen):
            reasons["duplikatum"] += 1
            continue
        seen.append(n)
        out.append(it)
    return out, reasons


def select(items, cfg, anchors_override=None):
    sz, f = cfg["sizes"], cfg["filters"]
    pool, reasons = eligible(items, cfg)
    rng = random.Random(cfg["seed"])
    cap, used_src = f["source_cap_total"], {}
    chosen_ids = set()

    def take(cands, n, label):
        got = []
        for it in cands:
            if len(got) >= n:
                break
            k = source_key(it.get("source"))
            if it["id"] in chosen_ids or used_src.get(k, 0) >= cap:
                continue
            chosen_ids.add(it["id"])
            used_src[k] = used_src.get(k, 0) + 1
            got.append(it)
        if len(got) < n:
            raise ValueError(f"nincs elég megfelelő cím a(z) {label} csoporthoz ({len(got)} / {n})")
        return got

    shuffled = lambda xs: rng.sample(xs, len(xs))
    by_id = {it["id"]: it for it in pool}
    if anchors_override:
        bad = [i for i in anchors_override if i not in by_id]
        if bad:
            raise ValueError(f"a felülírt horgony nem megfelelő vagy nem létezik: {bad[:3]}")
        anchors = take([by_id[i] for i in anchors_override], len(anchors_override), "horgony (felülírt)")
        if len(anchors) != sz["anchors"]:
            raise ValueError(f"a horgonyok száma {len(anchors)}, kellene: {sz['anchors']}")
    else:
        anchors = []
        for feat, n in cfg["anchor_mix"].items():
            anchors += take(shuffled([it for it in pool if features(it["title"])[feat]]), n, f"horgony/{feat}")
        rest = sz["anchors"] - len(anchors)
        plain = [it for it in pool if not any(features(it["title"]).values())]
        anchors += take(shuffled(plain), rest, "horgony/sima")
    measured_random = take(shuffled(pool), sz["measured_random"], "mérési/véletlen")
    enriched_pool = [it for it in pool if any(features(it["title"]).values())]
    measured_enriched = take(shuffled(enriched_pool), sz["measured_enriched"], "mérési/dúsított")
    return {"anchors": anchors, "measured": measured_random + measured_enriched,
            "measured_random_ids": [i["id"] for i in measured_random], "measured_enriched_ids": [i["id"] for i in measured_enriched],
            "pool": len(pool), "enriched_pool": len(enriched_pool), "excluded": reasons, "source_counts": dict(sorted(used_src.items()))}
