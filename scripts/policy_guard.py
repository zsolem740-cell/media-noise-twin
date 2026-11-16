"""Őr: csak olvasó szabályellenőrző a CLAUDE.md szigorú tiltásaihoz.

Nem módosít fájlt, nem hív hálózatot, nem olvas kulcsot. A tiszta függvények (`check_*`) bemenetet kapnak, így git nélkül tesztelhetők;
a `main` csak a git-állapotot gyűjti össze. Kilépési kód: 0 tiszta, 1 hiba, 2 a futtatás nem tudott ellenőrizni (pl. nincs alapág).
"""
import argparse
import fnmatch
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POLICY = ROOT / "config" / "guard_policy.json"
TEXT_SUFFIXES = {".py", ".json", ".md", ".txt", ".yml", ".yaml", ".js", ".html", ".sh", ".toml", ".ini", ".cfg"}
SECRET_RES = [
    re.compile(r"AIza[0-9A-Za-z\-_]{20,}"),
    re.compile(r"gsk_[0-9A-Za-z]{20,}"),
    re.compile(r"(?<![0-9A-Za-z])sk-[0-9A-Za-z\-_]{20,}"),
    re.compile(r"gh[pousr]_[0-9A-Za-z]{20,}"),
    re.compile(r"github_pat_[0-9A-Za-z_]{20,}"),
    re.compile(r"Bearer\s+[0-9A-Za-z\-_.=]{16,}", re.I),
    re.compile(r"(?i)\b(?:api_key|secret|token|password)\s*=\s*['\"]([^'\"]{8,})['\"]"),
]
PLACEHOLDERS = ("REDACTED", "DUMMY", "EXAMPLE", "PLACEHOLDER", "YOUR_", "CHANGEME", "XXXX", "CANARY", "FAKE", "TEST")
WEIGHT_RE = re.compile(r"(?i)weight|s[uú]lyoz")
WEIGHT_OK = re.compile(r"(?i)kappa_weighted|weighted\s*=\s*(?:True|False)|\bweighted=|ci95_weighted|\"kappa_weighted\"|quadratic|linear|if weighted else")


def finding(level, rule, where, msg):
    return {"level": level, "rule": rule, "where": where, "msg": msg}


def load_policy(path=POLICY):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def is_text(path):
    return Path(path).suffix.lower() in TEXT_SUFFIXES


def check_forbidden_paths(changes, policy):
    """results/ tartalmát nem szabad commitolni: bármely hozzáadott/módosított fájl ilyen mappában hiba (a .gitkeep kivétel)."""
    out = []
    for status, path in changes:
        if status.startswith("D") or path.endswith(".gitkeep"):
            continue
        for d in policy["forbidden_dirs_in_diff"]:
            if path.startswith(d) or f"/{d}" in f"/{path}":
                out.append(finding("hiba", "results-commit", path, "a results/ mappa tartalma nem kerülhet commitba"))
                break
    return out


def check_protected(changes, policy):
    """A v1/v2/v3 promptok fájljai nem módosulhatnak (a kiinduló ághoz képest sem módosítás, sem törlés, sem átnevezés)."""
    prot = set(policy["protected_paths"])
    return [finding("hiba", "protected-prompt", path, "védett prompt-fájl (v1/v2/v3): tilos módosítani") for status, path in changes if path in prot]


def check_pins(read_text, policy):
    out = []
    for path, pin in policy.get("pinned_sha256", {}).items():
        if pin is None:
            continue
        text = read_text(path)
        if text is None:
            out.append(finding("hiba", "pinned-prompt", path, "a rögzített hash fájlja hiányzik"))
        elif hashlib.sha256(text.encode("utf-8")).hexdigest() != pin:
            out.append(finding("hiba", "pinned-prompt", path, "a fájl hash-e eltér a rögzítettől"))
    return out


def check_secrets(files, read_text):
    out = []
    for path in files:
        if not is_text(path):
            continue
        text = read_text(path)
        if text is None:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for pat in SECRET_RES:
                for m in pat.finditer(line):
                    cand = m.group(1) if m.lastindex else m.group(0)
                    if not any(h in cand.upper() for h in PLACEHOLDERS):
                        out.append(finding("hiba", "secret", f"{path}:{n}", "kulcs- vagy titokszerű minta (az érték nincs kiírva)"))
                        break
    return out


def check_providers(files, read_text, policy):
    """Harmadik szolgáltató tilos: tiltott szolgáltató neve importban vagy hosztnévben."""
    out = []
    bad = policy["forbidden_providers"]
    imp = re.compile(r"^\s*(?:import|from)\s+(" + "|".join(map(re.escape, bad)) + r")\b", re.M)
    host = re.compile(r"https?://[^\s\"']*\b(" + "|".join(map(re.escape, bad)) + r")\b[^\s\"']*", re.I)
    for path in files:
        if not path.endswith((".py", ".json", ".yml", ".yaml")) or path.startswith(("scripts/policy_guard.py", "config/guard_policy.json")):
            continue
        if path.startswith("tests/") or "/tests/" in path:
            continue
        text = read_text(path)
        if text is None:
            continue
        for m in list(imp.finditer(text)) + list(host.finditer(text)):
            line = text.count("\n", 0, m.start()) + 1
            out.append(finding("hiba", "third-provider", f"{path}:{line}", f"nem engedélyezett szolgáltató: {m.group(1).lower()}"))
    return out


