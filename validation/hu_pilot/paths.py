"""Elkülönítés: a pilot a beállított hírmentést csak olvassa, és kizárólag a saját results/ mappájába ír."""
import json
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
REPO_ROOT = MODULE_DIR.parents[1]


class IsolationError(Exception):
    pass


def load_config(path=None):
    return json.loads((Path(path) if path else MODULE_DIR / "config.json").read_text(encoding="utf-8"))


def inside(path, base):
    try:
        Path(path).resolve().relative_to(Path(base).resolve())
        return True
    except ValueError:
        return False


def results_dir(cfg, base=None):
    return Path(base) if base else MODULE_DIR / cfg["results_dir"]


def check_write(path, rdir):
    p = Path(path).resolve()
    if not inside(p, rdir):
        raise IsolationError(f"az írás csak az eredménytárba engedett ({Path(rdir).resolve()}): {p}")
    return p
