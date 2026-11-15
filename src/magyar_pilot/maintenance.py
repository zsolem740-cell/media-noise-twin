import argparse
import csv
import os
import re
import shutil
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = ROOT / "results"
LEDGER_FILE = RESULTS_DIR / "token_ledger.csv"

REQUIRED_FILES = [
    "CLAUDE.md",
    "docs/PILOT_RUNBOOK.md",
    "pytest.ini",
    "tests/conftest.py",
    ".gitignore",
]

REQUIRED_GITIGNORE_ENTRIES = [
    "results/",
    "context_snapshot.txt",
    "context_snapshot_part*.txt",
    "dist_releases/",
    ".env",
]
REQUIRED_ZIP_ROOT_FILES = {"index.html", "_headers", "manifest.json", "sw.js"}
MAX_ZIP_MEMBER_INSPECT_BYTES = 131_072  # 128 KB korlát ZIP-elem tartalomvizsgálathoz

SECRET_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z\-_]{20,}"),
    re.compile(r"gsk_[0-9A-Za-z]{20,}"),
    re.compile(r"(?<![0-9A-Za-z\-])sk-[0-9A-Za-z\-_]{20,}"),
    re.compile(r"gh[pousr]_[0-9A-Za-z]{20,}"),
    re.compile(r"github_pat_[0-9A-Za-z_]{20,}"),
    re.compile(r"Bearer\s+([0-9A-Za-z\-_.=]{16,})", re.IGNORECASE),
    re.compile(
        r"(?i)\b([A-Z0-9_]*(?:api_key|secret|token|password|passwd|private_key)[A-Z0-9_]*)\s*[:=]\s*(['\"])([^\s'\"#]{8,})\2"
    ),
]

PLACEHOLDER_HINTS = ("REDACTED", "DUMMY", "EXAMPLE", "PLACEHOLDER", "YOUR_", "CHANGEME", "XXXX", "FAKE")


def is_placeholder_match(matched_text: str) -> bool:
    upper_val = matched_text.upper()
    return any(hint in upper_val for hint in PLACEHOLDER_HINTS)


def extract_secret_candidate(match: re.Match[str]) -> str:
    """Az utolsó nem üres capture-csoportot adja vissza; csoport hiányában a teljes találatot."""
    non_empty_groups = [g for g in match.groups() if g]
    if non_empty_groups:
        return non_empty_groups[-1]
    return match.group(0)


def contains_secret(text: str) -> bool:
    """Match-szinten ellenőrzi a titkokat, így egy soron belüli placeholder nem fedi el a valós kulcsot."""
    for pat in SECRET_PATTERNS:
        for match in pat.finditer(text):
            candidate = extract_secret_candidate(match)
            if not is_placeholder_match(candidate):
                return True
    return False


