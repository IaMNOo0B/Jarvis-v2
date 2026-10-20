"""Regression tests for provider-specific timeout propagation."""

from jarvis.llm_omniroute import OmniRouteProvider
from jarvis.llm_pollinations import PollinationsProvider


class FakeCall:
    def __init__(self, timeout):
        self.timeout = timeout
        self.seen_timeout = None

    def __call__(self, _message):
        self.seen_timeout = self.timeout
        return {"content": "ok"}


def test_pollinations_keeps_its_configured_timeout():
    call = FakeCall(timeout=60.0)
    provider = PollinationsProvider(call)
    assert provider.timeout == 60.0
    assert provider.respond([{"role": "user", "content": "hi"}],
                            timeout=provider.timeout) == "ok"
    assert call.seen_timeout == 60.0
    assert call.timeout == 60.0


def test_omniroute_keeps_its_configured_timeout():
    call = FakeCall(timeout=35.0)
    provider = OmniRouteProvider(call)
    assert provider.timeout == 35.0
    assert provider.respond([{"role": "user", "content": "hi"}],
                            timeout=provider.timeout) == "ok"
    assert call.seen_timeout == 35.0
    assert call.timeout == 35.0
