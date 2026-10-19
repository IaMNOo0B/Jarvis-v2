"""JARVIS v2 — universal OpenAI-compatible provider with key rotation.

One class serves EVERY OpenAI-compatible free API (Groq, OpenRouter,
NVIDIA NIM, Mistral, Cerebras, Cohere, Gemini, Cloudflare, …). Each
provider gets its own key list; the FallbackChain rotates keys on
401/403/429 and moves to the next provider on 5xx/timeout.

Keys live in the OS keyring (via jarvis.config.Secrets), never in files,
never in logs. Add one with the /key chat command:
    /key groq gsk_xxxxxxxxxxxxxxxx
"""

from __future__ import annotations

import json
import sys
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from jarvis.brain import ProviderHTTPError

TIMEOUT = 60.0

# Key fingerprinting: prefix -> provider. Lets the owner paste a key
# without naming the provider — the bot figures it out.
KEY_PREFIXES: Dict[str, str] = {
    "gsk_": "groq",
    "sk-or-": "openrouter",
    "nvapi-": "nvidia",
    "AIza": "gemini",
    "csk-": "cerebras",
    "csk_": "cerebras",
    "pplx-": "perplexity",
    "xai-": "xai",
    "sk-ant-": "anthropic",
    "hf_": "huggingface",
    "fw_": "fireworks",
}


def fingerprint_key(key: str) -> Optional[str]:
    """Identify the provider from the key's prefix. No network needed."""
    k = key.strip()
    for prefix, provider in KEY_PREFIXES.items():
        if k.startswith(prefix):
            return provider
    return None


def probe_key(key: str, timeout: float = 8.0) -> Optional[str]:
    """Ask each preset's /models endpoint: 200 = this provider, 401 = not.

    Only used when the prefix is unknown. The key is sent solely to the
    provider endpoints it might belong to — its intended use.
    """
    import urllib.request
    import urllib.error
    for pname, preset in PRESETS.items():
        try:
            req = urllib.request.Request(
                f"{preset['base_url'].rstrip('/')}/models",
                headers={"Authorization": f"Bearer {key.strip()}"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return pname
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                continue  # key rejected here — not this provider
            # Other HTTP codes: endpoint reachable, key might be fine
            # (some providers 403 /models on valid keys). Keep looking.
            continue
        except Exception:
            continue
    return None
PRESETS: Dict[str, Dict[str, str]] = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "openai/gpt-oss-120b",  # 120B, 30 RPM free
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "nvidia/nemotron-3-ultra-550b-a55b:free",  # 550B, 50/day
    },
    "nvidia": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "moonshotai/kimi-k3",  # 2.8T, trial
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "model": "mistral-small-latest",
    },
    "cerebras": {
        "base_url": "https://api.cerebras.ai/v1",
        "model": "llama-3.3-70b",
    },
    "cohere": {
        "base_url": "https://api.cohere.ai/compatibility/v1",
        "model": "command-r-plus",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-2.5-pro",  # frontier, permanent free tier
    },
    "chutes": {
        "base_url": "https://llm.chutes.ai/v1",
        "model": "deepseek-ai/DeepSeek-R1",
    },
}


class CompatError(Exception):
    pass


class CompatConnectionError(CompatError, ConnectionError):
    pass


class CompatTimeoutError(CompatError, TimeoutError):
    pass


class CompatHTTPError(CompatError, ProviderHTTPError):
    pass


def _to_openai_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for m in messages:
        role = str(m.get("role", "user"))
        if role not in ("system", "user", "assistant"):
            role = "user"
        out.append({"role": role, "content": str(m.get("content") or "")})
    return out


def _get_keys(secret_name: str) -> List[str]:
    """All keys for a provider: keyring first, env fallback.

    Numbered env vars allow many keys without the keyring:
    JARVIS_GROQ_KEYS="gsk_aaa,gsk_bbb" (comma-separated).
    """
    keys: List[str] = []
    try:
        from jarvis.config import Secrets
        secrets = Secrets()
        # Keyring holds one value per name; numbered slots hold the rest.
        first = secrets.get(secret_name)
        if first:
            keys.append(first)
        i = 2
        while True:
            extra = secrets.get(f"{secret_name}_{i}")
            if not extra:
                break
            keys.append(extra)
            i += 1
    except Exception:
        pass
    env = (os_env(f"JARVIS_{secret_name.upper()}_KEYS")
           or os_env(f"JARVIS_{secret_name.upper()}"))
    if env:
        keys.extend(k.strip() for k in env.split(",") if k.strip())
    # Deduplicate, preserve order.
    seen, unique = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k)
            unique.append(k)
    return unique


def os_env(name: str) -> Optional[str]:
    import os
    return os.environ.get(name)


class CompatCall:
    """Single provider, many keys. stdlib only."""

    def __init__(self, name: str, base_url: str, model: str,
                 keys: List[str], timeout: float = TIMEOUT) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.keys = list(keys)
        self.timeout = timeout

    def check_health(self) -> tuple:
        if not self.keys:
            return False, f"{self.name}: no keys stored (use /key {self.name} <key>)"
        try:
            req = urllib.request.Request(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.keys[0]}"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                resp.read(1024)
            return True, f"{self.name} up ({len(self.keys)} key(s))"
        except urllib.error.HTTPError as exc:
            # 401 here just means /models needs different scope — the key
            # may still work for chat. Report honestly.
            return True, f"{self.name} reachable ({len(self.keys)} key(s), /models: {exc.code})"
        except Exception as exc:
            return False, f"{self.name} unreachable ({exc})"

    def _post(self, messages: List[Dict[str, Any]], key: str) -> Dict[str, Any]:
        body = json.dumps({
            "model": self.model,
            "messages": _to_openai_messages(messages),
            "stream": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {key}"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            raise CompatHTTPError(exc.code, str(exc)) from exc
        except TimeoutError as exc:
            raise CompatTimeoutError(str(exc)) from exc
        except (ConnectionError, OSError) as exc:
            raise CompatConnectionError(str(exc)) from exc
        try:
            content = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise CompatError(f"bad response shape: {exc}") from exc
        return {"content": str(content)}

    def __call__(self, messages: List[Dict[str, Any]], key_index: int = 0) -> Dict[str, Any]:
        if not self.keys:
            raise CompatError(f"{self.name}: no keys stored")
        key = self.keys[key_index % len(self.keys)]
        return self._post(messages, key)


class CompatProvider:
    """Duck-type provider for brain.FallbackChain with key rotation."""

    def __init__(self, call: CompatCall, name: Optional[str] = None) -> None:
        self._call = call
        self.name = name or call.name
        self.keys = call.keys  # the chain rotates on 401/403/429

    def respond(self, message: Any, key_index: int = 0,
                timeout: float = 5.0) -> str:
        prev = self._call.timeout
        try:
            self._call.timeout = timeout
            result = self._call(message, key_index=key_index)
        finally:
            self._call.timeout = prev
        return str(result.get("content", ""))


def make_compat_providers(only: Optional[List[str]] = None,
                          quiet: bool = False) -> List[CompatProvider]:
    """Build providers for every preset with stored keys. Keyless presets
    are skipped here (Pollinations covers that)."""
    providers = []
    for pname, preset in PRESETS.items():
        if only is not None and pname not in only:
            continue
        keys = _get_keys(f"{pname}_api_key")
        if not keys:
            continue
        call = CompatCall(pname, preset["base_url"], preset["model"], keys)
        ok, msg = call.check_health()
        if not quiet:
            print(f"[llm] {msg}")
        if ok:
            providers.append(CompatProvider(call))
    return providers
