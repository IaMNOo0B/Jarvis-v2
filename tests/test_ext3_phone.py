"""Extension Team 3 tests — Team 15 steals implemented in jarvis/phone.py:

1. Self-closing pairing (re-pair revokes old credentials).
2. Unknown-outcome rule for R1 writes (never auto-retry).
3. Confirmation TTL + purge + explicit "expired" reply.
4. Allow-always for exact (tool, args-shape) pairs, hard-blocked for
   R2-adjacent tools.
5. Reconnect discipline: persisted watermark, dedup, stale refusal,
   one latest-state digest.

Message-level fakes only — no network, no real token.
"""
from __future__ import annotations

import json
import time

import pytest

from jarvis.gate import Gate
from jarvis.phone import (
    PhoneRemote,
    CONFIRM_TTL_S, CONFIRM_EXPIRED_MSG, OUTCOME_UNKNOWN_MSG,
    allow_always_blocked, args_shape,
)


class Clock:
    def __init__(self, t: float = 1_000_000.0):
        self.t = t

    def now(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


NOTES_SCHEMA = {
    "type": "object",
    "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
    "required": ["path", "content"],
}


def make_gate(capabilities=("fs.write",)) -> Gate:
    return Gate(skill_registry={
        "notes_write": {"tier": 2, "schema": NOTES_SCHEMA,
                        "capabilities": list(capabilities)},
    })


class Rig:
    """A PhoneRemote with fakes; optionally paired, persisted, failing."""

    def __init__(self, data_dir=None, confirm_ttl_s=None, executor=None,
                 gate=None):
        self.clock = Clock()
        self.brain_calls: list[tuple[str, int]] = []
        self.exec_calls: list[tuple[str, dict]] = []
        self.alerts: list[str] = []

        def brain_fn(text, user_id):
            self.brain_calls.append((text, user_id))
            return "brain reply"

        def default_executor(tool, args):
            self.exec_calls.append((tool, args))
            return "note written"

        kwargs = {}
        if data_dir is not None:
            kwargs["data_dir"] = str(data_dir)
        if confirm_ttl_s is not None:
            kwargs["confirm_ttl_s"] = confirm_ttl_s
        self.remote = PhoneRemote(
            brain_fn, gate or make_gate(),
            token="TESTTOKEN", api_base="http://127.0.0.1:1",
            executor=executor or default_executor, clock=self.clock.now,
            on_alert=self.alerts.append, **kwargs)
        self.remote.set_pin_from_plaintext("1234")

    def pair(self, user_id: int = 111, chat_id: int = 222) -> None:
        code = self.remote.issue_pairing_code()
        reply = self.remote.process_message(self.msg(code, user_id, chat_id))
        assert reply is not None and "Paired" in reply

    def msg(self, text=None, user_id=111, chat_id=222, date=None):
        m = {"message_id": 1,
             "from": {"id": user_id},
             "chat": {"id": chat_id, "type": "private"},
             "date": int(self.clock.now() if date is None else date)}
        if text is not None:
            m["text"] = text
        return m


@pytest.fixture()
def rig() -> Rig:
    return Rig()


# --------------------------------------------------------------------------- #
# 1. Self-closing pairing
# --------------------------------------------------------------------------- #

def test_issue_code_refused_while_paired(rig: Rig):
    rig.pair()
    with pytest.raises(RuntimeError, match="already paired"):
        rig.remote.issue_pairing_code()


def test_revoke_reopens_pairing_and_replaces_device(rig: Rig):
    rig.pair(user_id=111, chat_id=222)
    rig.remote.revoke()
    code = rig.remote.issue_pairing_code()  # desktop re-opens pairing
    reply = rig.remote.process_message(rig.msg(code, user_id=999, chat_id=888))
    assert reply is not None and "Paired" in reply
    # New device works...
    assert rig.remote.process_message(
        rig.msg("hi", user_id=999, chat_id=888)) == "brain reply"
    # ...old device credentials are revoked: silence, brain never sees it.
    assert rig.remote.process_message(rig.msg("hi")) is None
    assert ("hi", 111) not in rig.brain_calls


def test_repair_kills_old_pending_and_credentials(rig: Rig):
    rig.pair()
    rig.remote.process_message(rig.msg("note buy milk"))
    assert rig.remote._pending_for(222) is not None
    # Desktop forces a fresh pairing session while state is live:
    rig.remote.revoke()
    code = rig.remote.issue_pairing_code()
    rig.remote.process_message(rig.msg(code, user_id=999, chat_id=888))
    # The old device's pending confirmation died with its credentials.
    assert rig.remote._pending == {}
    # The old device's PIN cannot execute anything now.
    assert rig.remote.process_message(rig.msg("1234")) is None
    assert rig.exec_calls == []


def test_old_code_dead_after_successful_pair(rig: Rig):
    code = rig.remote.issue_pairing_code()
    rig.remote.process_message(rig.msg(code))
    paired_at = rig.remote._paired["paired_at"]
    # Replay from a different identity: silence, pairing unchanged.
    assert rig.remote.process_message(
        rig.msg(code, user_id=999, chat_id=999)) is None
    assert rig.remote._paired["user_id"] == 111
    assert rig.remote._paired["paired_at"] == paired_at


# --------------------------------------------------------------------------- #
# 2. Unknown-outcome rule
# --------------------------------------------------------------------------- #

def _failing_rig() -> Rig:
    attempts: list = []

    def bad_executor(tool, args):
        attempts.append((tool, args))
        raise RuntimeError("disk died mid-write")

    r = Rig(executor=bad_executor)
    r.exec_attempts = attempts
    return r


def test_executor_failure_reports_unknown_never_retried():
    r = _failing_rig()
    r.pair()
    r.remote.process_message(r.msg("note buy milk"))
    reply = r.remote.process_message(r.msg("1234"))
    assert reply == OUTCOME_UNKNOWN_MSG
    assert "unknown" in reply.lower() and "verify on the PC" in reply
    assert len(r.exec_attempts) == 1
    # The outcome is recorded as an explicit state, desktop-visible.
    assert r.remote.outcome_log[-1]["outcome"] == "unknown"
    # Re-sending the PIN must NOT re-execute the write.
    r.remote.process_message(r.msg("1234"))
    assert len(r.exec_attempts) == 1


def test_gate_block_is_blocked_not_unknown():
    # Gate denies BEFORE the executor runs (capability not granted):
    # outcome is known — nothing ran — and must not be reported "unknown".
    r = Rig(gate=make_gate(capabilities=("net.send",)))
    r.pair()
    r.remote.process_message(r.msg("note buy milk"))
    reply = r.remote.process_message(r.msg("1234"))
    assert reply.startswith("Blocked at execution")
    assert "Nothing ran" in reply
    assert r.exec_calls == []
    assert r.remote.outcome_log[-1]["outcome"] == "blocked"


def test_successful_confirm_records_done(rig: Rig):
    rig.pair()
    rig.remote.process_message(rig.msg("note buy milk"))
    reply = rig.remote.process_message(rig.msg("1234"))
    assert reply.startswith("Done, sir")
    assert rig.remote.outcome_log[-1]["outcome"] == "done"


# --------------------------------------------------------------------------- #
# 3. Confirmation TTL + purge + expired reply
# --------------------------------------------------------------------------- #

def test_default_confirm_ttl_is_five_minutes():
    assert CONFIRM_TTL_S == 5 * 60


def test_late_pin_gets_expired_reply(rig: Rig):
    rig.pair()
    rig.remote.process_message(rig.msg("note buy milk"))
    rig.clock.advance(5 * 60 + 1)
    reply = rig.remote.process_message(rig.msg("1234"))
    assert reply == CONFIRM_EXPIRED_MSG
    assert rig.exec_calls == []


def test_expired_reply_consumed_once(rig: Rig):
    rig.pair()
    rig.remote.process_message(rig.msg("note buy milk"))
    rig.clock.advance(6 * 60)
    assert rig.remote.process_message(rig.msg("1234")) == CONFIRM_EXPIRED_MSG
    # Second stray PIN is just a fresh turn now, not another "expired".
    assert rig.remote.process_message(rig.msg("1234")) == "brain reply"


def test_confirm_within_ttl_still_works(rig: Rig):
    rig.pair()
    rig.remote.process_message(rig.msg("note buy milk"))
    rig.clock.advance(4 * 60)
    reply = rig.remote.process_message(rig.msg("1234"))
    assert reply.startswith("Done, sir")
    assert len(rig.exec_calls) == 1


def test_custom_confirm_ttl():
    r = Rig(confirm_ttl_s=60)
    r.pair()
    r.remote.process_message(r.msg("note buy milk"))
    r.clock.advance(61)
    assert r.remote.process_message(r.msg("1234")) == CONFIRM_EXPIRED_MSG
    assert r.exec_calls == []


def test_purge_pass_runs_on_poll_cycle(rig: Rig):
    rig.pair()
    rig.remote.process_message(rig.msg("note buy milk"))
    assert rig.remote._pending != {}
    rig.clock.advance(6 * 60)
    rig.remote._api = lambda method, payload=None, timeout=35.0: {
        "ok": True, "result": []}
    assert rig.remote.poll_once() == 0
    assert rig.remote._pending == {}
    assert rig.remote.outcome_log[-1]["outcome"] == "expired"
    # The purge left an expiry notice: a late PIN still gets the reply.
    assert rig.remote.process_message(rig.msg("1234")) == CONFIRM_EXPIRED_MSG


# --------------------------------------------------------------------------- #
# 4. Allow-always — BLOCKLIST FIRST (the hard guarantee), then the flow
# --------------------------------------------------------------------------- #

R2_ADJACENT_TOOLS = [
    "execute_code", "run_code", "eval_code", "shell_run", "memory_delete",
    "secret_get", "system_shutdown", "install_skill", "password_reset",
    "grant_permission", "delete_file", "token_rotate", "jarvis_update",
]


def test_allow_always_blocklist_hard_blocks_r2_tools(rig: Rig):
    for tool in R2_ADJACENT_TOOLS:
        assert allow_always_blocked(tool), tool
        assert rig.remote.promote_allow_always(tool, {"x": "y"}) is False, tool
        assert rig.remote.is_allow_always(tool, {"x": "y"}) is False, tool
    assert rig.remote.allow_always_entries() == []


def test_allow_always_rejects_non_r1_tools(rig: Rig):
    # Only phone-writable R1 tools are promotable at all.
    assert rig.remote.promote_allow_always("time_read", {}) is False
    assert rig.remote.promote_allow_always("notes_read", {"path": "x"}) is False
    assert rig.remote.allow_always_entries() == []


def test_args_shape_is_structural_not_values():
    a = args_shape("notes_write", {"path": "a.txt", "content": "milk"})
    b = args_shape("notes_write", {"content": "bread", "path": "b.txt"})
    assert a == b == "notes_write(content:str,path:str)"
    c = args_shape("notes_write", {"path": "a.txt", "content": "x", "n": 1})
    assert c != a


def test_allow_always_entry_in_state_file_cannot_smuggle_r2(tmp_path):
    # Even a hand-edited state file cannot promote an R2-adjacent tool:
    # blocked entries are filtered at load time.
    (tmp_path / "phone_allowlist.json").write_text(json.dumps({
        "version": 1,
        "entries": [{"tool": "execute_code",
                     "shape": "execute_code(code:str)", "added_at": 1}]}))
    r = Rig(data_dir=tmp_path)
    assert r.remote.allow_always_entries() == []
    assert r.remote.is_allow_always("execute_code", {"code": "x"}) is False


def test_always_pin_promotes_then_skips_pin(rig: Rig):
    rig.pair()
    rig.remote.process_message(rig.msg("note buy milk"))
    reply = rig.remote.process_message(rig.msg("ALWAYS 1234"))
    assert reply.startswith("Done, sir")
    assert "Allow-always set" in reply
    assert len(rig.exec_calls) == 1
    # Same command shape again: no confirmation round-trip at all.
    reply2 = rig.remote.process_message(rig.msg("note buy bread"))
    assert reply2.startswith("Done, sir (allow-always)")
    assert len(rig.exec_calls) == 2


def test_plain_pin_does_not_promote(rig: Rig):
    rig.pair()
    rig.remote.process_message(rig.msg("note buy milk"))
    rig.remote.process_message(rig.msg("1234"))
    reply = rig.remote.process_message(rig.msg("note buy bread"))
    assert "Confirm, sir" in reply  # still asks


def test_allow_always_persists_and_revokes(tmp_path):
    r1 = Rig(data_dir=tmp_path)
    args = {"path": "phone-x.txt", "content": "milk"}
    assert r1.remote.promote_allow_always("notes_write", args) is True
    # A fresh PhoneRemote over the same data dir sees the promotion.
    r2 = Rig(data_dir=tmp_path)
    assert r2.remote.is_allow_always("notes_write",
                                     {"path": "other", "content": "z"})
    # Different shape does NOT match.
    assert not r2.remote.is_allow_always(
        "notes_write", {"path": "p", "content": "c", "extra": 1})
    # Desktop revocation works and persists.
    assert r2.remote.revoke_allow_always("notes_write", args) is True
    assert r2.remote.revoke_allow_always("notes_write", args) is False
    r3 = Rig(data_dir=tmp_path)
    assert r3.remote.allow_always_entries() == []


def test_allow_always_unknown_outcome_still_unknown():
    r = _failing_rig()
    r.pair()
    assert r.remote.promote_allow_always(
        "notes_write", {"path": "a", "content": "b"}) is True
    reply = r.remote.process_message(r.msg("note buy milk"))
    assert reply == OUTCOME_UNKNOWN_MSG
    assert len(r.exec_attempts) == 1


# --------------------------------------------------------------------------- #
# 5. Reconnect discipline: watermark, dedup, stale refusal, digest
# --------------------------------------------------------------------------- #

class PollRig(Rig):
    """Rig wired for poll_once: fake getUpdates + captured sends."""

    def __init__(self, data_dir=None):
        super().__init__(data_dir=data_dir)
        self.updates: list[dict] = []
        self.sent: list[tuple[int, str]] = []

        def fake_api(method, payload=None, timeout=35.0):
            if method == "getUpdates":
                out, self.updates = self.updates, []
                return {"ok": True, "result": out}
            return {"ok": True, "result": {}}

        self.remote._api = fake_api
        self.remote.send = lambda chat_id, text: self.sent.append(
            (chat_id, text))

    def upd(self, upd_id: int, text: str, user_id=111, chat_id=222,
            date=None) -> dict:
        return {"update_id": upd_id,
                "message": self.msg(text, user_id, chat_id, date=date)}


@pytest.fixture()
def poll_rig(tmp_path) -> PollRig:
    r = PollRig(data_dir=tmp_path)
    r.pair()
    return r


def test_watermark_persists_and_dedups(poll_rig: PollRig, tmp_path):
    poll_rig.updates = [poll_rig.upd(10, "hello"),
                        poll_rig.upd(11, "hello again")]
    assert poll_rig.remote.poll_once() == 2
    assert len(poll_rig.brain_calls) == 2
    state = json.loads((tmp_path / "phone_state.json").read_text())
    assert state["last_update_id"] == 11
    # After a restart, a NEW remote over the same data dir resumes the
    # watermark and dedups Telegram's re-delivery of update 11.
    r2 = PollRig(data_dir=tmp_path)
    assert r2.remote._last_update_id == 11
    assert r2.remote._offset == 12
    r2.remote._paired = {"user_id": 111, "chat_id": 222,
                         "paired_at": r2.clock.now(),
                         "last_active": r2.clock.now()}
    r2.updates = [r2.upd(11, "hello again"), r2.upd(12, "fresh one")]
    r2.remote.poll_once()
    assert [t for t, _ in r2.brain_calls] == ["fresh one"]


def test_stale_commands_refused_digest_sent_once(poll_rig: PollRig):
    now = poll_rig.clock.now()
    poll_rig.updates = [
        poll_rig.upd(20, "note buy milk", date=now - 3600),   # stale write
        poll_rig.upd(21, "what time is it", date=now - 1800),  # stale read
        poll_rig.upd(22, "hello"),                              # fresh
    ]
    poll_rig.remote.poll_once()
    # Nothing stale executed: no pending write, only the fresh turn ran.
    assert poll_rig.remote._pending == {}
    assert poll_rig.exec_calls == []
    assert [t for t, _ in poll_rig.brain_calls] == ["hello"]
    kinds = [c["kind"] for c in poll_rig.remote.contact_log]
    assert kinds.count("stale_refused") == 2
    # Exactly one digest to the paired chat, on top of the fresh reply.
    digests = [t for _c, t in poll_rig.sent if "Back online" in t]
    assert len(digests) == 1
    assert "refused, never replayed" in digests[0]


def test_stale_stranger_logged_and_silent(poll_rig: PollRig):
    now = poll_rig.clock.now()
    poll_rig.updates = [poll_rig.upd(30, "note evil", user_id=999,
                                     chat_id=999, date=now - 3600)]
    poll_rig.remote.poll_once()
    assert poll_rig.sent == []  # no digest, no reply — silence to strangers
    entry = poll_rig.remote.contact_log[-1]
    assert entry["kind"] == "stale_refused" and entry["user_id"] == 999


def test_stale_pairing_code_refused(tmp_path):
    r = PollRig(data_dir=tmp_path)  # NOT paired
    code = r.remote.issue_pairing_code()
    now = r.clock.now()
    r.updates = [r.upd(40, code, date=now - 3600)]
    r.remote.poll_once()
    assert not r.remote.is_paired
    # The same code, delivered fresh, pairs normally.
    r.updates = [r.upd(41, code)]
    r.remote.poll_once()
    assert r.remote.is_paired


def test_fresh_backlog_within_window_still_processes(poll_rig: PollRig):
    now = poll_rig.clock.now()
    poll_rig.updates = [poll_rig.upd(50, "recent question",
                                     date=now - 60)]
    poll_rig.remote.poll_once()
    assert [t for t, _ in poll_rig.brain_calls] == ["recent question"]
    assert not any("Back online" in t for _c, t in poll_rig.sent)