def send_ntfy(topic: str, title: str, message: str, notify_enabled: bool = False, priority: str = "default") -> None:
    """Alapértelmezetten tiltott hálózati értesítés; csak explicit --notify kapcsolóval fut."""
    if not notify_enabled or not topic:
        return
    url = f"https://ntfy.sh/{topic.strip('/')}"
    req = urllib.request.Request(
        url,
        data=message.encode("utf-8"),
        headers={
            "Title": title.encode("utf-8"),
            "Priority": priority,
            "Tags": "wrench,shield",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception as exc:
        print(f"[FIGYELEM] ntfy értesítés sikertelen: {exc}")


def check_structure_and_gitignore() -> list[str]:
    """Ellenőrzi a kötelező fájlokat és a .gitignore védelmi szabályait."""
    issues: list[str] = []
    for rel in REQUIRED_FILES:
        if not (ROOT / rel).exists():
            issues.append(f"Hiányzó kötelező fájl: {rel}")

    gitignore = ROOT / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8", errors="ignore")
        for entry in REQUIRED_GITIGNORE_ENTRIES:
            if entry not in content:
                issues.append(f"Hiányzó .gitignore bejegyzés: {entry}")
    return issues


def scan_for_leaked_secrets() -> list[str]:
    """Átvizsgálja a forrásfájlokat véletlenül bent maradt API-kulcsok és hitelesítők után."""
    leaks: list[str] = []
    ignore_dirs = {".git", "__pycache__", ".pytest_cache", "results", "node_modules", ".venv", "dist_releases"}
    allowed_exts = {".py", ".md", ".js", ".html", ".json", ".yml", ".yaml", ".ini", ".toml"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in ignore_dirs for part in path.parts):
            continue
        if path.name.startswith(".env") or path.suffix.lower() not in allowed_exts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if contains_secret(text):
            leaks.append(f"Lehetséges API-kulcs vagy titok a fájlban: {path.relative_to(ROOT).as_posix()}")
    return leaks


def verify_zip_packages() -> dict[str, list[str]]:
    """Ellenőrzi a pilot .zip csomagokat; a méretkorlát miatt kihagyott elemeket külön kategóriába sorolja."""
    issues: list[str] = []
    skipped_for_size: list[str] = []

    zip_candidates = list(ROOT.glob("mz_pilot_*.zip"))
    release_dir = ROOT / "dist_releases"
    if release_dir.exists():
        zip_candidates.extend(release_dir.glob("mz_pilot_*.zip"))

    inspectable_exts = {".html", ".js", ".json", ".txt", ".py", ".md", ""}

    for zip_path in sorted(set(zip_candidates)):
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                infos = zf.infolist()
                names = {info.filename for info in infos}
                missing = REQUIRED_ZIP_ROOT_FILES - names
                if missing:
                    issues.append(f"{zip_path.name}: hiányzó gyökérfájlok ({', '.join(sorted(missing))})")

                for info in infos:
                    member = info.filename
                    member_path = Path(member)
                    if any(p == "results" for p in member_path.parts):
                        issues.append(f"{zip_path.name}: tiltott 'results/' mappa a csomagban ({member})")
                    if member_path.name.startswith(".env"):
                        issues.append(f"{zip_path.name}: tiltott '.env' fájl a csomagban ({member})")
                    if not member.endswith("/") and (
                        member_path.name == "_headers" or member_path.suffix.lower() in inspectable_exts
                    ):
                        if info.file_size > MAX_ZIP_MEMBER_INSPECT_BYTES:
                            skipped_for_size.append(
                                f"{zip_path.name}/{member} ({info.file_size} B > {MAX_ZIP_MEMBER_INSPECT_BYTES} B)"
                            )
                            continue
                        try:
                            raw = zf.read(member).decode("utf-8", errors="ignore")
                            if contains_secret(raw):
                                issues.append(f"{zip_path.name}: lehetséges titok/kulcs a csomagban ({member})")
                        except Exception as exc:
                            issues.append(f"{zip_path.name}: olvashatatlan elem ({member}: {exc})")
        except zipfile.BadZipFile:
            issues.append(f"{zip_path.name}: sérült ZIP archívum")

    return {"issues": issues, "skipped_for_size": skipped_for_size}


def clean_caches(apply: bool = False) -> list[str]:
    """Összegyűjti vagy törli a felesleges cache mappákat és ideiglenes snapshotokat."""
    targets: list[Path] = []
    for cache_dir in ROOT.rglob("*"):
        if cache_dir.is_dir() and cache_dir.name in {"__pycache__", ".pytest_cache"}:
            targets.append(cache_dir)

    snapshot = ROOT / "context_snapshot.txt"
    if snapshot.exists():
        targets.append(snapshot)
    targets.extend(sorted(ROOT.glob("context_snapshot_part*.txt")))

    actions: list[str] = []
    for target in targets:
        rel = target.relative_to(ROOT).as_posix()
        if apply:
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink(missing_ok=True)
            actions.append(f"Törölve: {rel}")
        else:
            actions.append(f"Törlésre jelölve (dry-run): {rel}")
    return actions


def check_token_watchdog(max_5h_tokens: int = 120_000, max_7d_tokens: int = 750_000) -> dict:
    """Kiértékeli az elmúlt 5 óra és az elmúlt 7 nap tokenfogyasztását a results/token_ledger.csv alapján."""
    if not LEDGER_FILE.exists():
        return {
            "status": "NO_LEDGER",
            "ledger_missing_reason": f"A naplófájl még nem létezik: {LEDGER_FILE.relative_to(ROOT).as_posix()}",
            "ledger_row_count": 0,
            "ledger_last_timestamp": None,
            "tokens_5h": 0,
            "limit_5h": max_5h_tokens,
            "tokens_7d": 0,
            "limit_7d": max_7d_tokens,
        }

    now = datetime.now(timezone.utc)
    cutoff_5h = now - timedelta(hours=5)
    cutoff_7d = now - timedelta(days=7)
    total_5h = 0
    total_7d = 0
    row_count = 0
    latest_ts: datetime | None = None

    with LEDGER_FILE.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_count += 1
            try:
                ts = datetime.fromisoformat(row["timestamp"])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if latest_ts is None or ts > latest_ts:
                    latest_ts = ts
                tokens = int(row.get("input_tokens", 0)) + int(row.get("output_tokens", 0))
                if ts >= cutoff_7d:
                    total_7d += tokens
                if ts >= cutoff_5h:
                    total_5h += tokens
            except (KeyError, ValueError):
                continue

    status = "WARNING" if (total_5h >= max_5h_tokens or total_7d >= max_7d_tokens) else "OK"
    return {
        "status": status,
        "ledger_missing_reason": None,
        "ledger_row_count": row_count,
        "ledger_last_timestamp": latest_ts.isoformat() if latest_ts else None,
        "tokens_5h": total_5h,
        "limit_5h": max_5h_tokens,
        "tokens_7d": total_7d,
        "limit_7d": max_7d_tokens,
    }


def run_maintenance(
    apply_clean: bool = False,
    max_5h_tokens: int = 120_000,
    max_7d_tokens: int = 750_000,
    notify: bool = False,
    ntfy_topic: str = "",
) -> int:
    print("=== MAGYAR_PILOT KARBANTARTÓI JELENTÉS ===")
    zip_report = verify_zip_packages()
    issues = check_structure_and_gitignore() + scan_for_leaked_secrets() + zip_report["issues"]
    skipped_for_size = zip_report["skipped_for_size"]
    clean_actions = clean_caches(apply=apply_clean)
    watchdog = check_token_watchdog(max_5h_tokens=max_5h_tokens, max_7d_tokens=max_7d_tokens)

    print(f"[1] Struktúra és biztonság: {len(issues)} eltérés")
    for item in issues:
        print(f"    - {item}")
    if skipped_for_size:
        print(f"    - Méretkorlát miatt átugrott ZIP-elemek (skipped_for_size): {len(skipped_for_size)}")
        for skipped in skipped_for_size:
            print(f"      * {skipped}")

    print(f"[2] Tisztítás ({'ÉLES' if apply_clean else 'DRY-RUN'}): {len(clean_actions)} elem")
    for act in clean_actions:
        print(f"    - {act}")

    print(
        f"[3] Token Watchdog (sorok: {watchdog['ledger_row_count']}, utolsó: {watchdog['ledger_last_timestamp'] or 'nincs'}): "
        f"5h = {watchdog['tokens_5h']} / {watchdog['limit_5h']} | "
        f"7d = {watchdog['tokens_7d']} / {watchdog['limit_7d']} [{watchdog['status']}]"
    )
    if watchdog.get("ledger_missing_reason"):
        print(f"    - Megjegyzés: {watchdog['ledger_missing_reason']}")

    if issues or watchdog["status"] == "WARNING":
        alert_lines = list(issues)
        if watchdog["tokens_5h"] >= watchdog["limit_5h"]:
            alert_lines.append(f"5h token küszöb elérve: {watchdog['tokens_5h']}/{watchdog['limit_5h']}")
        if watchdog["tokens_7d"] >= watchdog["limit_7d"]:
            alert_lines.append(f"7d heti token küszöb elérve: {watchdog['tokens_7d']}/{watchdog['limit_7d']}")

        send_ntfy(
            topic=ntfy_topic or os.getenv("NTFY_TOPIC", ""),
            title="Media-Zaj Karbantartó Riasztás",
            message="\n".join(alert_lines),
            notify_enabled=notify,
            priority="high",
        )
        return 1

    print("=== MINDEN RENDSZER RENDBEN ===")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Háttér-karbantartó, tisztító és felügyeleti modul.")
    parser.add_argument("--clean", action="store_true", help="Ténylegesen törli a cache-t és a régi snapshotokat.")
    parser.add_argument("--max-5h-tokens", type=int, default=120_000, help="5 órás figyelmeztetési tokenküszöb.")
    parser.add_argument("--max-7d-tokens", type=int, default=750_000, help="7 napos (heti) figyelmeztetési tokenküszöb.")
    parser.add_argument("--notify", action="store_true", help="Engedélyezi a kimenő ntfy riasztást (alapból tiltva).")
    parser.add_argument("--ntfy-topic", type=str, default="", help="Opcionális ntfy csatornanév riasztáshoz.")
    args = parser.parse_args()
    raise SystemExit(
        run_maintenance(
            apply_clean=args.clean,
            max_5h_tokens=args.max_5h_tokens,
            max_7d_tokens=args.max_7d_tokens,
            notify=args.notify,
            ntfy_topic=args.ntfy_topic,
        )
    )


if __name__ == "__main__":
    main()
