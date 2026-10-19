"""Tests for jarvis/phone.py — the Telegram phone surface.

Uses a fake Telegram Bot API server (http.server in a thread) and a
controllable clock. No network, no real token, no real Telegram.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from jarvis.gate import Gate
from jarvis.phone import (
    PhoneRemote, RateLimiter,
    HOLD_MSG, SESSION_EXPIRED, SLOW_DOWN, VOICE_TOO_BIG, VOICE_CANT_CONFIRM,
    NO_PIN_SET,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

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


def make_gate() -> Gate:
    return Gate(skill_registry={
        "notes_write": {"tier": 2, "schema": NOTES_SCHEMA,
                        "capabilities": ["fs.write"]},
    })


class Rig:
    """A paired PhoneRemote with fakes, ready for message-level tests."""

    def __init__(self):
        self.clock = Clock()
        self.brain_calls: list[tuple[str, int]] = []
        self.exec_calls: list[tuple[str, dict]] = []
        self.alerts: list[str] = []
        gate = make_gate()

        def brain_fn(text, user_id):
            self.brain_calls.append((text, user_id))
            return "brain reply"

        def executor(tool, args):
            self.exec_calls.append((tool, args))
            return "note written"

        self.remote = PhoneRemote(
            brain_fn, gate,
            token="TESTTOKEN", api_base="http://127.0.0.1:1",  # no HTTP in these tests
            executor=executor, clock=self.clock.now,
            on_alert=self.alerts.append)
        self.remote.set_pin_from_plaintext("1234")

    def pair(self, user_id: int = 111, chat_id: int = 222) -> None:
        code = self.remote.issue_pairing_code()
        reply = self.remote.process_message(self.msg(code, user_id, chat_id))
        assert reply is not None and "Paired" in reply

    @staticmethod
    def msg(text=None, user_id=111, chat_id=222, chat_type="private",
            voice=None, date=None):
        m = {"message_id": 1,
             "from": {"id": user_id},
             "chat": {"id": chat_id, "type": chat_type},
             "date": int(date if date is not None else time.time())}
        if text is not None:
            m["text"] = text
        if voice is not None:
            m["voice"] = voice
        return m


@pytest.fixture()
def rig() -> Rig:
    return Rig()


# --------------------------------------------------------------------------- #
# Pairing
# --------------------------------------------------------------------------- #

def test_pairing_happy_path(rig: Rig):
    code = rig.remote.issue_pairing_code()
    assert len(code) == 6 and code.isdigit()
    reply = rig.remote.process_message(rig.msg(code))
    assert reply and "Paired" in reply
    assert rig.remote.is_paired


def test_pair_code_single_use(rig: Rig):
    code = rig.remote.issue_pairing_code()
    rig.remote.process_message(rig.msg(code))  # pairs user 111
    # Attacker tries a code from another identity: silence.
    reply = rig.remote.process_message(rig.msg("999999", user_id=999, chat_id=999))
    assert reply is None  # silence, not an error
    assert rig.remote._paired["user_id"] == 111


def test_pair_code_expired(rig: Rig):
    code = rig.remote.issue_pairing_code()
    rig.clock.advance(6 * 60)
    reply = rig.remote.process_message(rig.msg(code))
    assert reply is None
    assert not rig.remote.is_paired


def test_stranger_gets_silence(rig: Rig):
    reply = rig.remote.process_message(rig.msg("hello?"))
    assert reply is None
    assert rig.remote.contact_log and rig.remote.contact_log[0]["kind"] == "stranger"


def test_group_chat_ignored_entirely(rig: Rig):
    rig.pair()
    reply = rig.remote.process_message(rig.msg("hello", chat_type="group"))
    assert reply is None
    kinds = [c["kind"] for c in rig.remote.contact_log]
    assert "group_ignored" in kinds
    assert rig.brain_calls == []


def test_session_expires_after_24h_idle(rig: Rig):
    rig.pair()
    rig.clock.advance(25 * 3600)
    reply = rig.remote.process_message(rig.msg("are you there"))
    assert reply == SESSION_EXPIRED
    assert not rig.remote.is_paired


# --------------------------------------------------------------------------- #
# Tiers
# --------------------------------------------------------------------------- #

def test_r0_brain_turn(rig: Rig):
    rig.pair()
    reply = rig.remote.process_message(rig.msg("what time is it"))
    assert reply == "brain reply"
    assert rig.brain_calls == [("what time is it", 111)]


def test_r2_refused_before_brain(rig: Rig):
    rig.pair()
    for text in ["delete all my files", "shutdown the pc",
                 "execute this code", "install skill evil",
                 "what is my api key"]:
        reply = rig.remote.process_message(rig.msg(text))
        assert reply is not None and "can't do that from the phone" in reply, text
    assert rig.brain_calls == []  # brain never consulted


def test_r1_flow_pin_ok(rig: Rig):
    rig.pair()
    reply = rig.remote.process_message(rig.msg("note buy milk"))
    assert "Confirm" in reply and "notes_write" in reply
    assert "action hash:" in reply
    assert rig.exec_calls == []  # nothing executed yet
    reply2 = rig.remote.process_message(rig.msg("1234"))
    assert reply2.startswith("Done, sir")
    assert len(rig.exec_calls) == 1
    tool, args = rig.exec_calls[0]
    assert tool == "notes_write"
    assert args["content"] == "buy milk"


def test_r1_wrong_pin_refused(rig: Rig):
    rig.pair()
    rig.remote.process_message(rig.msg("note buy milk"))
    reply = rig.remote.process_message(rig.msg("0000"))
    assert "Wrong PIN" in reply
    assert rig.exec_calls == []


def test_r1_no_pin_set():
    r = Rig()
    r.remote._pin = None
    r.pair()
    reply = r.remote.process_message(r.msg("note buy milk"))
    assert reply == NO_PIN_SET


def test_r1_confirmation_expires(rig: Rig):
    rig.pair()
    rig.remote.process_message(rig.msg("note buy milk"))
    rig.clock.advance(11 * 60)
    rig.remote.process_message(rig.msg("1234"))  # treated as a fresh turn now
    assert rig.exec_calls == []


def test_r1_tampered_action_refused(rig: Rig):
    rig.pair()
    rig.remote.process_message(rig.msg("note buy milk"))
    pending = rig.remote._pending_for(222)
    assert pending is not None
    pending["args"] = {"path": "evil.txt", "content": "pwned"}  # simulate swap
    reply = rig.remote.process_message(rig.msg("1234"))
    assert "Action changed" in reply
    assert rig.exec_calls == []


def test_pin_never_stored_plaintext(rig: Rig):
    blob = json.dumps(rig.remote._pin)
    assert "1234" not in blob
    assert rig.remote.verify_pin("1234")
    assert not rig.remote.verify_pin("0000")


# --------------------------------------------------------------------------- #
# Rate limits & HOLD (F3 manufactured-fatigue defense)
# --------------------------------------------------------------------------- #

def test_text_rate_limit(rig: Rig):
    rig.pair()
    for _ in range(20):
        rig.remote.process_message(rig.msg("hi"))
    reply = rig.remote.process_message(rig.msg("hi"))
    assert reply == SLOW_DOWN


def test_confirmation_hold_and_resume(rig: Rig):
    rig.pair()
    for i in range(5):
        r = rig.remote.process_message(rig.msg(f"note item {i}"))
        assert "Confirm" in r
    r = rig.remote.process_message(rig.msg("note one more"))
    assert r == HOLD_MSG
    assert 222 in rig.remote._hold
    r = rig.remote.process_message(rig.msg("RESUME"))
    assert "Resumed" in r
    assert 222 not in rig.remote._hold


# --------------------------------------------------------------------------- #
# Voice notes
# --------------------------------------------------------------------------- #

def test_voice_too_big_refused(rig: Rig):
    rig.pair()
    voice = {"file_id": "abc", "file_size": 11 * 1024 * 1024,
             "mime_type": "audio/ogg", "duration": 999}
    reply = rig.remote.process_message(rig.msg(voice=voice))
    assert reply == VOICE_TOO_BIG


def test_voice_cannot_confirm_r1(rig: Rig):
    rig.pair()
    rig.remote.process_message(rig.msg("note buy milk"))
    voice = {"file_id": "abc", "file_size": 1000,
             "mime_type": "audio/ogg", "duration": 5}
    reply = rig.remote.process_message(rig.msg(voice=voice))
    assert reply == VOICE_CANT_CONFIRM
    assert rig.exec_calls == []


def test_voice_no_stt_configured(rig: Rig):
    rig.pair()
    voice = {"file_id": "abc", "file_size": 1000,
             "mime_type": "audio/ogg", "duration": 5}
    reply = rig.remote.process_message(rig.msg(voice=voice))
    assert "no speech recognizer" in reply


# --------------------------------------------------------------------------- #
# Fake Telegram server: validate(), getMe 401, voice download path
# --------------------------------------------------------------------------- #

class FakeTG(BaseHTTPRequestHandler):
    routes: dict = {}
    last_paths: list = []

    def _send(self, code: int, obj: dict):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        FakeTG.last_paths.append(self.path)
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        handler = FakeTG.routes.get(self.path)
        if handler:
            code, obj = handler()
            self._send(code, obj)
        else:
            self._send(404, {"ok": False})

    def do_GET(self):
        FakeTG.last_paths.append(self.path)
        if self.path.startswith("/file/botTESTTOKEN/"):
            body = b"OGG" * 100
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._send(404, {"ok": False})

    def log_message(self, *a):
        pass


@pytest.fixture()
def tg_server():
    FakeTG.routes = {}
    FakeTG.last_paths = []
    srv = HTTPServer(("127.0.0.1", 0), FakeTG)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def _remote_with_server(base: str, clock=None) -> tuple[PhoneRemote, dict, list]:
    gate = make_gate()
    calls: list = []
    alerts: list = []
    r = PhoneRemote(lambda text, uid: "brain reply", gate,
                    token="TESTTOKEN", api_base=base,
                    executor=lambda t, a: "ok",
                    clock=(clock.now if clock else time.time),
                    on_alert=alerts.append)
    return r, calls, alerts


def test_validate_ok(tg_server):
    FakeTG.routes[f"/botTESTTOKEN/getMe"] = lambda: (200, {"ok": True, "result": {"id": 1}})
    r, _, _ = _remote_with_server(tg_server)
    assert r.validate() is True


def test_validate_401_disables_without_token_leak(tg_server):
    FakeTG.routes[f"/botTESTTOKEN/getMe"] = lambda: (401, {"ok": False, "description": "Unauthorized"})
    r, _, _ = _remote_with_server(tg_server)
    assert r.validate() is False
    assert r._disabled_reason is not None
    assert "TESTTOKEN" not in r._disabled_reason  # token never in messages


def test_token_never_in_redacted_strings(tg_server):
    r, _, _ = _remote_with_server(tg_server)
    assert "TESTTOKEN" not in r._redact(f"url=https://x/botTESTTOKEN/getMe oops")


def test_voice_download_transcribe_delete(tg_server):
    clock = Clock()
    FakeTG.routes[f"/botTESTTOKEN/getFile"] = (
        lambda: (200, {"ok": True, "result": {"file_path": "voice/f1.oga"}}))
    seen_paths: list[str] = []

    def fake_stt(path: str) -> str:
        seen_paths.append(path)
        assert path.endswith(".oga")
        return "remind me later"

    r, _, _ = _remote_with_server(tg_server, clock)
    r.stt_fn = fake_stt
    r.set_pin_from_plaintext("1234")
    code = r.issue_pairing_code()
    # pair via direct message dict (no HTTP needed for process_message)
    msg = {"message_id": 1, "from": {"id": 7}, "chat": {"id": 8, "type": "private"},
           "date": int(time.time()), "text": code}
    assert "Paired" in r.process_message(msg)
    vmsg = {"message_id": 2, "from": {"id": 7}, "chat": {"id": 8, "type": "private"},
            "date": int(time.time()),
            "voice": {"file_id": "f1", "file_size": 300,
                      "mime_type": "audio/ogg", "duration": 3}}
    reply = r.process_message(vmsg)
    assert reply == "brain reply"  # transcript went through as an R0 turn
    assert len(seen_paths) == 1
    import os
    assert not os.path.exists(seen_paths[0])  # temp file deleted
