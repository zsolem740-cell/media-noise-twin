"""A kódellenőr (scripts/code_guard.py) lefedettségének próbája a kereskedelmi modell mappájára: hálózat, git és valódi kulcs nélkül, kizárólag ideiglenes hamis fájlokkal."""
import configparser
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import code_guard as cg  # noqa: E402


def analyze(tmp_path, monkeypatch, rel, source):
    monkeypatch.setattr(cg, "ROOT", tmp_path)
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return cg.analyze_python_file(path)


def test_scan_dirs_cover_the_trading_model_folder_and_the_original_ones():
    names = {p.name for p in cg.SCAN_DIRS}
    assert {"src", "tests", "scripts", "trading_model"} <= names


def test_forbidden_network_imports_are_errors_in_trading_model_tests(tmp_path, monkeypatch):
    for module in ("requests", "urllib.request", "subprocess", "openai", "anthropic"):
        errors = analyze(tmp_path, monkeypatch, "trading_model/tests/test_x.py", f"import {module}\n")
        assert any("TILTOTT IMPORT" in e for e in errors), module
    errors = analyze(tmp_path, monkeypatch, "trading_model/tests/test_x.py", "from urllib import request\n")
    assert any("TILTOTT IMPORT" in e for e in errors)


def test_socket_import_is_allowed_only_in_the_two_named_guard_files(tmp_path, monkeypatch):
    assert analyze(tmp_path, monkeypatch, "trading_model/tests/test_network_guard.py", "import socket\n") == []
    assert analyze(tmp_path, monkeypatch, "tests/conftest.py", "import socket\n") == []
    other = analyze(tmp_path, monkeypatch, "trading_model/tests/test_other.py", "import socket\n")
    assert any("TILTOTT IMPORT" in e and "socket" in e for e in other)
    unit = analyze(tmp_path, monkeypatch, "tests/unit/test_other.py", "import socket\n")
    assert any("TILTOTT IMPORT" in e for e in unit)


def test_generic_rules_apply_to_trading_model_code_files_too(tmp_path, monkeypatch):
    assert any("VESZÉLYES HÍVÁS" in e for e in analyze(tmp_path, monkeypatch, "trading_model/data.py", "eval('1')\n"))
    assert any("Üres 'except:'" in e for e in analyze(tmp_path, monkeypatch, "trading_model/gate.py", "try:\n    pass\nexcept:\n    pass\n"))
    secret = "gsk_" + "A1b2C3d4E5f6G7h8I9j0K1l2"
    assert any("BIZTONSÁGI HIBA" in e for e in analyze(tmp_path, monkeypatch, "trading_model/synthetic.py", f'KEY = "{secret}"\n'))
    assert analyze(tmp_path, monkeypatch, "trading_model/data.py", "import json\nX = 1\n") == []


def test_the_real_trading_model_tree_passes_the_guard():
    errors = []
    for py in sorted((REPO / "trading_model").rglob("*.py")):
        errors.extend(cg.analyze_python_file(py))
    assert errors == []


def test_pytest_ini_collects_the_trading_model_tests_by_default():
    cfg = configparser.ConfigParser()
    cfg.read(REPO / "pytest.ini", encoding="utf-8")
    assert "trading_model/tests" in cfg["pytest"]["testpaths"].split()
