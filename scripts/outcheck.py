"""Kimenő-ellenőr: mielőtt szöveg vagy fájl kimegy külső szolgáltatásnak (Perplexity, keresés, PR-szöveg, nyilvános oldal), megnézi, nincs-e benne, ami nem mehet ki a CLAUDE.md szerint:
szavazói adat (export, szavazat, betűhöz kötött személyes adat), API-kulcs vagy titok, a results/ tartalma. Csak olvas; a kimenetben soha nem szerepel a talált érték, csak a szabály és a sor száma.
Személyes adat (életkor, nem, név) általános mintával nem ismerhető fel megbízhatóan (hírcímekben is előfordul), ezért a felhasználó saját, a tárolón KÍVÜL tartott TILTOTT-SZAVAK fájlt adhat (--terms): ami abban szerepel, az hiba.
Parancssor: python3 scripts/outcheck.py [--terms FAJL] [--stdin] FÁJL...   (kilépési kód: 0 tiszta, 1 hiba, 2 nem olvasható)"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import policy_guard as pg  # noqa: E402

EXPORT_MARKERS = [
    (re.compile(r'"format"\s*:\s*"mnt-backup"'), "szavazói export (mnt-backup) tartalma"),
    (re.compile(r"szavazatok-[A-J]\.json"), "szavazói exportfájl neve"),
    (re.compile(r'"vote"\s*:\s*"(?:fact|mid|bait)"'), "szavazat (vote) rekord"),
    (re.compile(r'"voter"\s*:\s*"[A-J]"'), "szavazóbetűhöz kötött rekord"),
]
SOFT = [
    (re.compile(r"\b\d{1,2}\s*éves\b", re.I), "életkorra utaló szó (hírcím vagy szavazó?)"),
    (re.compile(r"\b(?:férfi|lány|fiú)\b", re.I), "nemre utaló szó (hírcím vagy szavazó?)"),
]


def finding(level, rule, where, msg):
    return {"level": level, "rule": rule, "where": where, "msg": msg}


def load_terms(path):
    if not path:
        return []
    return [l.strip().lower() for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip() and not l.lstrip().startswith("#")]


def check_text(name, text, terms=()):
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        where = f"{name}:{n}"
        for pat in pg.SECRET_RES:
            for m in pat.finditer(line):
                cand = m.group(1) if m.lastindex else m.group(0)
                if not any(h in cand.upper() for h in pg.PLACEHOLDERS):
                    out.append(finding("hiba", "titok", where, "kulcs- vagy titokszerű minta (az érték nincs kiírva)"))
                    break
        for pat, msg in EXPORT_MARKERS:
            if pat.search(line):
                out.append(finding("hiba", "szavazoi-adat", where, msg))
        low = line.lower()
        for t in terms:
            if t in low:
                out.append(finding("hiba", "tiltott-szo", where, "a felhasználó tiltott-szavak fájljában szereplő kifejezés (a kifejezés nincs kiírva)"))
        for pat, msg in SOFT:
            if pat.search(line):
                out.append(finding("figyelmeztetés", "szemelyes-adat", where, msg))
    return out


def check_path(path):
    p = str(path).replace("\\", "/")
    if "/results/" in "/" + p or p.startswith("results/"):
        return [finding("hiba", "results-fajl", p, "a results/ tartalma nem mehet ki")]
    return []


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--stdin", action="store_true")
    ap.add_argument("--terms")
    a = ap.parse_args(argv)
    try:
        terms = load_terms(a.terms)
        res = []
        if a.stdin:
            res += check_text("<stdin>", sys.stdin.read(), terms)
        for f in a.files:
            res += check_path(f)
            res += check_text(f, Path(f).read_text(encoding="utf-8", errors="replace"), terms)
    except (FileNotFoundError, OSError) as e:
        print(f"NEM OLVASHATÓ: {type(e).__name__}", file=sys.stderr)
        return 2
    if not a.files and not a.stdin:
        print("Nincs mit ellenőrizni: adj meg fájlt vagy --stdin-t.", file=sys.stderr)
        return 2
    errs = [r for r in res if r["level"] == "hiba"]
    for r in res:
        print(f"[{r['level'].upper()}] {r['rule']} {r['where']}: {r['msg']}")
    print("TISZTA" if not errs else f"{len(errs)} HIBA: ne küldd ki")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
