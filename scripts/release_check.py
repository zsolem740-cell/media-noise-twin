"""Kiadási ellenőr: egyesítés előtt megmutatja, mit visz be az ág a célághoz képest, és megáll, ha többet, mint amit a felhasználó jóváhagyott.

Csak olvas (git diff, fájlolvasás); nem egyesít, nem nyit PR-t, nem ír a tárolóba, nincs hálózat. A CLAUDE.md szabálya: a jóváhagyás a megnevezett változásra szól.
A jóváhagyott kör `--approved` mintákkal adható meg (ismételhető; `**` bármely mélységet, `*` egy szintet fed). Törlés csak `--allow-delete` mintával engedett.
Kilépési kód: 0 a változás a jóváhagyott körön belül és az Őr tiszta, 1 meg kell állni, 2 nem ellenőrizhető (hiányzó ág).
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import policy_guard as pg  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def glob_to_re(pat):
    out, i = "", 0
    while i < len(pat):
        if pat[i:i + 3] == "**/":
            out += "(?:.*/)?"
            i += 3
        elif pat[i:i + 2] == "**":
            out += ".*"
            i += 2
        elif pat[i] == "*":
            out += "[^/]*"
            i += 1
        elif pat[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pat[i])
            i += 1
    return re.compile("^" + out + "$")


def matches(path, patterns):
    return any(glob_to_re(p).match(path) for p in patterns)


def classify(changes, approved, allow_delete):
    """changes: (státusz, út) párok (az átnevezést a collect törlésre és hozzáadásra bontja). Visszaad: összegzés és megállító okok."""
    added = sorted(p for s, p in changes if s.startswith("A"))
    modified = sorted(p for s, p in changes if s.startswith("M"))
    deleted = sorted(p for s, p in changes if s.startswith("D"))
    stops = []
    for s, p in changes:
        if s.startswith("D"):
            if not matches(p, allow_delete):
                stops.append({"rule": "torles", "where": p, "msg": "törlés, amit senki nem engedélyezett (--allow-delete)"})
        elif not matches(p, approved):
            stops.append({"rule": "jovahagyott-koron-kivul", "where": p, "msg": "a fájl a jóváhagyott körön kívül van"})
    return {"added": added, "modified": modified, "deleted": deleted}, stops


def evaluate(changes, approved, allow_delete, read_text, tracked, policy):
    summary, stops = classify(changes, approved, allow_delete)
    guard = pg.run_checks(changes, tracked, read_text, policy)
    stops += [dict(g, rule="orzo:" + g["rule"]) for g in guard if g["level"] == "hiba"]
    warnings = [g for g in guard if g["level"] != "hiba"]
    if not approved:
        stops.append({"rule": "nincs-jovahagyott-kor", "where": "", "msg": "nincs megadva jóváhagyott kör (--approved): nem lehet eldönteni, hogy több-e a változás"})
    return {"summary": summary, "stops": stops, "warnings": warnings, "verdict": "MEGÁLLNI" if stops else "RENDBEN"}


def _git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, check=False)


def parse_name_status(text):
    changes = []
    for line in text.splitlines():
        parts = line.split("\t")
        if parts[0].startswith(("R", "C")) and len(parts) == 3:               # átnevezés = a régi út törlése + az új út hozzáadása; másolás = új út
            changes += ([("D", parts[1])] if parts[0].startswith("R") else []) + [("A", parts[2])]
        else:
            changes += [(parts[0], p) for p in parts[1:]]
    return changes


def collect(base, head):
    d = _git("diff", "--name-status", "-M", f"{base}...{head}")
    if d.returncode != 0:
        return None, None, d.stderr.strip()
    changes = parse_name_status(d.stdout)
    tracked = _git("ls-tree", "-r", "--name-only", head).stdout.splitlines()
    n = _git("rev-list", "--count", f"{base}..{head}").stdout.strip()
    return changes, tracked, n


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="origin/main", help="célág")
    ap.add_argument("--head", required=True, help="az egyesítendő ág (pl. origin/claude/valami)")
    ap.add_argument("--approved", action="append", default=[], help="jóváhagyott útminta (ismételhető)")
    ap.add_argument("--allow-delete", action="append", default=[], help="törölhető útminta (ismételhető)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    changes, tracked, extra = collect(a.base, a.head)
    if changes is None:
        print(f"NEM ELLENŐRIZHETŐ: {extra}", file=sys.stderr)
        return 2
    reader = lambda p: (lambda r: r.stdout if r.returncode == 0 else None)(_git("show", f"{a.head}:{p}"))
    res = evaluate(changes, a.approved, a.allow_delete, reader, tracked, pg.load_policy())
    res.update({"base": a.base, "head": a.head, "commits": int(extra or 0)})
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        s = res["summary"]
        print(f"=== KIADÁSI ELLENŐR: {a.head} -> {a.base}, {res['commits']} commit ===")
        print(f"hozzáadva {len(s['added'])}, módosítva {len(s['modified'])}, törölve {len(s['deleted'])}")
        for k, lab in (("added", "+"), ("modified", "~"), ("deleted", "-")):
            for p in s[k][:40]:
                print(f"  {lab} {p}")
            if len(s[k]) > 40:
                print(f"  {lab} … és még {len(s[k]) - 40}")
        for r in res["warnings"]:
            print(f"[FIGYELMEZTETÉS] {r['rule']} {r['where']}: {r['msg']}")
        for r in res["stops"]:
            print(f"[MEGÁLLÍT] {r['rule']} {r['where']}: {r['msg']}")
        print(res["verdict"])
    return 1 if res["stops"] else 0


if __name__ == "__main__":
    sys.exit(main())
