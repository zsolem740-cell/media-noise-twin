#!/usr/bin/env python3
"""
Kontextus snapshot készítő a Media-Zaj projekthez.

Cél:
- Egyetlen (vagy részekre bontott), kulcs nélküli szöveges kontextuscsomag készítése.
- A CLAUDE.md korlátok előre kerülnek.
- A titkok maszkolva vannak (a maszkolás a csonkolás ELŐTT fut).
- Valódi adatmappák (data/, mentesek/, results/) kimaradnak.
- A snapshot nem kerül commitra (.gitignore).

Használat (a repó gyökeréből):
    python scripts/context_snapshot.py
    python scripts/context_snapshot.py --max-file-bytes 20000
    python scripts/context_snapshot.py --output context_snapshot.txt
    python scripts/context_snapshot.py --max-chars 120000   # részekre bontás: context_snapshot_part1.txt, _part2.txt, ...
"""

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "context_snapshot.txt"

IGNORE_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    "results",
    "node_modules",
    ".venv",
    "venv",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    "dist_releases",
    "data",        # hírmentés, címkék: valódi adat, nem forráskód
    "mentesek",    # szavazói exportok
}

IGNORE_FILES = {
    "context_snapshot.txt",
    "context_snapshot_part1.txt",
    "context_snapshot_part2.txt",
    ".env",
    ".env.local",
    ".env.production",
    ".DS_Store",
}

ALLOWED_EXTS = {
    ".py",
    ".md",
    ".ini",
    ".toml",
    ".json",
    ".html",
    ".js",
    ".css",
    ".yml",
    ".yaml",
    ".txt",
}

# Fájlonkénti alapértelmezett méretkorlát bájtban.
DEFAULT_MAX_FILE_BYTES = 40_000

# Titokminták. Az első kettő teljes egészében cserélődik; a hozzárendelés és a Bearer alakban csak az ÉRTÉK (a változónév és a szó marad olvasható).
FULL_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z\-_]{20,}"),
    re.compile(r"gsk_[0-9A-Za-z]{20,}"),
    re.compile(r"(?<![0-9A-Za-z\-])sk-[0-9A-Za-z\-_]{20,}"),
    re.compile(r"gh[pousr]_[0-9A-Za-z]{20,}"),
    re.compile(r"github_pat_[0-9A-Za-z_]{20,}"),
]
VALUE_PATTERNS = [
    re.compile(r"(?i)((?:api[_-]?key|token|password|passwd|secret)[A-Za-z0-9_]*\s*[:=]\s*['\"]?)[^'\"\s]{8,}"),
    re.compile(r"(?i)(bearer\s+)[0-9A-Za-z\-_\.=]{16,}"),
]
# Ennyi extra bájtot olvasunk a csonkolási határ után: a határon átnyúló kulcs így egészben megvan, és teljesen maszkolódik, mielőtt a szöveget levágjuk.
BOUNDARY_MARGIN = 1024

REDACTED = "[REDACTED_SECRET]"


def redact_secrets(text: str) -> str:
    """Maszkolja a felismerhető API-kulcsokat, tokeneket és jelszavakat (hozzárendelésnél csak az értéket)."""
    for pattern in FULL_PATTERNS:
        text = pattern.sub(REDACTED, text)
    for pattern in VALUE_PATTERNS:
        text = pattern.sub(lambda m: m.group(1) + REDACTED, text)
    return text


def is_ignored(path: Path) -> bool:
    """Igaz, ha a fájl vagy valamelyik szülőmappája kizárt."""
    if any(part in IGNORE_DIRS for part in path.parts):
        return True
    if path.name in IGNORE_FILES:
        return True
    if path.name == "CLAUDE.md":
        return False
    if path.name.startswith(".env") or path.name.startswith("context_snapshot"):
        return True
    if path.suffix.lower() not in ALLOWED_EXTS:
        return True
    return False


def read_limited(path: Path, max_bytes: int) -> tuple[str, bool]:
    """
    Beolvassa a fájlt legfeljebb max_bytes bájtig. A maszkolás a csonkolás ELŐTT fut:
    a határ után még BOUNDARY_MARGIN bájtot beolvasunk, azt is maszkoljuk, és csak utána vágjuk le a szöveget.
    Visszaadja a szöveget és azt, hogy csonkolva volt-e.
    """
    size = path.stat().st_size
    truncated = size > max_bytes
    with path.open("rb") as f:
        raw = f.read(max_bytes + BOUNDARY_MARGIN if truncated else size)
    text = redact_secrets(raw.decode("utf-8", errors="ignore"))
    if truncated:
        text = text.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")
        text += "\n\n[TRUNCATED_FOR_CONTEXT_SNAPSHOT]\n"
    return text, truncated


