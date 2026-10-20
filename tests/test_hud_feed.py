"""HUD live feed (Team 4 steals) — pure-logic tests, fully headless.

EventFeed / pill_state / dim_color live in jarvis.chat_gui but are pure
Python: importing the module needs no display (only ChatWindow touches
Tk). Test events mirror SessionStore.get_events() dicts exactly.

Rendering table under test (event type -> feed line):
  user.message        -> (no line; activity -> thinking)
  capnet.plan         -> "Plan: use <tool> — <reason>"
  tool.call allow     -> "<Action>…"            e.g. "Searching the web…"
  tool.call approved  -> "<Action> (approved)"  e.g. "Opening Notepad (approved)"
  tool.call deny      -> "Blocked by the gate: <tool> (<reason>)"
  tool.call approval  -> "Waiting for your approval: <tool>"
  approval.requested -> "Approval requested: <tool> — nothing runs…"
  tool.result ok      -> "✓ <tool> done"
  tool.result knowl.  -> "Looked up: <note.md> (+N more)"
  tool.result failed  -> "✗ <tool> failed: <error>"
  tool.result postc.  -> "Delivery check failed: <tool> (…) — not done"
  brain.reply         -> (no line; activity -> idle)
  recovery.escalated  -> "Recovery: <summary>"
  voice.stage speak.  -> (no line; activity -> speaking)
"""

from __future__ import annotations

import json

import pytest

from jarvis.chat_gui import FEED_MAX_LINES, EventFeed, dim_color, pill_state


def ev(seq, type_, payload=None, event_id=None, parent=None):
    return {"event_id": event_id or f"e{seq}", "session_id": "s1",
            "seq": seq, "trace_id": "t", "ts": "2026-10-20T00:00:00Z",
            "type": type_, "causal_parent": parent, "actor": "brain",
            "trust": "system", "payload": payload or {}}


def call(seq, tool, verdict="allow", args=None, event_id=None):
    return ev(seq, "tool.call",
              {"tool": tool, "args": args or {}, "gate_verdict": verdict},
              event_id=event_id)


def result(seq, parent, payload):
    return ev(seq, "tool.result", payload, parent=parent)


# --------------------------------------------------------------------------- #
# tool.call rendering + gate verdicts
# --------------------------------------------------------------------------- #

def test_call_allow_renders_action_line():
    feed = EventFeed()
    out = feed.consume([call(1, "web_search", args={"query": "news"})])
    assert out == ["Searching the web…"]
    assert feed.activity == "tool"


def test_call_launch_app_allow_with_undo_is_approved():
    feed = EventFeed()
    out = feed.consume([call(1, "pc.launch_app", verdict="allow_with_undo",
                             args={"app": "Notepad"})])
    assert out == ["Opening Notepad (approved)"]


def test_call_launch_app_plain_allow_keeps_ellipsis():
    feed = EventFeed()
    out = feed.consume([call(1, "launch_app", args={"name": "Calc"})])
    assert out == ["Opening Calc…"]


def test_call_unknown_tool_falls_back_to_running():
    feed = EventFeed()
    assert feed.consume([call(1, "mystery_tool")]) == ["Running mystery_tool…"]


def test_call_deny_names_tool_and_reason():
    feed = EventFeed()
    out = feed.consume([ev(1, "tool.call",
                           {"tool": "code_run", "args": {},
                            "gate_verdict": "deny",
                            "reason": "tier-3 needs approval"})])
    assert out == ["Blocked by the gate: code_run (tier-3 needs approval)"]
    assert feed.activity == "thinking"


def test_call_require_approval_waits():
    feed = EventFeed()
    out = feed.consume([call(1, "code_write", verdict="require_approval")])
    assert out == ["Waiting for your approval: code_write"]
    assert feed.activity == "approval"


def test_approval_requested_event_line():
    feed = EventFeed()
    out = feed.consume([ev(1, "approval.requested",
                           {"action": "code_write", "args": {}})])
    assert out == ["Approval requested: code_write — "
                   "nothing runs until you approve"]
    assert feed.activity == "approval"


# --------------------------------------------------------------------------- #
# capnet.plan
# --------------------------------------------------------------------------- #

def test_plan_line_names_tool_and_reason():
    feed = EventFeed()
    out = feed.consume([ev(1, "capnet.plan",
                           {"task": "search x", "chosen": "tool:web_search",
                            "reason": "chose tool:web_search — you named it",
                            "via": "capnet"})])
    assert out == ["Plan: use web_search — you named it"]


def test_plan_without_choice_renders_nothing():
    feed = EventFeed()
    out = feed.consume([ev(1, "capnet.plan",
                           {"task": "chat", "chosen": None, "reason": ""})])
    assert out == []


# --------------------------------------------------------------------------- #
# tool.result rendering
# --------------------------------------------------------------------------- #

