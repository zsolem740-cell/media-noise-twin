"""Az éles modellfuttatás réteg tesztjei: valódi HTTP-átvitel HELYI hamis szerverrel (127.0.0.1), a futtató parancs őrei, a futtatási csomag, a munkafolyamat.
Külső hálózati hívás nincs (a közös hálózati zár blokkolja); kulcsként csak mesterséges minta szerepel."""
import ast
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from validation.hu_pilot import bundle as B
from validation.hu_pilot import modelrun as mr
from validation.hu_pilot import run
from validation.hu_pilot.freeze import NotFrozen
from validation.hu_pilot.live import run_live as RL
from validation.hu_pilot.live.transport import HttpTransport
from .test_modelrun import CANARY, Clock, GEM, GRQ, DAY_DET, frozen, jl, ok_raw, post_of, quota_day  # noqa: F401
from .test_modelrun import err as err_raw

MOD = Path(mr.__file__).resolve().parent
REPO = MOD.parents[1]
UTC = __import__("datetime").timezone.utc
KEY = "AIzaSy" + "FAKELIVE" * 4                 # mesterséges, nem valódi kulcs


class Fake:
    """Helyi szerver: a kéréseket rögzíti, a választ egy függvény adja (provider, törzs, sorszám) -> (status, szöveg, fejlécek)."""
    def __init__(self, responder):
        self.calls, self.responder = [], responder
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(n).decode("utf-8"))
                outer.calls.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
                st, text, hdr = outer.responder(len(outer.calls), self.path, body)
                self.send_response(st)
                for k, v in (hdr or {}).items():
                    self.send_header(k, v)
                data = text.encode("utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


@pytest.fixture
def fake():
    made = []

    def mk(responder):
        f = Fake(responder)
        made.append(f)
        return f
    yield mk
    for f in made:
        f.close()


def provider_of(path):
    return "gemini" if "generateContent" in path else "groq"


def ok_for(n, path, body):
    p = provider_of(path)
    return 200, ok_raw(p, body).text, None


# ---------------------------------------------------------------- átvitel

def test_gemini_request_shape_key_only_in_header(fake, cfg):
    f = fake(lambda n, p, b: (200, "{}", None))
    tr = HttpTransport("gemini", KEY, 5, base_url=f.url)
    body = {"contents": [{"role": "user", "parts": [{"text": "<post>\nAlma körte szilva\n</post>"}]}]}
    raw = tr(GEM, body)
    c = f.calls[0]
    assert raw.status == 200 and c["path"] == f"/v1beta/models/{GEM}:generateContent" and c["headers"]["x-goog-api-key"] == KEY
    assert KEY not in c["path"] and c["body"] == body and "authorization" not in c["headers"]


def test_groq_request_shape_bearer_header(fake):
    f = fake(lambda n, p, b: (200, "{}", None))
    tr = HttpTransport("groq", KEY, 5, base_url=f.url)
    raw = tr(GRQ, {"model": GRQ, "messages": [{"role": "user", "content": "x"}]})
    c = f.calls[0]
    assert raw.status == 200 and c["path"] == "/openai/v1/chat/completions" and c["headers"]["authorization"] == "Bearer " + KEY and "x-goog-api-key" not in c["headers"]


def test_http_error_returns_status_text_and_retry_after(fake):
    f = fake(lambda n, p, b: (429, json.dumps({"error": {"message": "slow", "code": 429}}), {"Retry-After": "7"}))
    raw = HttpTransport("gemini", KEY, 5, base_url=f.url)(GEM, {})
    assert raw.status == 429 and raw.retry_after == "7" and "slow" in raw.text


def test_redirects_are_not_followed_so_the_key_never_reaches_another_host(fake):
    other = fake(lambda n, p, b: (200, "{}", None))
    f = fake(lambda n, p, b: (302, "", {"Location": other.url + "/steal"}))
    raw = HttpTransport("groq", KEY, 5, base_url=f.url)(GRQ, {})
    assert raw.status == 302 and other.calls == []


def test_timeout_and_connection_errors_map_to_the_runner_exceptions_without_the_key(fake):
    f = fake(lambda n, p, b: (time.sleep(1.0), (200, "{}", None))[1])
    with pytest.raises(mr.TransportTimeout) as e:
        HttpTransport("gemini", KEY, 0.2, base_url=f.url)(GEM, {})
    assert KEY not in str(e.value)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()          # biztosan zárt port
    with pytest.raises(ConnectionError) as e2:
        HttpTransport("gemini", KEY, 2, base_url=f"http://127.0.0.1:{port}")(GEM, {})
    assert KEY not in str(e2.value)


def test_transport_hides_the_key_and_refuses_bad_setup():
    tr = HttpTransport("groq", KEY, 5)
    assert KEY not in repr(tr) and "elrejtve" in repr(tr) and tr.base.startswith("https://")
    for bad in ("", "  ", None):
        with pytest.raises(ValueError):
            HttpTransport("gemini", bad, 5)
    with pytest.raises(ValueError):
        HttpTransport("openai", KEY, 5)


# ---------------------------------------------------------------- csomag

def test_bundle_needs_a_valid_freeze_and_holds_no_votes_or_reference(tmp_path, cfg, feed_path):
    from .test_hu_pilot import full_flow
    res, sel, exp = full_flow(tmp_path, cfg, feed_path)
    run.do_analyze(cfg, [exp], base=res)
    with pytest.raises(NotFrozen):
        run.do_export_bundle(cfg, base=res, path=tmp_path / "b.json")                 # lezárás előtt nincs csomag
    run.do_freeze(cfg, [exp], base=res)
    out = run.do_export_bundle(cfg, base=res, path=tmp_path / "b.json")
    text = (tmp_path / "b.json").read_text(encoding="utf-8")
    assert out["titles"] == 50 and out["gate"] == "atment"
    for banned in ("human_mean", "majority", "ordinal", "votes", "\"mids\"", "voter_profile"):
        assert banned not in text, banned
    assert B.load_bundle(tmp_path / "b.json", cfg)["freeze"]["gate"]["decision"] == "atment"
    with pytest.raises(FileExistsError):
        run.do_export_bundle(cfg, base=res, path=tmp_path / "b.json")


@pytest.fixture
def bundle_path(frozen, cfg, tmp_path):
    res, titles = frozen
    p = tmp_path / "bundle.json"
    B.write_bundle(B.build_bundle(res, cfg), p)
    return p


def test_bundle_tampering_is_detected(bundle_path, cfg, tmp_path):
    b = json.loads(bundle_path.read_text(encoding="utf-8"))
    b["titles"][0]["title"] += " x"
    bad = tmp_path / "bad.json"; bad.write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(B.BundleError, match="hash"):
        B.load_bundle(bad, cfg)
    b2 = json.loads(bundle_path.read_text(encoding="utf-8")); b2["freeze"]["gate"]["decision"] = "elbukott"; b2["sha256"] = B._hash(b2)
    bad2 = tmp_path / "bad2.json"; bad2.write_text(json.dumps(b2, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(NotFrozen):
        B.load_bundle(bad2, cfg)                                                       # a kaput elbukott: a hash rendben, mégsem fut
    b3 = json.loads(bundle_path.read_text(encoding="utf-8")); b3["votes"] = [1]; b3["sha256"] = B._hash(b3)
    bad3 = tmp_path / "bad3.json"; bad3.write_text(json.dumps(b3), encoding="utf-8")
    with pytest.raises(B.BundleError, match="tiltott mező"):
        B.load_bundle(bad3, cfg)


# ---------------------------------------------------------------- teljes futás valódi átvitellel, hamis szerverrel

def fast(clock):
    return dict(now=clock.now, sleep=clock.sleep, monotonic=clock.monotonic)


@pytest.mark.parametrize("provider,model", [("gemini", GEM), ("groq", GRQ)])
def test_full_run_over_real_http_to_a_local_server_with_no_freeze_files(fake, cfg, bundle_path, tmp_path, provider, model):
    f = fake(ok_for)
    b = B.load_bundle(bundle_path, cfg)
    out = tmp_path / "out"                                                              # itt nincs lezárási fájl és referencia: csak a csomag
    rep = RL.run(b, cfg, provider, model, KEY, out, "r1", base_url=f.url, **fast(Clock()))
    assert rep["status"] == "complete" and rep["n_ok"] == 50 and len(f.calls) == 50 and rep["failover_allowed"] is False and rep["providers_used"] == [provider]
    assert all(provider_of(c["path"]) == provider for c in f.calls) and [post_of(c["body"]) for c in f.calls] == [t["title"] for t in b["titles"]]
    blob = "".join(p.read_text(encoding="utf-8", errors="replace") for p in out.rglob("*") if p.is_file())
    assert KEY not in blob and CANARY not in blob
    for l in jl(out / "model_runs/r1/log.jsonl"):
        assert l["provider"] == provider and l["model_requested"] == model and l["outcome"] == "ok" and l["usage"]


def test_daily_quota_stop_and_resume_over_real_http_never_resends_done_titles(fake, cfg, bundle_path, tmp_path):
    state = {"stop_after": 7}

    def responder(n, path, body):
        if n == state["stop_after"] + 1:
            return 429, json.dumps({"error": {"code": 429, "message": "per day " + CANARY, "details": DAY_DET}}), None
        return ok_for(n, path, body)
    f = fake(responder)
    b, out = B.load_bundle(bundle_path, cfg), tmp_path / "out"
    r1 = RL.run(b, cfg, "gemini", GEM, KEY, out, "kv", base_url=f.url, **fast(Clock(__import__("datetime").datetime(2026, 11, 14, 10, 0, tzinfo=UTC))))
    assert r1["status"] == "stopped_quota" and r1["n_ok"] == 7 and r1["resume_after_utc"] == "2026-11-15T08:05:00Z"
    sent_first = {post_of(c["body"]) for c in f.calls[:7]}
    state["stop_after"] = 10 ** 6
    n_before = len(f.calls)
    r2 = RL.run(b, cfg, "gemini", GEM, KEY, out, "kv", base_url=f.url, **fast(Clock(__import__("datetime").datetime(2026, 11, 15, 8, 5, tzinfo=UTC))))
    assert r2["status"] == "complete" and r2["n_ok"] == 50
    assert not sent_first & {post_of(c["body"]) for c in f.calls[n_before:]} and len(f.calls) - n_before == 43
    assert CANARY not in "".join(p.read_text(encoding="utf-8", errors="replace") for p in out.rglob("*") if p.is_file())


def test_the_runner_itself_refuses_a_failed_gate_in_manifest_mode_and_calls_nothing(fake, cfg, bundle_path, tmp_path):
    f = fake(ok_for)
    b = B.load_bundle(bundle_path, cfg)
    for bad in ({**b["freeze"], "gate": {**b["freeze"]["gate"], "decision": "elbukott"}}, {**b["freeze"], "measured_ids": []}, {"gate": {}}):
        with pytest.raises(NotFrozen):
            tr = HttpTransport("gemini", KEY, 5, base_url=f.url)
            mr.run_measurement(b["titles"], "gemini", tr, cfg, tmp_path / "o", "r", GEM, manifest=bad)
    assert f.calls == []


# ---------------------------------------------------------------- a parancs őrei

def cli(args, monkeypatch, key=None, provider="gemini"):
    alias = {"gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY"}[provider]
    for a in ("GEMINI_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(a, raising=False)
    if key:
        monkeypatch.setenv(alias, key)
    return RL.main(args)


def base_args(bundle_path, tmp_path, provider="gemini", model=GEM, mode="check"):
    a = ["--provider", provider, "--bundle", str(bundle_path), "--out-dir", str(tmp_path / "o"), "--run-name", "r", "--mode", mode]
    return a + (["--model", model] if model else [])


def test_check_mode_uses_no_network_and_reports_key_presence(bundle_path, tmp_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("a check módban nincs hálózat")
    monkeypatch.setattr(socket.socket, "connect", boom)
    code = cli(base_args(bundle_path, tmp_path), monkeypatch, key=KEY)
    o = json.loads(capsys.readouterr().out)
    assert code == 0 and o["status"] == "OK" and o["n_requests"] == 50 and o["key_present"] is True and o["network_used"] is False and KEY not in json.dumps(o)
    assert cli(base_args(bundle_path, tmp_path), monkeypatch) == 0 and json.loads(capsys.readouterr().out)["key_present"] is False


@pytest.mark.parametrize("extra,why", [([], "nincs --live"), (["--live"], "nincs megerősítés"), (["--live", "--confirm", "igen"], "rossz megerősítés"), (["--confirm", "INDITSD"], "helyes megerősítés, de nincs --live")])
def test_run_mode_refuses_without_live_flag_and_confirmation(extra, why, bundle_path, tmp_path, monkeypatch, capsys):
    called = []
    monkeypatch.setattr(RL, "HttpTransport", lambda *a, **k: called.append(1))
    code = cli(base_args(bundle_path, tmp_path, mode="run") + extra, monkeypatch, key=KEY)
    assert code == 2 and not called and "ELUTASÍTVA" in capsys.readouterr().out, why


def test_run_mode_refuses_missing_key_missing_model_wrong_groq_model_and_a_tampered_bundle(bundle_path, tmp_path, monkeypatch, capsys):
    live = ["--live", "--confirm", RL.CONFIRM]
    assert cli(base_args(bundle_path, tmp_path, mode="run") + live, monkeypatch) == 2                              # nincs kulcs
    assert "GEMINI_API_KEY" in capsys.readouterr().out                                                              # a hibaüzenet a kulcs NEVÉT mondja, értékét soha
    assert cli(base_args(bundle_path, tmp_path, model="", mode="run") + live, monkeypatch, key=KEY) == 2          # Gemini modell nélkül
    assert cli(base_args(bundle_path, tmp_path, provider="groq", model="egy/mas-modell", mode="run") + live, monkeypatch, key=KEY, provider="groq") == 2
    b = json.loads(bundle_path.read_text(encoding="utf-8")); b["titles"][3]["title"] = "Más cím, mint amit lezártak"
    bad = tmp_path / "bad.json"; bad.write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
    assert cli(base_args(bad, tmp_path, mode="run") + live, monkeypatch, key=KEY) == 2
    assert KEY not in capsys.readouterr().out


def test_cli_end_to_end_prints_a_secret_free_summary_and_the_exit_code_tracks_the_status(fake, bundle_path, tmp_path, monkeypatch, capsys):
    f = fake(ok_for)
    real = HttpTransport
    monkeypatch.setattr(RL, "HttpTransport", lambda p, k, t, base_url=None: real(p, k, t, base_url=f.url))
    orig_run = RL.run                                                                  # a várakozást a teszt kiváltja (a valódi futás a konfigurált időközt tartja)
    monkeypatch.setattr(RL, "run", lambda *a, **k: orig_run(*a, **k, **fast(Clock())))
    code = cli(base_args(bundle_path, tmp_path, mode="run") + ["--live", "--confirm", RL.CONFIRM], monkeypatch, key=KEY)
    out = capsys.readouterr().out
    o = json.loads(out)
    assert code == 0 and o["status"] == "complete" and o["n_ok"] == 50 and KEY not in out and o["failover_allowed"] is False
    f2 = fake(lambda n, p, b: (429, json.dumps({"error": {"code": 429, "message": "per day", "details": DAY_DET}}), None))
    monkeypatch.setattr(RL, "HttpTransport", lambda p, k, t, base_url=None: real(p, k, t, base_url=f2.url))
    tmp2 = tmp_path / "x"; tmp2.mkdir()
    code2 = cli(base_args(bundle_path, tmp2, mode="run") + ["--live", "--confirm", RL.CONFIRM], monkeypatch, key=KEY)
    assert code2 == 3 and json.loads(capsys.readouterr().out)["status"] == "stopped_quota"


# ---------------------------------------------------------------- elkülönítés és munkafolyamat

def imports_of(path):
    names = []
    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Import):
            names += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom) and not n.level:
            names.append(n.module or "")
    return {x.split(".")[0] for x in names}


def test_network_and_environment_code_exist_only_in_the_live_package():
    net = {"urllib", "http", "socket", "requests", "httpx", "ssl"}
    for f in MOD.glob("*.py"):                                                       # a pilot többi modulja hálózatmentes és környezetmentes marad
        assert not imports_of(f) & (net | {"os", "subprocess"}), f.name
        assert "live" not in imports_of(f) and "validation.hu_pilot.live" not in f.read_text(encoding="utf-8"), f.name
    assert imports_of(MOD / "live/transport.py") & {"urllib", "socket"}
    for f in (MOD / "live").glob("*.py"):
        assert "subprocess" not in imports_of(f) and not imports_of(f) & {"requests", "httpx", "anthropic", "openai", "google"}, f.name
    assert not imports_of(MOD / "live/run_live.py") & net                            # a futtató maga nem hív hálózatot, csak az átvitelt
    for f in (MOD / "live").glob("*.py"):
        for line in f.read_text(encoding="utf-8").splitlines():
            assert not ("print(" in line and "key" in line.lower().replace("key_alias", "").replace("key_present", "")), (f.name, line)


def test_workflow_is_manual_only_check_by_default_and_never_writes_to_the_repo():
    y = yaml.safe_load((REPO / ".github/workflows/pilot-model-run.yml").read_text(encoding="utf-8"))
    on = y.get("on", y.get(True))
    assert list(on) == ["workflow_dispatch"]                                           # nincs ütemezés, nincs push-indítás
    ins = on["workflow_dispatch"]["inputs"]
    assert ins["mode"]["default"] == "check" and set(ins["provider"]["options"]) == {"gemini", "groq"} and {"confirm", "model", "run_name", "resume_run_id"} <= set(ins)
    assert y["permissions"] == {"contents": "read", "actions": "read"}
    text = (REPO / ".github/workflows/pilot-model-run.yml").read_text(encoding="utf-8")
    assert "git push" not in text and "git commit" not in text and "contents: write" not in text
    steps = y["jobs"]["run"]["steps"]
    live = [s for s in steps if "--live" in s.get("run", "")]
    assert len(live) == 1 and live[0]["if"].replace(" ", "") == "${{inputs.mode=='run'}}"
    for s in steps:                                                                    # a titkok csak env-ben, soha parancssorban; a bemenetek env-en át, nem a parancsba illesztve
        assert "secrets." not in s.get("run", "") and "inputs." not in s.get("run", "")
    up = [s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact")][0]
    assert up["with"]["retention-days"] == 14 and up["if"].replace(" ", "") == "${{always()}}"
    assert y["jobs"]["run"]["timeout-minutes"] <= 180
