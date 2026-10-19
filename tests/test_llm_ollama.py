"""Tests for jarvis.llm_ollama — fake Ollama server in a thread.

No network, no model. Covers: answer parsing, TOOL:/ARGS: line parsing,
native tool_calls normalization, request shape, health true/false,
timeout -> typed error, connection refused -> typed error, malformed
output -> honest error (never a fake reply), empty reply -> honest error,
make_llm_call stub fallback (loud, never silent), FallbackChain adapter,
and the round-trip contract with Brain._parse_reply.
"""

import io
import json
import socket
import threading
import time
from contextlib import redirect_stderr
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from jarvis.brain import Brain
from jarvis.llm_ollama import (
    OllamaCall,
    OllamaConnectionError,
    OllamaError,
    OllamaHTTPError,
    OllamaProvider,
    OllamaTimeoutError,
    make_llm_call,
)

MODEL = "qwen2.5:7b-instruct-q4_K_M"


class FakeOllama(BaseHTTPRequestHandler):
    mode = "answer"          # POST /api/chat behavior
    tags_models = [MODEL]    # GET /api/tags model list
    last_request = None

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/api/tags":
            self._json({"models": [{"name": m} for m in FakeOllama.tags_models]})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        FakeOllama.last_request = json.loads(self.rfile.read(length) or b"{}")
        mode = FakeOllama.mode
        if mode == "sleep":
            time.sleep(3)
            self._json({"message": {"role": "assistant", "content": "too late"}})
        elif mode == "tool_lines":
            self._json({"message": {"role": "assistant",
                                    "content": "TOOL: now\nARGS: {}"}})
        elif mode == "native_tools":
            self._json({"message": {"role": "assistant", "content": "",
                                    "tool_calls": [{"function": {"name": "now",
                                                                 "arguments": {}}}]}})
        elif mode == "empty":
            self._json({"message": {"role": "assistant", "content": "   "}})
        elif mode == "no_message":
            self._json({"done": True})
        elif mode == "garbage":
            body = b"this is not json at all"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif mode == "http500":
            self._json({"error": "boom"}, 500)
        else:
            self._json({"message": {"role": "assistant",
                                    "content": "At your service, sir."}})

    def log_message(self, *args):  # noqa: D102 — keep test output clean
        pass


@pytest.fixture()
def server():
    FakeOllama.mode = "answer"
    FakeOllama.tags_models = [MODEL]
    FakeOllama.last_request = None
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _unused_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _call(base_url, **kw):
    kw.setdefault("timeout", 10)
    return OllamaCall(base_url=base_url, model=MODEL, **kw)


# -- parsing --------------------------------------------------------------- #

def test_plain_answer(server):
    out = _call(server)([{"role": "user", "content": "hi"}])
    assert out == {"content": "At your service, sir."}


def test_tool_lines_parsed(server):
    FakeOllama.mode = "tool_lines"
    out = _call(server)([{"role": "user", "content": "time?"}])
    assert out == {"tool_calls": [{"name": "now", "args": {}}]}


def test_native_tool_calls_normalized(server):
    FakeOllama.mode = "native_tools"
    out = _call(server)([{"role": "user", "content": "time?"}])
    assert out == {"tool_calls": [{"name": "now", "args": {}}]}


def test_request_shape(server):
    FakeOllama.mode = "answer"
    _call(server)([{"role": "user", "content": "hi"}])
    req = FakeOllama.last_request
    assert req["model"] == MODEL
    assert req["stream"] is False
    assert isinstance(req["messages"], list)
    assert req["messages"][0]["role"] == "user"
    # Brain-internal keys are stripped before sending.
    _call(server)([{"role": "assistant", "content": None,
                   "tool_calls": [{"name": "x"}]}])
    last = FakeOllama.last_request["messages"][-1]
    assert set(last) == {"role", "content"}
    assert last["content"] == ""


def test_result_roundtrips_through_brain_parser(server):
    FakeOllama.mode = "tool_lines"
    out = _call(server)([{"role": "user", "content": "time?"}])
    kind, payload = Brain._parse_reply(out)
    assert kind == "tools" and payload == [("now", {})]
    FakeOllama.mode = "answer"
    out = _call(server)([{"role": "user", "content": "hi"}])
    kind, payload = Brain._parse_reply(out)
    assert kind == "answer" and payload == "At your service, sir."


