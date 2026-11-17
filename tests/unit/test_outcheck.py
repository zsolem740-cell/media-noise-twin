"""A Kimenő-ellenőr próbája: minden szabályhoz pozitív és negatív eset; a talált érték soha nem kerül a kimenetre. Csak fájlokat/szöveget olvas."""
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import outcheck as oc  # noqa: E402


def rules(res, level="hiba"):
    return {r["rule"] for r in res if r["level"] == level}


def test_clean_public_text_passes_and_a_news_title_with_age_only_warns():
    assert oc.check_text("t", "Közzétett nyilvános hírcím: Kamatot emelt a jegybank") == []
    res = oc.check_text("t", "Egy 52 éves férfi nyerte a lottót")
    assert rules(res) == set() and rules(res, "figyelmeztetés") == {"szemelyes-adat"} and len(res) == 2


def test_voter_export_markers_are_errors():
    for line in ('{"format": "mnt-backup", "version": 1}', "szavazatok-B.json", '"vote": "bait"', '"voter": "C"'):
        assert rules(oc.check_text("t", line)) == {"szavazoi-adat"}, line
    assert oc.check_text("t", "a szavazatok összesítése egyezést mutat") == []


def test_keys_are_errors_without_printing_the_value_and_placeholders_pass(capsys, tmp_path):
    key = "AIza" + "Q" * 30
    res = oc.check_text("t", f'k = "{key}"')
    assert rules(res) == {"titok"} and key not in str(res)
    assert oc.check_text("t", "api_key = 'YOUR_KEY_HERE'") == []
    f = tmp_path / "a.txt"
    f.write_text(f"token {key}\n", encoding="utf-8")
    assert oc.main([str(f)]) == 1 and key not in capsys.readouterr().out


def test_private_terms_file_blocks_matches_case_insensitively_and_never_prints_the_term(tmp_path, capsys):
    terms = tmp_path / "terms.txt"
    terms.write_text("# magánjegyzék\nTitkosNév Példa\n  \n58 éves nő\n", encoding="utf-8")
    msg = tmp_path / "m.txt"
    msg.write_text("Szia titkosnév példa itt volt\nsemmi\nA szavazó 58 ÉVES NŐ volt\n", encoding="utf-8")
    assert oc.main(["--terms", str(terms), str(msg)]) == 1
    out = capsys.readouterr().out
    assert "tiltott-szo" in out and ":1:" in out and ":3:" in out and "titkosnév" not in out.lower() and "58" not in out.replace("[HIBA]", "")
    assert oc.main([str(msg)]) == 0 and "figyelmeztetés".upper() in capsys.readouterr().out


def test_files_in_a_results_folder_are_errors_regardless_of_content(tmp_path, capsys):
    d = tmp_path / "results"
    d.mkdir()
    f = d / "x.txt"
    f.write_text("ártalmatlan", encoding="utf-8")
    assert oc.main([str(f)]) == 1 and "results-fajl" in capsys.readouterr().out
    assert oc.check_path("validation/hu_pilot/results/selection.json")[0]["rule"] == "results-fajl" and oc.check_path("docs/x.md") == []


def test_stdin_mode_and_exit_codes(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"vote": "fact"}'))
    assert oc.main(["--stdin"]) == 1
    monkeypatch.setattr(sys, "stdin", io.StringIO("rendben szöveg"))
    assert oc.main(["--stdin"]) == 0 and "TISZTA" in capsys.readouterr().out
    assert oc.main([str(tmp_path / "nincs.txt")]) == 2 and oc.main([]) == 2
