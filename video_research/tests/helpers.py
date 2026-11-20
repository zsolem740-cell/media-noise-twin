"""Tesztsegédek: forgatókönyves LLM-hamisító és számláló adapterburkoló. Nincs hálózat."""
import re

from video_research.llm import LLMResult
from video_research.adapters.fixture import FixtureAdapter

SEG = re.compile(r"^\[(?P<id>[^\]]+)\] (?P<text>.+)$", re.M)


class ScriptedLLM:
    provider, model, kind = "scripted-fake", "fake-model", "ai"
    """A kért átiratból szó szerinti idézetet emel ki (jó eset) + egy kitalált idézetet (amit a rendszernek el kell utasítania)."""
    def __init__(self, semantic="consistent", tokens=100, fail_after=None):
        self.calls, self.prompts, self.semantic, self.tokens, self.fail_after = 0, [], semantic, tokens, fail_after

    def complete_json(self, *, system, user, schema_name, max_tokens):
        self.calls += 1
        self.prompts.append((system, user))
        if self.fail_after is not None and self.calls > self.fail_after:
            raise RuntimeError("szimulált összeomlás")
        if schema_name == "semantic":
            return LLMResult({"verdict": self.semantic}, self.tokens)
        if schema_name == "plan":
            return LLMResult({"search_queries": ["android ai ügynök", "https://evil.example/x"]}, self.tokens)
        segs = list(SEG.finditer(user.split("<untrusted_transcript>", 1)[1].rsplit("</untrusted_transcript>", 1)[0]))
        findings = []
        for m in segs:
            t = m.group("text")
            if "AutoDroid" in t:
                findings.append({"category": "tool", "statement_hu": "Az AutoDroid a telefon felületét root nélkül vezérli.", "quotes": [{"segment_id": m.group("id"), "quote": t}], "relevance": "direct", "concrete": True})
            if "elakad" in t or "battery" in t:
                findings.append({"category": "warning", "statement_hu": "Problémát jeleztek: " + t[:30], "quotes": [{"segment_id": m.group("id"), "quote": t}], "relevance": "direct", "concrete": True})
        findings.append({"category": "claim", "statement_hu": "Kitalált állítás a videóról", "quotes": [{"segment_id": "x", "quote": "ez a mondat sosem hangzott el a videóban"}], "relevance": "direct", "concrete": True})
        return LLMResult({"findings": findings}, self.tokens)


class CountingAdapter:
    """Burkoló: számolja az indításokat; opcionálisan hibát szimulál."""
    def __init__(self, inner: FixtureAdapter, cost=0.01, start_error=None, cost_known=True, hang=False):
        self.inner, self.cost, self.start_error, self.cost_known, self.hang = inner, cost, start_error, cost_known, hang
        self.starts, self.aborts, self.is_fixture, self.name = [], [], inner.is_fixture, inner.name

    def supports(self, c, p): return self.inner.supports(c, p)
    def estimate_cost(self, c, p, u): return self.cost * u if self.cost_known else None
    def max_run_cost(self, c, p): return self.cost

    def start(self, c, p, params):
        if self.start_error:
            raise self.start_error
        self.starts.append((c.value, params.get("url") or params.get("query")))
        return self.inner.start(c, p, params)

    def poll(self, run_id):
        from video_research.adapters.base import RunState
        return RunState("running") if self.hang else RunState("succeeded", cost_usd=self.cost if self.cost_known else None)

    def abort(self, run_id):
        self.aborts.append(run_id)
        return True

    def results(self, c, p, run_id, params): return self.inner.results(c, p, run_id, params)