# -- health ---------------------------------------------------------------- #

def test_health_ok(server):
    ok, msg = _call(server).check_health()
    assert ok and "present" in msg


def test_health_model_missing(server):
    FakeOllama.tags_models = ["llama3:8b"]
    ok, msg = _call(server).check_health()
    assert not ok and "ollama pull" in msg and MODEL in msg


def test_health_unreachable():
    ok, msg = _call(f"http://127.0.0.1:{_unused_port()}").check_health()
    assert not ok and "not reachable" in msg


# -- failures are typed, never faked --------------------------------------- #

def test_timeout_raises_typed_error(server):
    FakeOllama.mode = "sleep"
    with pytest.raises(OllamaTimeoutError):
        _call(server, timeout=0.3)([{"role": "user", "content": "hi"}])


def test_timeout_is_transport_typed_for_fallback_chain(server):
    FakeOllama.mode = "sleep"
    try:
        _call(server, timeout=0.3)([{"role": "user", "content": "hi"}])
    except OllamaTimeoutError as exc:
        assert isinstance(exc, TimeoutError)
        assert isinstance(exc, ConnectionError)
    else:
        pytest.fail("expected OllamaTimeoutError")


def test_connection_refused_raises_typed_error():
    with pytest.raises(OllamaConnectionError):
        _call(f"http://127.0.0.1:{_unused_port()}")([{"role": "user", "content": "hi"}])


def test_http_error_carries_status(server):
    FakeOllama.mode = "http500"
    with pytest.raises(OllamaHTTPError) as ei:
        _call(server)([{"role": "user", "content": "hi"}])
    assert ei.value.status == 500


def test_garbage_body_is_honest_error(server):
    FakeOllama.mode = "garbage"
    with pytest.raises(OllamaError, match="not JSON"):
        _call(server)([{"role": "user", "content": "hi"}])


def test_empty_reply_is_honest_error_never_faked(server):
    FakeOllama.mode = "empty"
    with pytest.raises(OllamaError, match="empty reply"):
        _call(server)([{"role": "user", "content": "hi"}])


def test_missing_message_is_honest_error(server):
    FakeOllama.mode = "no_message"
    with pytest.raises(OllamaError, match="'message'"):
        _call(server)([{"role": "user", "content": "hi"}])


# -- factory: stub fallback is loud, never silent ---------------------------- #

def test_make_llm_call_returns_ollama_when_healthy(server, capsys):
    call = make_llm_call(base_url=server, model=MODEL)
    assert isinstance(call, OllamaCall)
    assert "WARNING" not in capsys.readouterr().err


def test_make_llm_call_falls_back_to_stub_loudly():
    from jarvis.chat import StubLLM
    err = io.StringIO()
    with redirect_stderr(err):
        call = make_llm_call(base_url=f"http://127.0.0.1:{_unused_port()}",
                             model=MODEL)
    assert isinstance(call, StubLLM)
    banner = err.getvalue()
    assert "WARNING" in banner and "STUB" in banner and "ollama serve" in banner


# -- FallbackChain adapter --------------------------------------------------- #

def test_provider_adapter_returns_reparseable_text(server):
    FakeOllama.mode = "tool_lines"
    prov = OllamaProvider(_call(server))
    assert prov.name == "ollama" and prov.keys == []
    text = prov.respond([{"role": "user", "content": "time?"}])
    kind, payload = Brain._parse_reply(text)
    assert kind == "tools" and payload == [("now", {})]


def test_provider_adapter_timeout_is_transport_typed(server):
    FakeOllama.mode = "sleep"
    prov = OllamaProvider(_call(server))
    with pytest.raises(TimeoutError):
        prov.respond([{"role": "user", "content": "hi"}], timeout=0.3)


def test_provider_adapter_plain_answer(server):
    prov = OllamaProvider(_call(server))
    assert prov.respond([{"role": "user", "content": "hi"}]) == "At your service, sir."
