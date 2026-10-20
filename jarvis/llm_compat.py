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

def _custom_providers_file() -> "Path":
    from pathlib import Path
    # Next to the data dir is fine; ChatApp passes its data_dir in.
    return Path(_custom_dir) / "custom_providers.json" if _custom_dir else \
        Path.home() / ".jarvis" / "custom_providers.json"


_custom_dir: Optional[str] = None


def set_custom_dir(path: str) -> None:
    global _custom_dir
    _custom_dir = path


def get_custom_providers() -> Dict[str, Dict[str, str]]:
    import json
    try:
        return json.loads(_custom_providers_file().read_text())
    except Exception:
        return {}


def add_custom_provider(name: str, base_url: str, model: str) -> None:
    import json
    name = name.strip().lower()
    if not name or not base_url.startswith(("http://", "https://")):
        raise ValueError("need a name and an http(s) base_url")
    providers = get_custom_providers()
    providers[name] = {"base_url": base_url.rstrip("/"), "model": model.strip()}
    f = _custom_providers_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(providers, indent=2))
    tmp.replace(f)


def all_presets() -> Dict[str, Dict[str, str]]:
    merged = dict(PRESETS)
    merged.update(get_custom_providers())
    return merged
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
    # Google AI Studio's current key format (2025+): "AQ." + a long
    # opaque body (~50 chars). Length-guarded so a stray short "AQ."
    # string is never claimed as a key.
    if k.startswith("AQ.") and len(k) >= 40:
        return "gemini"
    return None


def probe_key(key: str, timeout: float = 15.0) -> Optional[str]:
    """DEPRECATED — DO NOT CALL. F-12.

    This function sprayed the raw API key as a Bearer token at up to 13
    providers' /chat/completions endpoints to "identify" it: twelve
    strangers logging a key that isn't theirs, sequential, ~100s hang.
    Per the owner's decision (Option A), /key no longer probes on
    fingerprint miss — it asks for the explicit /key <provider> <key>
    form instead.

    Kept (neutered) for API compatibility only. Always returns None and
    performs ZERO network calls.
    """
    _ = (key, timeout)
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
        "model": "gemini-2.5-flash",  # free tier (2.5-pro needs billing; use /provider to override)
    },
    "chutes": {
        "base_url": "https://llm.chutes.ai/v1",
        "model": "deepseek-ai/DeepSeek-R1",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "xai": {
        "base_url": "https://api.x.ai/v1",
        "model": "grok-4",
    },
    "together": {
        "base_url": "https://api.together.xyz/v1",
        "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    },
    "fireworks": {
        "base_url": "https://api.fireworks.ai/inference/v1",
        "model": "accounts/fireworks/models/llama-v3p3-70b-instruct",
    },
    "perplexity": {
        "base_url": "https://api.perplexity.ai",
        "model": "sonar-pro",
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


def _get_keys(secret_name: str, data_dir: Optional[str] = None) -> List[str]:
    """All keys for a provider: keyring first, env fallback.

    Numbered env vars allow many keys without the keyring:
    JARVIS_GROQ_KEYS="gsk_aaa,gsk_bbb" (comma-separated).
    """
    keys: List[str] = []
    try:
        from jarvis.config import Secrets
        secrets = Secrets(data_dir=data_dir)
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
        """Honest health check: validates the key with a real 1-token
        /chat/completions call. The old /models check lied — several
        providers leave /models public (200 for ANY key) or 401 valid
        keys. This costs one tiny request per startup for the truth."""
        if not self.keys:
            return False, f"{self.name}: no keys stored (use /key {self.name} <key>)"
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
            "stream": False,
        }).encode("utf-8")
        try:
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions", data=body,
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {self.keys[0]}"},
                method="POST")
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp.read(1024)
            return True, f"{self.name} up ({len(self.keys)} key(s), key works)"
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                return False, (f"{self.name}: key rejected ({exc.code}) — "
                               f"check the key with /keys")
            return True, (f"{self.name} reachable ({len(self.keys)} key(s), "
                          f"chat: {exc.code} — may still work)")
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
        # The chain honors per-provider .timeout (getattr(provider,
        # "timeout", None) or FALLBACK_TIMEOUT). Without this, keyed
        # providers get 5s — starving slow free-tier models (550B on
        # OpenRouter routinely exceeds 5s first-token). Same F-02 class
        # of bug as OllamaProvider.timeout.
        self.timeout = call.timeout

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
                          quiet: bool = False,
                          data_dir: Optional[str] = None) -> List[CompatProvider]:
    """Build providers for every preset with stored keys. Keyless presets
    are skipped here (Pollinations covers that)."""
    providers = []
    for pname, preset in all_presets().items():
        if only is not None and pname not in only:
            continue
        keys = _get_keys(f"{pname}_api_key", data_dir=data_dir)
        if not keys:
            continue
        call = CompatCall(pname, preset["base_url"], preset["model"], keys)
        ok, msg = call.check_health()
        if not quiet:
            print(f"[llm] {msg}")
        if ok:
            providers.append(CompatProvider(call))
    return providers