def build_manifest(files: list[Path], max_bytes: int) -> str:
    """Rövid, géppel is olvasható tartalomjegyzék a snapshot elejére."""
    lines = [
        "=== CONTEXT SNAPSHOT MANIFEST ===",
        f"ROOT: {ROOT.name}",
        f"MAX_FILE_BYTES: {max_bytes}",
        f"FILE_COUNT: {len(files)}",
        "",
        "FILES:",
    ]
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        size = path.stat().st_size
        marker = " [TRUNCATED]" if size > max_bytes else ""
        lines.append(f"- {rel} ({size} bytes){marker}")
    lines.append("")
    return "\n".join(lines)


def split_parts(text_sections: list[str], manifest: str, max_chars: int) -> list[str]:
    """Részekre bontás szakaszhatáron: egy rész legfeljebb max_chars karakter; az első rész a tartalomjegyzékkel kezdődik.
    Egy max_chars-nál hosszabb szakasz külön, darabolva kerül be."""
    pieces = [manifest + "\n"] + [sec + "\n" for sec in text_sections]
    parts: list[str] = []
    cur = ""
    for piece in pieces:
        while piece:
            if len(cur) + len(piece) <= max_chars:
                cur += piece
                piece = ""
            elif cur and len(piece) <= max_chars:           # új rész kezdődik a szakaszhatáron
                parts.append(cur)
                cur = ""
            else:                                           # a szakasz önmagában is hosszabb: kemény darabolás
                room = max_chars - len(cur)
                if room <= 0:
                    parts.append(cur)
                    cur = ""
                    continue
                cur += piece[:room]
                piece = piece[room:]
                parts.append(cur)
                cur = ""
    if cur:
        parts.append(cur)
    return parts


def build_snapshot(output_file: Path, max_file_bytes: int, max_chars: int = 0) -> list[Path]:
    """Összegyűjti az engedélyezett forrásfájlokat, és kiírja a snapshotot (max_chars > 0 esetén részekre bontva)."""
    sections: list[str] = []

    claude_md = ROOT / "CLAUDE.md"
    included_files: list[Path] = []

    # 1. A CLAUDE.md mindig legelöl van, hogy a korlátok először olvashatók legyenek.
    if claude_md.exists():
        content, truncated = read_limited(claude_md, max_file_bytes)
        sections.append(
            f"=== FILE: CLAUDE.md ===\n{content}\n"
        )
        included_files.append(claude_md)

    # 2. A többi engedélyezett forrásfájl.
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        if path == claude_md:
            continue
        if path == output_file or path.name.startswith(output_file.stem + "_part"):
            continue
        if is_ignored(path):
            continue

        rel_path = path.relative_to(ROOT).as_posix()
        content, truncated = read_limited(path, max_file_bytes)

        sections.append(
            f"=== FILE: {rel_path} ===\n{content}\n"
        )
        included_files.append(path)

    manifest = build_manifest(included_files, max_file_bytes)
    final_text = manifest + "\n" + "\n".join(sections)
    written: list[Path] = []

    if max_chars and len(final_text) > max_chars:
        for old in output_file.parent.glob(f"{output_file.stem}_part*{output_file.suffix}"):
            old.unlink()                                    # korábbi részek ne maradjanak félrevezetően
        for i, part in enumerate(split_parts(sections, manifest, max_chars), 1):
            target = output_file.with_name(f"{output_file.stem}_part{i}{output_file.suffix}")
            target.write_text(part, encoding="utf-8")
            written.append(target)
        if output_file.exists():
            output_file.unlink()                            # az egységes fájl ne maradjon a részek mellett
    else:
        for old in output_file.parent.glob(f"{output_file.stem}_part*{output_file.suffix}"):
            old.unlink()                                    # egyetlen fájl esetén a korábbi részek se maradjanak
        output_file.write_text(final_text, encoding="utf-8")
        written.append(output_file)

    total_chars = len(final_text)
    print(
        f"Kész: {', '.join(p.name for p in written)} "
        f"({len(included_files)} fájl, {total_chars} karakter, kulcsok szűrve)."
    )
    return written


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Kontextus snapshot készítő a Media-Zaj projekthez."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="A kimeneti snapshot fájl útvonala.",
    )
    parser.add_argument(
        "--max-file-bytes",
        type=int,
        default=DEFAULT_MAX_FILE_BYTES,
        help="Fájlonkénti maximális méret bájtban.",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=0,
        help="Ha a snapshot ennél hosszabb, részekre bontja (context_snapshot_part1.txt, ...). 0 = egyetlen fájl.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    build_snapshot(args.output, args.max_file_bytes, args.max_chars)
