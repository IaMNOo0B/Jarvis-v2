"""Tests for jarvis.llm_omniroute — the OmniRoute gateway provider."""

import io
import json
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from jarvis import llm_omniroute as om
from jarvis.brain import ProviderHTTPError


# -- fake gateway ---------------------------------------------------------- #
class _Handler(BaseHTTPRequestHandler):
    mode = "ok"  # ok | http500 | badshape

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/v1/models":
            self._send(200, {"data": [{"id": "google/gemini-2.5-flash"}]})
        else:
            self._send(404, {})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        # Echo the auth header presence for the test to assert.
        assert self.headers.get("Authorization", "").startswith("Bearer "), \
            "missing Bearer token"
        assert body.get("stream") is False
        if self.mode == "http500":
            self._send(500, {"error": "boom"})
        elif self.mode == "badshape":
            self._send(200, {"nope": True})
        else:
            self._send(200, {"choices": [
                {"message": {"content": "hello sir"}}]})

    def log_message(self, *a):
        pass


@pytest.fixture()
def gateway():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _Handler.mode = "ok"
    yield f"http://127.0.0.1:{port}/v1"
    server.shutdown()


def _call(base_url, **kw):
    return om.OmniRouteCall(base_url=base_url, token="test-key", **kw)


def test_health_ok(gateway):
    call = _call(gateway)
    ok, msg = call.check_health()
    assert ok and "1 models" in msg


def test_health_down():
    call = _call("http://127.0.0.1:1/v1")
    ok, msg = call.check_health()
    assert not ok and "not reachable" in msg


def test_chat_roundtrip(gateway):
    call = _call(gateway)
    out = call([{"role": "user", "content": "hi"}])
    assert out == {"content": "hello sir"}


def test_messages_sanitized(gateway):
    # Brain-internal keys must not leak to the gateway.
    seen = {}

    orig = _Handler.do_POST

    def spy(self):
        length = int(self.headers.get("Content-Length", 0))
        seen["body"] = json.loads(self.rfile.read(length) or b"{}")
        self._send(200, {"choices": [{"message": {"content": "ok"}}]})

    _Handler.do_POST = spy
    try:
        _call(gateway)([{"role": "user", "content": "x", "tool_calls": [1],
                         "weird_role": "zzz"}])
    finally:
        _Handler.do_POST = orig
    msgs = seen["body"]["messages"]
    assert msgs == [{"role": "user", "content": "x"}]


def test_http500_maps_to_provider_error(gateway):
    _Handler.mode = "http500"
    with pytest.raises(ProviderHTTPError) as exc:
        _call(gateway)([{"role": "user", "content": "hi"}])
    assert exc.value.status == 500


def test_bad_shape_raises_honest(gateway):
    _Handler.mode = "badshape"
    with pytest.raises(om.OmniRouteError):
        _call(gateway)([{"role": "user", "content": "hi"}])


def test_provider_ducktype(gateway):
    call = _call(gateway)
    prov = om.OmniRouteProvider(call)
    assert prov.name == "omniroute" and prov.keys == []
    assert prov.respond([{"role": "user", "content": "hi"}]) == "hello sir"


def test_make_call_returns_none_when_down(capsys):
    assert om.make_omniroute_call(base_url="http://127.0.0.1:1/v1") is None
    assert "unavailable" in capsys.readouterr().err