def test_result_ok_generic():
    feed = EventFeed()
    feed.consume([call(1, "web_search", event_id="c1")])
    out = feed.consume([result(2, "c1", {"ok": True, "output": "..."})])
    assert out == ["✓ web_search done"]
    assert feed.activity == "thinking"


def test_result_failure_with_error_field():
    feed = EventFeed()
    feed.consume([call(1, "web_search", event_id="c1")])
    out = feed.consume([result(2, "c1", {"ok": False, "error": "dns boom"})])
    assert out == ["✗ web_search failed: dns boom"]


def test_result_failure_error_in_output():
    # Brain attempt results carry the failure text in `output`, not `error`.
    feed = EventFeed()
    feed.consume([call(1, "code_run", event_id="c1")])
    out = feed.consume([result(2, "c1", {"ok": False, "output": "it broke"})])
    assert out == ["✗ code_run failed: it broke"]


def test_result_unknown_parent_is_generic():
    feed = EventFeed()
    out = feed.consume([result(1, "nope", {"ok": True, "output": ""})])
    assert out == ["✓ Done"]


def test_result_postcondition_failed_stamp():
    feed = EventFeed()
    feed.consume([call(1, "code_write", event_id="c1")])
    out = feed.consume([result(2, "c1", {
        "ok": True, "output": "...", "postcondition_failed": True,
        "postcondition_failures": ["file_exists:code/demo.txt"]})])
    assert out == ["Delivery check failed: code_write "
                   "(file_exists:code/demo.txt) — treat as not done"]


# --------------------------------------------------------------------------- #
# knowledge-source highlight (the provenance line)
# --------------------------------------------------------------------------- #

def _knowledge_output(matches, count=None, wrap=False):
    body = {"query": "hinglish", "matches": matches,
            "count": len(matches) if count is None else count}
    if wrap:
        body = {"ok": True, "result": body}
    return json.dumps(body)


_M1 = {"file": "knowledge/learn-hinglish.md", "title": "Hinglish",
       "section": "s1", "passage": "..."}
_M2 = {"file": "knowledge/learn-voice.md", "title": "Voice",
       "section": "s2", "passage": "..."}


def test_knowledge_result_names_the_note():
    feed = EventFeed()
    feed.consume([call(1, "knowledge_search", event_id="k1")])
    out = feed.consume([result(2, "k1", {
        "ok": True, "output": _knowledge_output([_M1])})])
    assert out == ["Looked up: learn-hinglish.md"]


def test_knowledge_result_counts_extra_notes():
    feed = EventFeed()
    feed.consume([call(1, "knowledge_search", event_id="k1")])
    out = feed.consume([result(2, "k1", {
        "ok": True, "output": _knowledge_output([_M1, _M2])})])
    assert out == ["Looked up: learn-hinglish.md (+1 more)"]


def test_knowledge_result_wrapped_envelope_and_dict_output():
    feed = EventFeed()
    feed.consume([call(1, "knowledge_search", event_id="k1")])
    wrapped = {"ok": True, "result": {"query": "q", "matches": [_M2],
                                     "count": 1}}
    out = feed.consume([result(2, "k1", {"ok": True, "output": wrapped})])
    assert out == ["Looked up: learn-voice.md"]


def test_knowledge_no_matches_is_honest():
    feed = EventFeed()
    feed.consume([call(1, "knowledge_search", event_id="k1")])
    out = feed.consume([result(2, "k1", {
        "ok": True, "output": _knowledge_output([])})])
    assert out == ["Looked in my notes — no matches"]


def test_knowledge_unparseable_output_falls_back_to_done():
    feed = EventFeed()
    feed.consume([call(1, "knowledge_search", event_id="k1")])
    out = feed.consume([result(2, "k1", {"ok": True, "output": "plain"})])
    assert out == ["✓ knowledge_search done"]


# --------------------------------------------------------------------------- #
# cursor discipline, ordering, cap
# --------------------------------------------------------------------------- #

def test_cursor_never_duplicates_on_repoll():
    feed = EventFeed()
    batch = [call(1, "web_search"), call(2, "web_fetch")]
    assert len(feed.consume(batch)) == 2
    assert feed.consume(batch) == []          # same batch again: nothing new
    assert feed.cursor == 2
    overlap = [call(2, "web_fetch"), call(3, "now")]
    assert feed.consume(overlap) == ["Checking the time…"]
    assert feed.cursor == 3


def test_out_of_order_batch_renders_in_seq_order():
    feed = EventFeed()
    out = feed.consume([call(3, "now"), call(1, "web_search"),
                        call(2, "web_fetch")])
    assert out == ["Searching the web…", "Reading a page…",
                   "Checking the time…"]
    assert feed.cursor == 3


def test_lines_capped_at_max():
    feed = EventFeed()
    n = FEED_MAX_LINES + 50
    added = feed.consume([call(i + 1, "web_search") for i in range(n)])
    assert len(added) == n                      # every event rendered once
    assert len(feed.lines) == FEED_MAX_LINES    # buffer holds only the tail
    assert feed.cursor == n


