"""A media-noise munkafolyamat nem fogad el kódot a postaládából (inbox), és a bot csak az ATM-adatot írja a main-re."""
import re
from pathlib import Path

import yaml

WF = Path(__file__).resolve().parents[2] / ".github/workflows/media-noise.yml"


def _load():
    return yaml.safe_load(WF.read_text(encoding="utf-8"))


def test_nincs_postalada_lepes_es_inditas():
    text = WF.read_text(encoding="utf-8")
    assert "inbox" not in text.lower()
    d = _load()
    paths = d[True]["push"]["paths"]
    assert paths == ["config/user.json"]


def test_nincs_projektkibontas_es_base64_csomag():
    text = WF.read_text(encoding="utf-8")
    assert "base64 -d" not in text
    assert "tar xz" not in text
    names = [s.get("name", "") for s in _load()["jobs"]["build"]["steps"]]
    assert not any("kibont" in n.lower() or "postal" in n.lower() for n in names)


def test_a_bot_csak_az_atm_adatot_commitolja():
    text = WF.read_text(encoding="utf-8")
    adds = re.findall(r"^\s*git add (.+)$", text, flags=re.M)
    assert adds == ["data/metrics/atm_history.json"]
    assert len(re.findall(r"git push", text)) == 1
