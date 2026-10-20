"""JARVIS v2 — Pollinations keyless cloud provider.

Pollinations.ai offers a FREE text API with no signup, no API key, no
credit card: https://text.pollinations.ai/openai (OpenAI-compatible).

This is the zero-hassle cloud brain: it works the second JARVIS starts,
nothing for the owner to create or paste. Trade-off vs keyed providers:
smaller models, fair-use rate limits, prompts may be public. It sits in
the FallbackChain AFTER the keyed providers (Gemini/Groq/NVIDIA/OpenRouter)
and BEFORE the stub — free power with zero setup.

Typed errors route through the chain like every other provider.
"""

from __future__ import annotations

import json
import sys
import urllib.request
import urllib.error
from typing import Any, Dict, List

from jarvis.brain import ProviderHTTPError

BASE_URL = "https://text.pollinations.ai/openai"
DEFAULT_MODEL = "openai"  # pollinations' default open model route
TIMEOUT = 60.0


class PollinationsError(Exception):
    pass


class PollinationsConnectionError(PollinationsError, ConnectionError):
    pass


class PollinationsTimeoutError(PollinationsError, TimeoutError):
    pass


class PollinationsHTTPError(PollinationsError, ProviderHTTPError):
    pass


def _to_openai_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for m in messages:
        role = str(m.get("role", "user"))
        if role not in ("system", "user", "assistant"):
            role = "user"
        out.append({"role": role, "content": str(m.get("content") or "")})
    return out


class PollinationsCall:
    """Callable: messages -> {"content": ...}. No key, no signup."""

    def __init__(self, model: str = DEFAULT_MODEL,
                 timeout: float = TIMEOUT) -> None:
        self.model = model
        self.timeout = timeout

    def check_health(self) -> tuple:
        try:
            req = urllib.request.Request(
                f"{BASE_URL}/models",
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            n = len(data.get("data", data if isinstance(data, list) else []))
            return True, f"pollinations up ({n} models, keyless)"
        except Exception as exc:
            return False, f"pollinations unreachable ({exc})"

    def __call__(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        body = json.dumps({
            "model": self.model,
            "messages": _to_openai_messages(messages),
            "stream": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{BASE_URL}/chat/completions", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            raise PollinationsHTTPError(exc.code, str(exc)) from exc
        except TimeoutError as exc:
            raise PollinationsTimeoutError(str(exc)) from exc
        except (ConnectionError, OSError) as exc:
            raise PollinationsConnectionError(str(exc)) from exc
        try:
            content = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise PollinationsError(
                f"bad response shape: {exc}") from exc
        return {"content": str(content)}


class PollinationsProvider:
    """Duck-type provider for brain.FallbackChain."""

    def __init__(self, call: PollinationsCall,
                 name: str = "pollinations") -> None:
        self._call = call
        self.name = name
        self.keys: List[str] = []  # keyless — nothing to rotate
        # Preserve the provider's configured network timeout. Without this,
        # FallbackChain's 5s default overwrites PollinationsCall.TIMEOUT (60s)
        # and makes a healthy but slower free model look exhausted.
        self.timeout = call.timeout

    def respond(self, message: Any, key_index: int = 0,
                timeout: float = 5.0) -> str:
        prev = self._call.timeout
        try:
            self._call.timeout = timeout
            result = self._call(message)
        finally:
            self._call.timeout = prev
        return str(result.get("content", ""))


def make_pollinations_call(model: str = DEFAULT_MODEL,
                           quiet: bool = False):
    """PollinationsCall if reachable, else None (loud reason)."""
    call = PollinationsCall(model=model)
    ok, msg = call.check_health()
    if ok:
        if not quiet:
            print(f"[llm] {msg}")
        return call
    if not quiet:
        print(f"[llm] Pollinations unavailable: {msg}", file=sys.stderr)
    return None
