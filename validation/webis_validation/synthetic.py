"""Szintetikus Webis-formátumú korpusz és egy szabályalapú PRÓBA-pontozó a csővezeték ellenőrzéséhez.
Minden cím kitalált. A próba-pontozó NEM AI és NEM mérési eredményt ad: csak azt bizonyítja, hogy a betöltés → minta → séma → kiértékelés lánc végigfut."""
import json
import random
import statistics
from pathlib import Path

CALM = ["City council approves road repair budget", "Library extends opening hours on weekends", "Local school wins regional science fair",
        "Museum opens new exhibit about river history", "Transit agency publishes spring timetable", "Farmers market returns to the old square",
        "Utility announces planned water maintenance", "Park district plants two hundred new trees", "Hospital adds evening clinic hours",
        "University releases annual enrollment figures"]
CURIOSITY = ["You won't believe what happened next", "This is why nobody talks about it", "The secret nobody told you", "What they found will surprise you"]
EXAGG = ["The most shocking story of the year", "Absolutely incredible, the best ever", "The worst disaster in history", "Amazing results nobody expected"]
EMOTION = ["Heartbreaking scenes leave everyone in tears", "Terrifying moment sparks outrage", "Furious crowd demands answers", "A devastating loss shocks the town"]
FORMAL = ["10 things you need to know", "BREAKING!!! Read this now", "WOW this is HUGE", "7 reasons why it matters"]
SCALE = [0.0, 0.33, 0.66, 1.0]


def make_corpus(n=300, seed=1):
    """(instances, truth) sorok; az ítéletek a címben lévő jelek számától függenek, zajjal."""
    rng = random.Random(seed)
    inst, truth = [], []
    for i in range(n):
        parts, level = [rng.choice(CALM)], 0
        for pool, p in ((CURIOSITY, 0.25), (EXAGG, 0.2), (EMOTION, 0.2), (FORMAL, 0.2)):
            if rng.random() < p:
                parts.insert(rng.randrange(len(parts) + 1), rng.choice(pool))
                level += 1
        text = ": ".join(parts) + f" ({i})" if rng.random() < 0.5 else ": ".join(parts) + f" #{i}"
        judg = [SCALE[max(0, min(3, level + rng.choice([-1, 0, 0, 1])))] for _ in range(5)]
        rid = f"syn{i:05d}"
        inst.append({"id": rid, "postText": [text], "targetTitle": "(a cikk címe: a validációban a modell nem kapja meg)"})
        truth.append({"id": rid, "truthJudgments": judg, "truthMean": round(sum(judg) / 5, 4), "truthMedian": statistics.median(judg),
                      "truthMode": max(set(judg), key=judg.count), "truthClass": "clickbait" if sum(judg) / 5 >= 0.5 else "no-clickbait"})
    return inst, truth


def write_corpus(directory, n=300, seed=1, instances="instances.jsonl", truth="truth.jsonl"):
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    inst, tr = make_corpus(n, seed)
    for name, rows in ((instances, inst), (truth, tr)):
        (d / name).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return d / instances, d / truth


_TRIGGERS = {"curiosity_gap": ("You won't believe", "This is why", "The secret", "will surprise you", "What they found"),
             "exaggeration": ("most shocking", "incredible", "worst", "Amazing", "best ever"),
             "emotional_pressure": ("Heartbreaking", "Terrifying", "outrage", "Furious", "devastating"),
             "formal_noise": ("!!!", "WOW", "HUGE", "BREAKING", "10 things", "7 reasons")}


def mock_score(record_id, text, source="webis-clickbait-17"):
    """Szabályalapú PRÓBA-pontozó (nem AI): jelenkénti kulcsszavak száma alapján 0–2 pont, a címből vett részlettel."""
    signals, total = {}, 0
    for name, trig in _TRIGGERS.items():
        hits = [t for t in trig if t in text]
        score = min(2, len(hits))
        total += score
        signals[name] = {"score": score, "reason": ("keyword match" if score else "no trigger"), "span": hits[0] if hits else ""}
    return {"id": record_id, "source": source, "signals": signals, "total": total, "scaled": total / 8}
