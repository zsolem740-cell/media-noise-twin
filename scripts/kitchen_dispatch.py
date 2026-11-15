import argparse
import hashlib
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE_DIR = ROOT / "dist_releases"
DEFAULT_VAULT_DIR = ROOT.parent / "mz_vault"

REQUIRED_WEB_FILES = {"index.html", "_headers", "manifest.json", "sw.js"}
ALLOWED_WEB_EXTS = {".html", ".js", ".css", ".json", ".svg", ".png", ".ico", ".txt", ".webmanifest"}


def run_expediter_gate(dry_run: bool = False) -> bool:
    """Minőségellenőrzés a kiadópult előtt: code_guard + offline pytest (dry-run módban is lefut)."""
    mode_tag = " [DRY-RUN]" if dry_run else ""
    if dry_run:
        print("[EXPEDITER DRY-RUN] Megjegyzés: a szárazfutás is lefuttatja a code_guard.py és az offline pytest ellenőrzést.")
    print(f"[EXPEDITER{mode_tag}] Konyhai minőségellenőrzés indítása...")
    code_guard = ROOT / "scripts" / "code_guard.py"
    if code_guard.exists():
        res_guard = subprocess.run([sys.executable, str(code_guard)], cwd=ROOT)
        if res_guard.returncode != 0:
            print(f"[EXPEDITER{mode_tag}] ELUTASÍTVA: A code_guard hibát talált!")
            return False

    res_test = subprocess.run(
        [sys.executable, "-m", "pytest", "-m", "not live_api"],
        cwd=ROOT,
    )
    if res_test.returncode not in (0, 5):
        print(f"[EXPEDITER{mode_tag}] ELUTASÍTVA: A tesztek elbuktak!")
        return False

    print(f"[EXPEDITER{mode_tag}] JÓVÁHAGYVA: Minden fogás tiszta, mehet a kiadásra.")
    return True


def package_release(stage_name: str, web_source_dir: Path, dry_run: bool = False) -> Path | None:
    """Összeállítja a Cloudflare Pages ZIP csomagot pontos gyökérstruktúrával."""
    if not web_source_dir.exists():
        raise FileNotFoundError(f"A webes forrásmappa nem található: {web_source_dir}")

    packed_files: list[Path] = []
    packed_names: set[str] = set()
    for item in sorted(web_source_dir.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(web_source_dir).as_posix()
        if item.name != "_headers" and item.suffix.lower() not in ALLOWED_WEB_EXTS:
            continue
        packed_files.append(item)
        packed_names.add(rel)

    missing = REQUIRED_WEB_FILES - packed_names
    if missing:
        raise RuntimeError(f"HIÁNYOS KIADÁS: A csomagból hiányoznak a kötelező gyökérfájlok: {sorted(missing)}")

    zip_path = RELEASE_DIR / f"mz_pilot_{stage_name}.zip"
    if dry_run:
        print(f"[KIADÓPULT DRY-RUN] Létrejönne: {zip_path} ({len(packed_files)} fájl)")
        return None

    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in packed_files:
            rel = item.relative_to(web_source_dir).as_posix()
            zf.write(item, arcname=rel)

    sha256 = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    print(f"[KIADÓPULT] Csomag kész: {zip_path.name} ({len(packed_files)} fájl)")
    print(f"[KIADÓPULT] SHA-256: {sha256}")
    return zip_path


def ensure_vault_outside_repo(vault_dir: Path) -> Path:
    """Ellenőrzi, hogy a mentési mappa garantáltan a Git-repón kívül helyezkedik el."""
    resolved_vault = vault_dir.resolve()
    resolved_root = ROOT.resolve()
    if resolved_vault == resolved_root or resolved_vault.is_relative_to(resolved_root):
        raise ValueError(
            f"BIZTONSÁGI HIBA: A --vault-dir ({resolved_vault}) nem lehet a repón belül ({resolved_root})!"
        )
    return resolved_vault


def backup_results_vault(vault_dir: Path, dry_run: bool = False) -> None:
    """A Gitből kizárt results/ mappa időbélyegzett mentése SHA-256 ellenőrző összeggel."""
    safe_vault = ensure_vault_outside_repo(vault_dir)
    results_dir = ROOT / "results"
    if not results_dir.exists() or not any(results_dir.iterdir()):
        print("[LOGISZTIKA] A results/ mappa üres vagy még nem létezik, nincs mit menteni.")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_base = safe_vault / f"results_backup_{stamp}"
    if dry_run:
        print(f"[LOGISZTIKA DRY-RUN] Mentés készülne ide: {archive_base}.zip")
        return

    safe_vault.mkdir(parents=True, exist_ok=True)
    archive_path = Path(shutil.make_archive(str(archive_base), "zip", root_dir=results_dir))
    sha256 = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    print(f"[LOGISZTIKA] Eredmények archiválva a páncélterembe: {archive_path}")
    print(f"[LOGISZTIKA] Backup SHA-256: {sha256}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Logisztikai, csomagoló és kiadási modul.")
    parser.add_argument("--stage", type=str, default="stage3", help="Kiadási szakasz neve (pl. stage2, stage3)")
    parser.add_argument("--web-dir", type=Path, default=ROOT / "web", help="A statikus webes fájlok forrásmappája")
    parser.add_argument("--vault-dir", type=Path, default=DEFAULT_VAULT_DIR, help="Repón kívüli mentési mappa")
    parser.add_argument("--backup-only", action="store_true", help="Csak a results/ mentését futtatja")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Szimuláció: lefuttatja a guardot és a teszteket, de nem ír kiadási vagy mentési fájlt lemezre",
    )
    args = parser.parse_args()

    if args.backup_only:
        try:
            backup_results_vault(args.vault_dir, dry_run=args.dry_run)
        except Exception as exc:
            print(f"[LOGISZTIKA] HIBA: {exc}")
            sys.exit(1)
        return

    if not run_expediter_gate(dry_run=args.dry_run):
        sys.exit(1)

    try:
        package_release(stage_name=args.stage, web_source_dir=args.web_dir, dry_run=args.dry_run)
        backup_results_vault(args.vault_dir, dry_run=args.dry_run)
    except Exception as exc:
        print(f"[KIADÓPULT] HIBA: {exc}")
        sys.exit(1)

    if args.dry_run:
        print("[SÉF DRY-RUN] A szimuláció sikeres, éles futtatáshoz hagyd el a --dry-run kapcsolót.")
    else:
        print("[SÉF] A rendelés kiadásra kész! Most már biztonságosan feltöltheted.")


if __name__ == "__main__":
    main()
