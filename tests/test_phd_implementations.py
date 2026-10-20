"""Tests for the PhD-implementation pass (2026-10-20):

1. FallbackChain transient retry with backoff (B1 recipe)
2. Provider trace stats + suggested_order (OpenJarvis analyzer)
3. Recall Gate (isair) + Brain auto-recall injection
4. Memory consolidation: dedupe/promote/decay (Nocturne)
5. Observability spans (OTel data model, JSONL sink)
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.brain import Brain, FallbackChain, ToolDef
from jarvis.gate import GateDecision, Verdict
from jarvis.memory import Memory
from jarvis import observability as obs
from jarvis.recall_gate import content_words, should_enrich


# --------------------------------------------------------------------- fakes

class _FlakyProvider:
    """Fails with ConnectionError the first `fail_times` calls."""

    def __init__(self, name, fail_times=0, reply="ok"):
        self.name = name
        self.keys = []
        self.fail_times = fail_times
        self.reply = reply
        self.calls = 0

    def respond(self, message, key_index=0, timeout=5.0):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ConnectionError("packet dropped")
        return self.reply


class _DeadProvider:
    def __init__(self, name):
        self.name = name
        self.keys = []

    def respond(self, message, key_index=0, timeout=5.0):
        raise TimeoutError("never answers")


class FakeGate:
    def check(self, tool_name, args, turn_allowances):
        return GateDecision(verdict=Verdict.ALLOW, reason="test")

    @staticmethod
    def wrap_output(output, source, trust="untrusted"):
        return f'<tool_output source="{source}">{output}</tool_output>'


class FakeRule:
    def __init__(self, text):
        self.text = text


class FakeRules:
    def find(self, rule_id):
        texts = {"P2-1": "Persona: calm butler.", "P2-2": "Verify first."}
        return FakeRule(texts[rule_id]) if rule_id in texts else None


class FakeStore:
    def __init__(self):
        self.events = []
        self._n = 0

    def emit(self, session_id, type, payload, actor, trust="user",
             causal_parent=None, trace_id=None):
        self._n += 1
        self.events.append({"type": type, "payload": payload})
        return f"ev{self._n}"

    def get_events(self, session_id, limit=40):
        return self.events


class FakeMemory:
    def __init__(self, hits):
        self.hits = hits
        self.queries = []

    def recall(self, query, limit=5):
        self.queries.append(query)
        return self.hits[:limit]


# ------------------------------------------------------- 1+2: chain behavior

class TestChainRetryAndStats:
    def test_transient_failure_retried_once_then_succeeds(self):
        p = _FlakyProvider("flaky", fail_times=1, reply="hello")
        chain = FallbackChain([p], retry_backoff=0.0)
        res = chain.respond("hi")
        assert res["ok"] is True
        assert res["reply"] == "hello"
        outcomes = [a["outcome"] for a in res["attempts"]]
        assert outcomes == ["retry", "success"]
        assert p.calls == 2

    def test_transient_failure_exhausts_retries_then_falls_back(self):
        dead = _FlakyProvider("dead", fail_times=99)
        backup = _FlakyProvider("backup", reply="from backup")
        chain = FallbackChain([dead, backup], retry_backoff=0.0)
        res = chain.respond("hi")
        assert res["ok"] is True
        assert res["via"] == "backup"
        dead_outcomes = [a["outcome"] for a in res["attempts"]
                         if a["provider"] == "dead"]
        assert dead_outcomes == ["retry", "fallback"]
        assert dead.calls == 2  # 1 attempt + 1 retry, no more

    def test_no_retry_when_disabled(self):
        p = _FlakyProvider("flaky", fail_times=1)
        chain = FallbackChain([p], transient_retries=0, retry_backoff=0.0)
        res = chain.respond("hi")
        assert res["ok"] is False
        assert [a["outcome"] for a in res["attempts"]] == ["fallback"]

    def test_stats_and_suggested_order(self):
        bad = _DeadProvider("bad")
        good = _FlakyProvider("good", reply="fine")
        chain = FallbackChain([bad, good], retry_backoff=0.0)
        chain.respond("one")
        chain.respond("two")
        stats = chain.stats()
        assert stats["good"]["successes"] == 2
        assert stats["good"]["success_rate"] == 1.0
        assert stats["bad"]["successes"] == 0
        assert stats["bad"]["failures"] == 2
        # Data-driven order: the working provider is suggested first.
        assert chain.suggested_order()[0] == "good"


# ------------------------------------------------------------- 3: recall gate

class TestRecallGate:
    def test_content_words_drop_stopwords_en_and_hinglish(self):
        words = content_words("What is my name, mera naam kya hai?")
        assert "name" in words and "naam" in words
        assert "what" not in words and "kya" not in words

    def test_skip_when_window_covers_query(self):
        window = [{"role": "user", "content": "mera naam kya hai?"},
                  {"role": "assistant", "content": "Your name is Owais, sir."}]
        assert should_enrich("what is my name?", window) is False

    def test_enrich_when_window_empty_or_user_only(self):
        assert should_enrich("what is my name?", []) is True
        user_only = [{"role": "user", "content": "name name name"}]
        assert should_enrich("what is my name?", user_only) is True

    def test_enrich_for_uncovered_query(self):
        window = [{"role": "assistant", "content": "The weather is sunny."}]
        assert should_enrich("what is my passport number?", window) is True

    def test_fail_open_on_empty_query(self):
        assert should_enrich("", [{"role": "assistant", "content": "x"}]) is True


class TestBrainAutoRecall:
    def _brain(self, llm, memory=None):
        return Brain(gate=FakeGate(), session_store=FakeStore(),
                     rules=FakeRules(), llm_call=llm, tools=[],
                     memory=memory)

    def test_memory_facts_reach_the_prompt(self):
        seen = {}

        def llm(messages):
            seen["messages"] = messages
            return "Your name is Owais, sir."

        mem = FakeMemory([{"kind": "fact", "key": "user_name",
                           "snippet": "user_name: Owais",
                           "confidence": 0.95, "source": "user",
                           "quarantined": False}])
        brain = self._brain(llm, memory=mem)
        result = brain.respond("s1", "remind me, what is my name please?")
        assert result.status == "answered"
        joined = "\n".join(m.get("content") or "" for m in seen["messages"])
        assert "[Stored memory" in joined
        assert "user_name: Owais" in joined
        assert mem.queries  # recall was actually consulted

    def test_no_memory_means_no_injection_and_no_crash(self):
        def llm(messages):
            return "Certainly, sir."

        brain = self._brain(llm, memory=None)
        result = brain.respond("s1", "hello there, how are you?")
        assert result.status == "answered"

    def test_broken_memory_degrades_silently(self):
        class Boom:
            def recall(self, query, limit=5):
                raise RuntimeError("db on fire")

        def llm(messages):
            return "Still here, sir."

        brain = self._brain(llm, memory=Boom())
        result = brain.respond("s1", "hello there, how are you?")
        assert result.status == "answered"


# ------------------------------------------------------ 4: memory consolidation

@pytest.fixture()
def mem(tmp_path):
    m = Memory(tmp_path / "mem.db", profile_id="test")
    yield m
    m.close()


class TestConsolidation:
    def test_dedupe_merges_duplicate_live_rows(self, mem):
        mem.write_fact("city", "Pune", source="user", tier="user",
                       confidence=0.9)
        # Bypass the write gate (legacy/import path) to create a duplicate.
        with mem._lock:
            mem._conn.execute(
                "INSERT INTO facts (profile_id, key, value, confidence,"
                " source, provenance_tier, quarantined, created_ts)"
                " VALUES ('test', 'city', 'Pune', 0.8, 'import', 'user', 0,"
                " '2026-10-01T00:00:00+00:00')")
            mem._conn.commit()
        counts = mem.consolidate()
        assert counts["deduped"] == 1
        assert mem.get_fact("city")["value"] == "Pune"

    def test_promote_corroborated_quarantined_fact(self, mem):
        mem.write_fact("capital_hint", "Paris", source="site-a",
                       tier="web", confidence=0.4)
        with mem._lock:  # second independent source for the same claim
            mem._conn.execute(
                "INSERT INTO facts (profile_id, key, value, confidence,"
                " source, provenance_tier, quarantined, created_ts,"
                " superseded_by) VALUES ('test', 'capital_hint', 'Paris',"
                " 0.5, 'site-b', 'web', 1, '2026-10-02T00:00:00+00:00', NULL)")
            mem._conn.commit()
        counts = mem.consolidate()
        assert counts["promoted"] == 1
        hits = mem.recall("capital_hint")
        assert len(hits) == 1 and hits[0]["quarantined"] is False

    def test_decay_applies_with_elapsed_time(self, mem):
        mem.write_fact("old_pref", "tea", source="user", tier="user",
                       confidence=0.9)
        old = (datetime.now(timezone.utc) - timedelta(days=40)).strftime(
            "%Y-%m-%dT%H:%M:%S+00:00")
        with mem._lock:
            mem._conn.execute(
                "UPDATE facts SET created_ts = ?", (old,))
            mem._conn.commit()
        t0 = datetime.now(timezone.utc)
        first = mem.consolidate(now_iso=t0.isoformat())  # baseline run
        assert first["decayed"] == 0
        later = (t0 + timedelta(days=10)).isoformat()
        second = mem.consolidate(now_iso=later)
        assert second["decayed"] == 1
        conf = mem.get_fact("old_pref")["confidence"]
        assert conf == pytest.approx(0.9 * (0.98 ** 10), abs=0.01)

    def test_young_facts_never_decay(self, mem):
        mem.write_fact("fresh", "x", source="user", tier="user",
                       confidence=0.9)
        t0 = datetime.now(timezone.utc)
        mem.consolidate(now_iso=t0.isoformat())
        # 10 days later the fact is 10 days old (< 30-day decay floor).
        counts = mem.consolidate(
            now_iso=(t0 + timedelta(days=10)).isoformat())
        assert counts["decayed"] == 0
        assert mem.get_fact("fresh")["confidence"] == 0.9

    def test_consolidate_is_idempotent_when_nothing_to_do(self, mem):
        mem.write_fact("a", "1", source="user", tier="user", confidence=0.5)
        c1 = mem.consolidate()
        c2 = mem.consolidate()
        assert c1 == {"expired": 0, "deduped": 0, "promoted": 0, "decayed": 0}
        assert c2 == c1


# ------------------------------------------------------------ 5: observability

class TestObservability:
    def test_span_records_and_summary(self):
        rec = obs.SpanRecorder()
        with obs.span("model.call", recorder=rec, round=1):
            pass
        assert len(rec.spans) == 1
        s = rec.spans[0]
        assert s["name"] == "model.call"
        assert s["attrs"]["round"] == 1
        assert s["trace_id"]
        summary = rec.summary()
        assert summary["model.call"]["count"] == 1

    def test_nested_spans_link_parent_and_share_trace(self):
        rec = obs.SpanRecorder()
        obs.new_trace_id()
        with obs.span("turn", recorder=rec):
            with obs.span("memory.recall", recorder=rec):
                pass
        turn, inner = rec.spans[-1], rec.spans[0]
        assert inner["parent_id"] == turn["span_id"]
        assert inner["trace_id"] == turn["trace_id"]

    def test_span_marks_errors_and_propagates(self):
        rec = obs.SpanRecorder()
        with pytest.raises(ValueError):
            with obs.span("boom", recorder=rec):
                raise ValueError("bad")
        assert "ValueError" in rec.spans[0]["attrs"]["error"]

    def test_jsonl_sink_written(self, tmp_path):
        sink = tmp_path / "spans.jsonl"
        rec = obs.SpanRecorder(sink_path=sink)
        with obs.span("turn", recorder=rec):
            pass
        lines = sink.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["name"] == "turn"
