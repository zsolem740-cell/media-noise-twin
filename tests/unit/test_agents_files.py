"""A `.claude/agents/` ügynökfájlok és a CLAUDE.md „Ügynökök” szakaszának ellenőrzése: csak olvasó eszközök, létező parancsok, a szakasz és a fájlok egyezése. Csak fájlokat olvas."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / ".claude" / "agents"
READ_ONLY = {"Read", "Grep", "Glob", "Bash"}
EXPECTED = {"kiadasi-ellenor", "kvotafigyelo", "elemzo", "telepites-ellenor", "kimeno-ellenor", "pilot-allapot"}


def parse(path):
    t = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", t, re.S)
    assert m, f"{path.name}: nincs frontmatter"
    meta = dict(l.split(":", 1) for l in m.group(1).splitlines() if ":" in l)
    return {k.strip(): v.strip() for k, v in meta.items()}, m.group(2)


def test_exactly_the_expected_agents_exist_with_matching_names_and_descriptions():
    files = {p.stem: p for p in AGENTS.glob("*.md")}
    assert set(files) == EXPECTED
    for stem, p in files.items():
        meta, body = parse(p)
        assert meta["name"] == stem and len(meta["description"]) > 40 and body.strip()


def test_every_agent_is_read_only_no_write_edit_network_or_subagent_tools():
    for p in AGENTS.glob("*.md"):
        meta, _ = parse(p)
        tools = {x.strip() for x in meta["tools"].split(",")}
        assert tools <= READ_ONLY, f"{p.name}: nem csak olvasó eszköz: {tools - READ_ONLY}"


def test_every_agent_states_it_only_reads_and_lists_what_is_forbidden():
    for p in AGENTS.glob("*.md"):
        _, body = parse(p)
        assert "olvas" in body.lower(), p.name
        assert "## Tilos" in body or "## Szabályok" in body, p.name
    assert "személyes adat" in parse(AGENTS / "elemzo.md")[1] and "CI" in parse(AGENTS / "elemzo.md")[1]
    assert "jóváhagyott kört" in parse(AGENTS / "kiadasi-ellenor.md")[1] and "Egyesíteni" in parse(AGENTS / "kiadasi-ellenor.md")[1]
    assert "visszaállás + 5 perc" in parse(AGENTS / "kvotafigyelo.md")[1] and "szolgáltatóváltás" in parse(AGENTS / "kvotafigyelo.md")[1]
    assert "ne töltsd fel" in parse(AGENTS / "telepites-ellenor.md")[1] and "Cloudflare-ba bármit írni" in parse(AGENTS / "telepites-ellenor.md")[1]
    kim = parse(AGENTS / "kimeno-ellenor.md")[1]
    assert "**tárolón kívül**" in kim and "Kiírni a talált" in kim and "ne küldd ki" in kim
    pa = parse(AGENTS / "pilot-allapot.md")[1]
    assert "csak betűk" in pa and "A lezárást, a feltöltést vagy az éles futást elindítani" in pa


def test_every_command_the_agents_run_points_to_an_existing_script_or_module():
    seen = 0
    for p in AGENTS.glob("*.md"):
        for cmd in re.findall(r"`(python3 [^`]+)`", p.read_text(encoding="utf-8")):
            parts = cmd.split()
            if parts[1] == "-m":
                target = ROOT / (parts[2].replace(".", "/") + ".py")
            else:
                target = ROOT / parts[1]
            assert target.exists(), f"{p.name}: nincs ilyen fájl: {target.relative_to(ROOT)}"
            seen += 1
    assert seen >= 6


def test_claude_md_agents_section_lists_every_agent_file_and_forbids_merging():
    t = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    sec = t.split("## Ügynökök", 1)[1].split("\n## ", 1)[0]
    for name in EXPECTED:
        assert name in sec, name
    assert "scripts/policy_guard.py" in sec and "Egyik sem egyesít" in sec and "PR-ben" in sec
