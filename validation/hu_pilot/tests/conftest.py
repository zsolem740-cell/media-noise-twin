import json
import random

import pytest

from validation.hu_pilot.paths import load_config

NOUNS = ("kerítés bödön szőlő tűzfal ősz hídfő várkert gyűrű kútfő dűlő ménes őrség kanyar sólyom fűrész börtön tükör ötös ligetes pékség orgona cserép márvány lépcső "
         "hegedű kovász gyömbér vásár ürge kútágas ködös szélmalom mészárszék csűr tömlöc lombik szövőszék pásztor gombóc kovács tanya hordó cukrász").split()
FILLER = "az egy és hogy nem meg már még van volt lesz ez ezt de csak vagy mint után szerint miatt között ellen kell lehet nagy új két mit mikor hol aki több nagyon itt ma most".split()


def make_titles(n, seed=1):
    rng, seen, out = random.Random(seed), set(), []
    while len(out) < n:
        w = rng.sample(NOUNS, 5) + rng.sample(FILLER, 4)
        rng.shuffle(w)
        t = " ".join(w).capitalize()
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def make_feed(n=200, seed=1, extra=()):
    titles = make_titles(n, seed)
    rng = random.Random(seed + 1)
    items = []
    for i, t in enumerate(titles):
        r = i % 17
        if r == 0:
            t += "!"
        elif r == 1:
            t = t.replace(t.split()[1], "BOTRÁNY", 1)
        elif r == 2:
            t += "?"
        elif r == 3:
            t = "„" + t + "”"
        items.append({"id": f"id{i:04d}", "title": t, "source": f"Forrás{i % 30}", "source_domain": "forras.hu", "official": False, "alert": False,
                      "S": rng.random(), "G": rng.random(), "V": rng.random(), "ATM": 7, "lat": 47.1, "lng": 19.0, "region": "HU-BU", "link": "https://x.hu/" + str(i)})
    items += list(extra)
    return {"schema": 1, "generated_at": "2026-11-12T00:00:00Z", "items": items,
            "model": {"formula": "x", "regions": [{"id": "HU", "name": "Magyarország"}], "weights": {"a": 1.5}, "clickbait": ["sokk"], "thresholds": {"hi": 0.6}},
            "summary": {"n_items": 200, "atm_mean": 69.4, "by_region": {"HU": 3}, "top_noise": [{"t": "x"}]}, "insights": {"trend": {"d": [1, 2]}, "anomalies": [1], "sources": [2]},
            "notified": {"ids": {"a": 1}, "terms": {"b": 2}}, "config": {"user": True, "applied": [1]}, "research": {"version": 1, "prices": {"x": 1.5}},
            "profiles": {"forras.hu": {"n": 5, "mS": 0.5}}}


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture
def feed_path(tmp_path):
    p = tmp_path / "feed.json"
    p.write_text(json.dumps(make_feed(), ensure_ascii=False), encoding="utf-8")
    return p


def backup(voter, votes, skipped=(), mids=()):
    def rec(i, kind, blind=True):
        return {"id": i, "vote": kind, "title": "t " + i, "ts": 1000, "blind": blind, "voter": voter, "domain": "x.hu"}
    return {"format": "mnt-backup", "version": 1, "voter": voter, "votes": [rec(i, k, b) if len(x) == 3 else rec(i, k) for x in votes for (i, k, *b_) in [x] for b in [b_[0] if b_ else True]],
            "mids": list(mids), "skipped": list(skipped)}