def test_malformed_events_are_ignored_not_fatal():
    feed = EventFeed()
    out = feed.consume([{"type": "tool.call"},          # no seq
                        {"seq": "x", "type": "tool.call"},
                        ev(1, "mystery.event", {"a": 1}),
                        ev(2, "tool.call", None)])
    assert out == ["Running a tool…"]  # payload-less call still renders
    assert feed.cursor == 2


# --------------------------------------------------------------------------- #
# activity derivation + brain state changes
# --------------------------------------------------------------------------- #

def test_activity_follows_a_whole_turn():
    feed = EventFeed()
    feed.consume([ev(1, "user.message", {"text": "hi"})])
    assert feed.activity == "thinking"
    feed.consume([call(2, "web_search", event_id="c1")])
    assert feed.activity == "tool"
    feed.consume([result(3, "c1", {"ok": True, "output": ""})])
    assert feed.activity == "thinking"
    feed.consume([ev(4, "brain.reply", {"text": "done, sir."})])
    assert feed.activity == "idle"


def test_voice_stage_speaking_sets_activity_without_a_line():
    feed = EventFeed()
    out = feed.consume([ev(1, "voice.stage", {"stage": "speaking"})])
    assert out == []
    assert feed.activity == "speaking"


def test_recovery_escalated_line():
    feed = EventFeed()
    out = feed.consume([ev(1, "recovery.escalated",
                           {"tool": "writer_a", "failure_kind": "postcondition",
                            "summary": "writer_a failed its delivery check"})])
    assert out == ["Recovery: writer_a failed its delivery check"]


# --------------------------------------------------------------------------- #
# pill_state — the state -> (label, color, tempo) table
# --------------------------------------------------------------------------- #

def test_pill_idle_variants():
    assert pill_state(None, "idle") == ("ready", "#2e7d32", 0)
    assert pill_state("unknown", "idle") == ("ready", "#2e7d32", 0)
    assert pill_state("none", "idle") == ("ready", "#2e7d32", 0)
    assert pill_state("ollama", "idle") == ("ready — brain: ollama",
                                            "#2e7d32", 0)


def test_pill_stub_is_honest_red():
    assert pill_state("stub", "idle") == ("STUB — no models!", "#d32f2f", 0)


def test_pill_activity_states():
    assert pill_state("ollama", "thinking") == ("thinking…", "#f9a825", 900)
    assert pill_state("ollama", "tool") == ("working — running a tool…",
                                            "#1565c0", 350)
    assert pill_state("ollama", "speaking") == ("speaking…", "#7b1fa2", 650)
    assert pill_state("ollama", "error") == ("error — see the chat",
                                             "#d32f2f", 0)
    assert pill_state("ollama", "stopped") == ("turn stopped", "#d32f2f", 0)
    assert pill_state("ollama", "approval") == ("waiting approval",
                                                "#d32f2f", 1400)


def test_pill_tempo_tool_is_faster_than_thinking():
    # Team 4's tempo law: busier state, faster pulse (smaller interval).
    assert pill_state("x", "tool")[2] < pill_state("x", "thinking")[2]
    assert pill_state("x", "idle")[2] == 0  # steady means no pulse at all


def test_dim_color_blends_toward_target():
    assert dim_color("#000000") == "#878787"  # 0 + 245*0.55 -> 135 -> 0x87
    assert dim_color("#ffffff") == "#fafafa"  # 255 - 10*0.55 -> 250 -> 0xfa
    assert dim_color("not-a-color") == "not-a-color"


# --------------------------------------------------------------------------- #
# integration: the real store's cursor contract (get_events after_seq)
# --------------------------------------------------------------------------- #

def test_feed_over_real_session_store(tmp_path):
    from jarvis.session_store import SessionStore

    store = SessionStore(str(tmp_path / "sessions.db"))
    sid = store.create_session("owais", "gui")
    store.emit(sid, "user.message", {"text": "search the web"},
               actor="user", trust="user")
    call_id = store.emit(sid, "tool.call",
                         {"tool": "web_search", "args": {"query": "x"},
                          "gate_verdict": "allow"},
                         actor="brain", trust="system")
    store.emit(sid, "tool.result", {"ok": True, "output": "results"},
               actor="tool", trust="tool_untrusted", causal_parent=call_id)
    store.emit(sid, "brain.reply", {"text": "done, sir."},
               actor="brain", trust="user", causal_parent=call_id)

    feed = EventFeed()
    # The GUI's poll loop, verbatim: cursor in, new events out.
    lines = feed.consume(store.get_events(sid, after_seq=feed.cursor))
    assert lines == ["Searching the web…", "✓ web_search done"]
    assert feed.activity == "idle"
    # Polling again at the same cursor yields nothing — no duplicates.
    assert feed.consume(store.get_events(sid, after_seq=feed.cursor)) == []
    store.close()
