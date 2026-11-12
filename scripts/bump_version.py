#!/usr/bin/env python3
"""A verziószám egy helyről: a PROJECT_VERSION és a felület négy további helye együtt változik.

  python3 scripts/bump_version.py v47.10     mind az öt helyet átírja (a service worker gyorsítótár-neve eggyel nő)
  python3 scripts/bump_version.py --check    ellenőrzi, hogy a verzió mindenhol azonos (eltérésnél 1-gyel lép ki)

A README változásnaplóját nem írja: az kézi szöveg marad."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_RX = r"v\d+(?:\.\d+)*"

# (fájl, minta egy csoporttal a verzió előtt és egy utána) – mindegyiknek pontosan egyszer kell illeszkednie
TARGETS = [
    ("public/js/modules/diag.js", r"(export const APP_VERSION = ')" + VERSION_RX + r"(';)"),
    ("public/js/modules/audit.js", r"(export const AUDIT_VERSION = ')" + VERSION_RX + r"(';)"),
    ("public/index.html", r'(<div class="sub">)' + VERSION_RX + r"( )"),
]
SW = ("public/sw.js", r"(const V = 'mnt-v)(\d+)(';)")


class VersionError(Exception):
    pass


def _find(text, pattern, path):
    hits = list(re.finditer(pattern, text))
    if len(hits) != 1:
        raise VersionError(f"{path}: a verzió helye {len(hits)}-szor található (pontosan 1 kell)")
    return hits[0]


def read_versions(root=ROOT):
    """A verzió minden helyről: {fájl: verzió}."""
    root = Path(root)
    out = {"PROJECT_VERSION": (root / "PROJECT_VERSION").read_text(encoding="utf-8").strip()}
    for path, pattern in TARGETS:
        m = _find((root / path).read_text(encoding="utf-8"), pattern, path)
        out[path] = m.group(0)[len(m.group(1)):len(m.group(0)) - len(m.group(2))]
    _find((root / SW[0]).read_text(encoding="utf-8"), SW[1], SW[0])   # a gyorsítótár-névnek is meg kell lennie
    return out


def check(root=ROOT):
    """Üres lista, ha minden hely egyezik; különben a hibák szövege."""
    try:
        v = read_versions(root)
    except (VersionError, OSError) as e:
        return [str(e)]
    want = v["PROJECT_VERSION"]
    if not re.fullmatch(VERSION_RX, want):
        return [f"PROJECT_VERSION: érvénytelen verzió: {want!r}"]
    return [f"{path}: {got} (a PROJECT_VERSION szerint {want})" for path, got in v.items() if got != want]


def bump(new, root=ROOT):
    """Mind az öt helyet átírja; előbb mindent ellenőriz, csak utána ír."""
    root = Path(root)
    if not re.fullmatch(VERSION_RX, new):
        raise VersionError(f"érvénytelen verzió: {new!r} (példa: v47.10)")
    writes = {"PROJECT_VERSION": new + "\n"}
    for path, pattern in TARGETS:
        text = (root / path).read_text(encoding="utf-8")
        m = _find(text, pattern, path)
        writes[path] = text[:m.start()] + m.group(1) + new + m.group(2) + text[m.end():]
    text = (root / SW[0]).read_text(encoding="utf-8")
    m = _find(text, SW[1], SW[0])
    old = (root / "PROJECT_VERSION").read_text(encoding="utf-8").strip()
    n = int(m.group(2)) + (0 if new == old else 1)                    # ugyanarra a verzióra újrafuttatva nem lép tovább
    writes[SW[0]] = text[:m.start()] + m.group(1) + str(n) + m.group(3) + text[m.end():]
    for path, content in writes.items():
        (root / path).write_text(content, encoding="utf-8")
    return sorted(writes)


def main(argv):
    if len(argv) != 1 or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    if argv[0] == "--check":
        errors = check()
        for e in errors:
            print(f"verzió-eltérés: {e}", file=sys.stderr)
        if not errors:
            print(f"verzió rendben: {read_versions()['PROJECT_VERSION']}")
        return 1 if errors else 0
    try:
        changed = bump(argv[0])
    except (VersionError, OSError) as e:
        print(f"hiba: {e}", file=sys.stderr)
        return 1
    print(f"{argv[0]}: " + ", ".join(changed))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
