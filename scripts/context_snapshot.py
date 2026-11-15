#!/usr/bin/env python3
"""
Kontextus snapshot készítő a Media-Zaj projekthez.

Cél:
- Egyetlen, kulcs nélküli szöveges kontextuscsomag készítése.
- A CLAUDE.md korlátok előre kerülnek.
- A titkok maszkolva vannak.
- A snapshot nem kerül commitra.

Használat:
    python context_snapshot.py
    python context_snapshot.py --max-chars 120000
    python context_snapshot.py --output context_snapshot.txt
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

# Titokminták: Gemini, Groq, általános API-kulcs/token/jelszó formák.
SECRET_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z\-_]{20,}"),
    re.compile(r"gsk_[0-9A-Za-z]{20,}"),
    re.compile(r"sk-[0-9A-Za-z\-_]{20,}"),
    re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*['\"]?[^'\"\s]{8,}"),
    re.compile(r"(?i)bearer\s+[0-9A-Za-z\-_\.]{20,}"),
]

REDACTED = "[REDACTED_SECRET]"


def redact_secrets(text: str) -> str:
    """Maszkolja a felismerhető API-kulcsokat, tokeneket és jelszavakat."""
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
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
    Beolvassa a fájlt, de legfeljebb max_bytes bájtig.
    Visszaadja a szöveget és azt, hogy csonkolva volt-e.
    """
    size = path.stat().st_size
    truncated = size > max_bytes

    if truncated:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            content = f.read(max_bytes)
        content += "\n\n[TRUNCATED_FOR_CONTEXT_SNAPSHOT]\n"
    else:
        content = path.read_text(encoding="utf-8", errors="ignore")

    return redact_secrets(content), truncated


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


def build_snapshot(output_file: Path, max_file_bytes: int) -> None:
    """Összegyűjti az engedélyezett forrásfájlokat, és kiírja a snapshotot."""
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
        if path == output_file:
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

    output_file.write_text(final_text, encoding="utf-8")

    total_chars = len(final_text)
    print(
        f"Kész: {output_file.name} "
        f"({len(included_files)} fájl, {total_chars} karakter, kulcsok szűrve)."
    )


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
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    build_snapshot(args.output, args.max_file_bytes)
