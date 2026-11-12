#!/usr/bin/env python3
"""A mobilos előnézet összeállítása egy önálló mappába (az éles public/ mappa nem változik).

  python3 preview/build.py KIMENETI_MAPPA            publikálható változat (az index.html csak tartalom, a keretet a közzététel adja)
  python3 preview/build.py KIMENETI_MAPPA --local    helyi próbához teljes HTML-lel

Az előnézet az éles alkalmazás tényleges kódját használja: az app.js és minden modul bájtra azonos a public/ mappa fájljaival,
három kivétellel (ezeket a build ellenőrzi és kiírja):
  - js/modules/uiRenderer.js: a mobilos megjelenítő (preview/uiRenderer.js)
  - js/modules/globe.js, globe3d.js: ugyanaz a kód, két ponton kibővítve (vak módban egyszínű, egyforma méretű pontok)
Adatként szintetikus hírlista kerül bele (preview/make_data.py); valódi hír, forrás vagy szavazat nem."""
import hashlib
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUB, PRE = ROOT / "public", ROOT / "preview"

# (fájl, régi szöveg, új szöveg): mindegyiknek pontosan egyszer kell szerepelnie az eredetiben
PATCHES = {
    "js/modules/globe.js": [
        ("const COLORS = { low: '#3ddc84', mid: '#ffb020', high: '#ff4d4d' };",
         "const COLORS = { get low() { return window.__mntNeutral ? '#a9b6c6' : '#3ddc84'; }, get mid() { return window.__mntNeutral ? '#a9b6c6' : '#ffb020'; }, get high() { return window.__mntNeutral ? '#a9b6c6' : '#ff4d4d'; } };"),
        ("  setPoints(p) { this.points = p; this.draw(); }",
         "  setPoints(p) { this.points = window.__mntPts ? window.__mntPts(p) : p; this.draw(); }"),
    ],
    "js/modules/globe3d.js": [
        ("const COLORS = { low: 0x3ddc84, mid: 0xffb020, high: 0xff4d4d };",
         "const COLORS = { get low() { return window.__mntNeutral ? 0xa9b6c6 : 0x3ddc84; }, get mid() { return window.__mntNeutral ? 0xa9b6c6 : 0xffb020; }, get high() { return window.__mntNeutral ? 0xa9b6c6 : 0xff4d4d; } };"),
        ("  setPoints(points) {\n    this.points = points;",
         "  setPoints(points) {\n    points = window.__mntPts ? window.__mntPts(points) : points;\n    this.points = points;"),
    ],
}
REPLACED = {"js/modules/uiRenderer.js": "preview/uiRenderer.js"}


class BuildError(Exception):
    pass


def sha16(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def check_base():
    """Az előnézeti megjelenítő melyik éles fájlra épül; ha az azóta változott, a build megáll."""
    head = (PRE / "uiRenderer.js").read_text(encoding="utf-8").splitlines()[:3]
    m = re.search(r"sha256\[:16\]=([0-9a-f]{16})", "\n".join(head))
    if not m:
        raise BuildError("preview/uiRenderer.js: hiányzik az alap hash a fejlécből")
    live = sha16(PUB / "js/modules/uiRenderer.js")
    if m.group(1) != live:
        raise BuildError(f"a public/js/modules/uiRenderer.js megváltozott ({live}), az előnézeti megjelenítő még a(z) {m.group(1)} változatra épül: nézd át, majd írd át a fejléc hashét")


def build(out, local=False, data=None):
    """Összeállítja a mappát; visszaadja a jelentést (azonos / módosított / előnézeti fájlok)."""
    out = Path(out)
    check_base()
    if out.exists():
        shutil.rmtree(out)
    (out / "js/modules").mkdir(parents=True)
    (out / "css").mkdir()
    report = {"identical": [], "patched": [], "replaced": [], "added": []}
    for src in sorted((PUB / "js").rglob("*.js")):
        rel = src.relative_to(PUB).as_posix()
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if rel in REPLACED:
            shutil.copyfile(ROOT / REPLACED[rel], dst)
            report["replaced"].append(rel)
        elif rel in PATCHES:
            text = src.read_text(encoding="utf-8")
            for old, new in PATCHES[rel]:
                if text.count(old) != 1:
                    raise BuildError(f"{rel}: a módosítandó hely {text.count(old)}-szor található (pontosan 1 kell): {old[:60]}")
                text = text.replace(old, new)
            dst.write_text(text, encoding="utf-8")
            report["patched"].append(rel)
        else:
            shutil.copyfile(src, dst)
            report["identical"].append(rel)
    shutil.copyfile(PUB / "css/main.css", out / "css/main.css")
    report["identical"].append("css/main.css")
    shutil.copyfile(PRE / "preview.css", out / "preview.css")
    shutil.copyfile(PRE / "guard.js", out / "guard.js")
    html = (PRE / "index.html").read_text(encoding="utf-8")
    if local:   # helyi próbához: ugyanaz a keret, amit a közzététel ad (doctype, kódolás, viewport)
        html = ('<!doctype html><html lang="hu"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"></head><body>' + html + "</body></html>")
    (out / "index.html").write_text(html, encoding="utf-8")
    if data:
        shutil.copyfile(data, out / "atm_history.json")
    else:
        sys.path.insert(0, str(ROOT))
        sys.path.insert(0, str(PRE))
        import make_data
        import json
        (out / "atm_history.json").write_text(json.dumps(make_data.build(), ensure_ascii=False), encoding="utf-8")
    report["added"] += ["index.html", "preview.css", "guard.js", "atm_history.json"]
    return report


def main(argv):
    local = "--local" in argv
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1:
        print(__doc__)
        return 2
    try:
        r = build(args[0], local)
    except BuildError as e:
        print(f"hiba: {e}", file=sys.stderr)
        return 1
    print(f"kész: {args[0]}")
    print(f"  bájtra azonos az éles fájllal: {len(r['identical'])} fájl (köztük js/app.js)")
    print(f"  kibővített: {', '.join(r['patched'])}")
    print(f"  előnézeti: {', '.join(r['replaced'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
