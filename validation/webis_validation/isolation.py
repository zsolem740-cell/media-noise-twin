"""Elkülönítési őrök: a Webis-validáció csak a saját data/ mappájából olvas és csak a saját results/ mappájába ír.
A fő mérési állapothoz (data/metrics, public, inbox, config, src) nem nyúl, és nem keveredik a magyar adatokkal."""
import json
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
REPO_ROOT = MODULE_DIR.parents[1]
FORBIDDEN_DIRS = [REPO_ROOT / d for d in ("data", "public", "inbox", "config", "src", "scripts")]
HU_ONLY_CHARS = "őűŐŰ"      # csak a magyarban fordulnak elő: az angol Webis-adatban ezek jelenléte hibára utal


class IsolationError(Exception):
    pass


def _inside(path, base):
    try:
        Path(path).resolve().relative_to(Path(base).resolve())
        return True
    except ValueError:
        return False


def load_config(path=None):
    path = Path(path) if path else MODULE_DIR / "config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    if cfg.get("mode") != "benchmark_readonly":
        raise IsolationError(f"a mód csak benchmark_readonly lehet, nem: {cfg.get('mode')!r}")
    if cfg.get("source") != "webis-clickbait-17" or cfg.get("language") != "en":
        raise IsolationError("a modul csak a webis-clickbait-17 angol adatát kezeli")
    return cfg


def check_read(path, data_dir):
    """Olvasás csak a modul adatmappájából; a fő adattárból és a kódmappákból soha."""
    p = Path(path).resolve()
    if any(_inside(p, f) for f in FORBIDDEN_DIRS) and not _inside(p, MODULE_DIR):
        raise IsolationError(f"a fő adattárból nem olvasunk: {p}")
    if not _inside(p, data_dir):
        raise IsolationError(f"az olvasás csak a validáció adatmappájából engedett ({Path(data_dir).resolve()}): {p}")
    return p


def check_write(path, results_dir):
    """Írás csak a modul eredménytárába."""
    p = Path(path).resolve()
    if not _inside(p, results_dir):
        raise IsolationError(f"az írás csak az eredménytárba engedett ({Path(results_dir).resolve()}): {p}")
    return p


def has_hungarian_chars(text):
    return any(c in HU_ONLY_CHARS for c in str(text))