def check_live_endpoints(files, read_text, policy):
    """Valódi API-végpont neve csak a kijelölt átviteli fájlokban szerepelhet; máshol (pl. szkriptben) hiba. Tesztben is jelzés, mert tilos élő hívás."""
    out = []
    allowed = set(policy["live_endpoint_allowed_files"])
    for path in files:
        if not path.endswith((".py", ".yml", ".yaml", ".sh", ".js")) or path.startswith("config/guard_policy.json"):
            continue
        text = read_text(path)
        if text is None:
            continue
        for ep in policy["live_endpoints"]:
            if ep in text and path not in allowed and path != "scripts/policy_guard.py":
                lvl = "hiba" if not (path.startswith("tests/") or "/tests/" in path) else "figyelmeztetés"
                out.append(finding(lvl, "live-endpoint", path, f"valódi végpont ({ep}) nem engedélyezett fájlban"))
    return out


def _walk(obj, key=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v, key)
    else:
        yield key, obj


def check_title_counts(read_text, policy, config_paths):
    """250 vagy több címes futás tilos: a konfig darabszám-jellegű számai nem érhetik el a határt."""
    out = []
    limit = policy["max_titles_per_run"]
    keys = set(policy["title_count_keys"])
    for path in config_paths:
        text = read_text(path)
        if text is None:
            continue
        try:
            data = json.loads(text)
        except ValueError:
            continue
        for k, v in _walk(data):
            if k in keys and isinstance(v, int) and not isinstance(v, bool) and v > limit:
                out.append(finding("hiba", "title-limit", f"{path}:{k}", f"{v} > {limit}: 250 vagy több címes futás tilos"))
    return out


def check_weighting(files, read_text):
    """Súlyozás tilos az emberi referencián és a modellfuttatáson. A kappa 'weighted' változata statisztika, nem súlyozás: kivétel. Heurisztika, ezért csak figyelmeztetés."""
    out = []
    for path in files:
        if not path.endswith(".py") or "validation/hu_pilot/" not in path or "/tests/" in path:
            continue
        text = read_text(path)
        if text is None:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if WEIGHT_RE.search(line) and not WEIGHT_OK.search(line):
                out.append(finding("figyelmeztetés", "weighting", f"{path}:{n}", "súlyozásra utaló szó: ellenőrizd, hogy nem a szavazatokat vagy a címkéket súlyozza"))
    return out


def run_checks(changes, files, read_text, policy):
    cfgs = [p for p in files if p.endswith("config.json") and "hu_pilot" in p]
    res = []
    res += check_forbidden_paths(changes, policy)
    res += check_protected(changes, policy)
    res += check_pins(read_text, policy)
    res += check_secrets([p for _, p in changes if not _.startswith("D")] or files, read_text)
    res += check_providers(files, read_text, policy)
    res += check_live_endpoints(files, read_text, policy)
    res += check_title_counts(read_text, policy, cfgs)
    res += check_weighting(files, read_text)
    return res


def _git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, check=False)


def collect(base):
    d = _git("diff", "--name-status", "-M", f"{base}...HEAD")
    if d.returncode != 0:
        return None, None, d.stderr.strip()
    changes = []
    for line in d.stdout.splitlines():
        parts = line.split("\t")
        status = parts[0]
        for p in parts[1:]:
            changes.append((status, p))
    tracked = _git("ls-files").stdout.splitlines()
    return changes, tracked, ""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="origin/main", help="a kiinduló ág, amihez a változást mérjük")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    policy = load_policy()
    changes, tracked, err = collect(a.base)
    if changes is None:
        print(f"NEM ELLENŐRIZHETŐ: nincs alapág ({a.base}): {err}", file=sys.stderr)
        return 2
    tracked_leak = [("A", p) for p in tracked if check_forbidden_paths([("A", p)], policy)]
    reader = lambda p: (ROOT / p).read_text(encoding="utf-8", errors="replace") if (ROOT / p).is_file() else None
    res = run_checks(changes + tracked_leak, tracked, reader, policy)
    errors = [r for r in res if r["level"] == "hiba"]
    if a.json:
        print(json.dumps({"base": a.base, "changed": len(changes), "findings": res}, ensure_ascii=False, indent=1))
    else:
        print(f"=== ŐR: {len(changes)} változott fájl a(z) {a.base} óta, {len(tracked)} követett fájl ellenőrizve ===")
        for r in res:
            print(f"[{r['level'].upper()}] {r['rule']} {r['where']}: {r['msg']}")
        print("TISZTA" if not errors else f"{len(errors)} HIBA")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
