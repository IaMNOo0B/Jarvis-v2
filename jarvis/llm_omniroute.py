"""JARVIS v2 — OmniRoute brain provider.

OmniRoute (diegosouzapw/OmniRoute, MIT) is a free self-hosted AI gateway:
one OpenAI-compatible endpoint, 375 providers (150+ free), 1,400+ models.
JARVIS talks to it like any OpenAI-compatible API; OmniRoute handles
provider routing. Free providers (Kiro AI, OpenCode Free, …) need no
signup and no per-provider keys.

Setup (the owner's 2-minute job, once):
  1. npm install -g omniroute && omniroute
     (dashboard opens at http://localhost:20128)
  2. Dashboard → Endpoints → copy the generated key
  3. Paste it into JARVIS Settings → API Keys → OmniRoute
     (stored in the OS keyring, never in a file)

The provider plugs into brain.FallbackChain as a cloud provider:
local Ollama → OmniRoute → stub. Typed errors route correctly:
connection/timeout → next provider; 401/403 → rotate key (none —
single key, so next provider); 408/429/5xx → next provider.

Model choice: set in config (brain.omniroute_model). Good free picks
(via freellm.net's directory, Oct 2026):
  - google/gemini-2.5-flash  — most capable free tier
  - groq/llama-3.3-70b       — fastest inference
  - nvidia/deepseek-r1       — reasoning, free via NIM
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from jarvis.brain import ProviderHTTPError

DEFAULT_BASE_URL = "http://localhost:20128/v1"
DEFAULT_MODEL = "google/gemini-2.5-flash"
DEFAULT_TIMEOUT = 60.0


class OmniRouteError(Exception):
    """Base for OmniRoute client errors."""


class OmniRouteConnectionError(OmniRouteError, ConnectionError):
    """Gateway unreachable — is `omniroute` running?"""


class OmniRouteTimeoutError(OmniRouteError, TimeoutError):
    """Gateway did not answer in time."""


class OmniRouteHTTPError(OmniRouteError, ProviderHTTPError):
    """HTTP failure; carries .status for the fallback chain."""


def _get_token() -> Optional[str]:
    """Bearer token: OS keyring first, env fallback. Never logged."""
    try:
        from jarvis.config import Secrets
        token = Secrets().get("omniroute_api_key")
        if token:
            return token
    except Exception:
        pass
    return os.environ.get("OMNIROUTE_API_KEY") or os.environ.get(
        "JARVIS_OMNIROUTE_API_KEY")


def _to_openai_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Strip Brain-internal keys; the gateway gets clean OpenAI messages."""
    out = []
    for m in messages:
        role = str(m.get("role", "user"))
        if role not in ("system", "user", "assistant"):
            role = "user"
        out.append({"role": role, "content": str(m.get("content") or "")})
    return out


class OmniRouteCall:
    """Callable: messages -> {"content": ...} via the gateway's
    OpenAI-compatible /chat/completions. stdlib only."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL,
                 model: str = DEFAULT_MODEL,
                 timeout: float = DEFAULT_TIMEOUT,
                 token: Optional[str] = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._token = token  # lazily resolved; None until needed

    def _headers(self) -> Dict[str, str]:
        token = self._token or _get_token()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def check_health(self) -> tuple:
        """(ok, message). Distinguishes: down / no models / healthy."""
        try:
            req = urllib.request.Request(
                f"{self.base_url}/models", headers=self._headers())
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            n = len(data.get("data", []))
            return True, f"omniroute up at {self.base_url} ({n} models)"
        except urllib.error.HTTPError as exc:
            return False, f"omniroute HTTP {exc.code} at {self.base_url}"
        except Exception as exc:
            return False, (f"omniroute not reachable at {self.base_url} "
                           f"({exc}). Is it running? Try: omniroute")

    def __call__(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        body = json.dumps({
            "model": self.model,
            "messages": _to_openai_messages(messages),
            "stream": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=body,
            headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            raise OmniRouteHTTPError(exc.code, str(exc)) from exc
        except TimeoutError as exc:
            raise OmniRouteTimeoutError(str(exc)) from exc
        except (ConnectionError, OSError) as exc:
            raise OmniRouteConnectionError(str(exc)) from exc
        try:
            content = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise OmniRouteError(
                f"bad gateway response shape: {exc}") from exc
        return {"content": str(content)}


class OmniRouteProvider:
    """Duck-type provider for brain.FallbackChain (.name, .keys, .respond)."""

    def __init__(self, call: OmniRouteCall, name: str = "omniroute") -> None:
        self._call = call
        self.name = name
        self.keys: List[str] = []  # single gateway key; nothing to rotate
        # Cloud first-token latency can exceed the chain's 5s base timeout.
        self.timeout = 15.0

    def respond(self, message: Any, key_index: int = 0,
                timeout: float = 5.0) -> str:
        prev = self._call.timeout
        try:
            self._call.timeout = timeout
            result = self._call(message)
        finally:
            self._call.timeout = prev
        # Plain text — the Brain re-parses TOOL:/ARGS: lines itself.
        return str(result.get("content", ""))


def make_omniroute_call(base_url: str = DEFAULT_BASE_URL,
                        model: str = DEFAULT_MODEL,
                        timeout: float = DEFAULT_TIMEOUT,
                        quiet: bool = False):
    """OmniRouteCall if the gateway is healthy, else None (loud reason)."""
    call = OmniRouteCall(base_url=base_url, model=model, timeout=timeout)
    ok, msg = call.check_health()
    if ok:
        if not quiet:
            print(f"[llm] {msg} — model {model}")
        return call
    if not quiet:
        print(f"[llm] OmniRoute unavailable: {msg}", file=sys.stderr)
    return None
