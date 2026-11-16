"""Rétegzett mintavétel az emberi átlag szerint. A célszámok (75/50/50/75) célok, nem kényszerek: ha egy rétegben kevés az elem,
a hiányt a többi rétegből a célszámaik arányában pótoljuk, és ezt a jelentés rögzíti."""
import random
from collections import Counter


class SampleError(Exception):
    pass


def stratum_of(mean, strata):
    for i, s in enumerate(strata):
        if s["lo"] <= mean < s["hi"]:
            return i
    raise SampleError(f"az átlag egyik rétegbe sem esik: {mean}")


def allocate(avail, targets, size):
    """Rétegenkénti darabszám: min(cél, elérhető); a hiányt a még szabad kapacitású rétegek kapják a célszámaik arányában
    (legnagyobb maradék módszer). Visszaad: darabszámok, a pótlásból kapott darabszámok, a nem pótolható maradék."""
    n = [min(t, a) for t, a in zip(targets, avail)]
    moved = [0] * len(n)
    deficit = size - sum(n)
    while deficit > 0:
        open_ = [i for i in range(len(n)) if n[i] < avail[i]]
        if not open_:
            break
        w = {i: (targets[i] or 1) for i in open_}
        tot = sum(w.values())
        share = {i: deficit * w[i] / tot for i in open_}
        add = {i: min(int(share[i]), avail[i] - n[i]) for i in open_}
        left = deficit - sum(add.values())
        for i in sorted(open_, key=lambda k: (-(share[k] - int(share[k])), k)):
            if left <= 0:
                break
            if add[i] < avail[i] - n[i]:
                add[i] += 1
                left -= 1
        gained = sum(add.values())
        if gained == 0:
            break
        for i in open_:
            n[i] += add[i]
            moved[i] += add[i]
        deficit -= gained
    return n, moved, deficit


def stratified_sample(records, cfg):
    sc = cfg["sample"]
    strata, size = sc["strata"], sc["size"]
    if sum(s["target"] for s in strata) != size:
        raise SampleError("a rétegek célszámainak összege nem egyezik a minta méretével")
    by = [[] for _ in strata]
    for r in sorted(records, key=lambda x: x.id):
        by[stratum_of(r.human_mean, strata)].append(r)
    avail = [len(b) for b in by]
    n, moved, shortfall = allocate(avail, [s["target"] for s in strata], size)
    rng = random.Random(sc["seed"])
    picked = []
    for i, b in enumerate(by):
        picked.extend(rng.sample(b, n[i]) if n[i] else [])
    picked.sort(key=lambda r: r.id)
    report = {"seed": sc["seed"], "size_requested": size, "size_actual": len(picked), "shortfall": shortfall,
              "strata": [{"name": s["name"], "target": s["target"], "available": avail[i], "allocated": n[i], "added_from_deficit": moved[i],
                          "short_title": sum(1 for r in picked if stratum_of(r.human_mean, strata) == i and r.short_title)}
                         for i, s in enumerate(strata)],
              "ids": [r.id for r in picked]}
    if len(set(report["ids"])) != len(report["ids"]):
        raise SampleError("ismétlődő azonosító a mintában")
    return picked, report


def distribution(records, strata):
    """A teljes korpusz eloszlása rétegenként (a mintavétel előtt ezt kell megnézni)."""
    c = Counter(stratum_of(r.human_mean, strata) for r in records)
    return [{"name": s["name"], "available": c.get(i, 0)} for i, s in enumerate(strata)]
