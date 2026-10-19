"""Layered, validated, crash-safe configuration for JARVIS v2.

Promoted from the proven settings_manager seed (~/workspace/learning).
v2 adaptations:
  * Corrupt config file -> quarantined aside AND ConfigError raised.
    Never silent defaults, never wiped data.
  * Secrets live outside the file: OS keyring first, then environment.
  * Secret values are never logged: redacted in reprs and log helpers.

Storage format is JSON (stdlib only). No new dependencies.
"""

from __future__ import annotations

import copy
import glob
import json
import logging
import os
import re
import sys
import tempfile
import time

__all__ = [
    "ConfigError",
    "Field",
    "ValidationError",
    "Secrets",
    "Config",
    "deep_merge",
    "default_schema",
    "redact_for_log",
    "SECRET_KEYS",
]

log = logging.getLogger("jarvis.config")

# Secret names known to v2. Anything under these names is redacted in logs.
SECRET_KEYS = frozenset({
    "gemini_api_key",
    "fish_api_key",
    "elevenlabs_api_key",
    "telegram_bot_token",
    "openrouter_api_key",
    "groq_api_key",
    "tavily_api_key",
    "phone_pin",
})

# Extra key-name fragments that mark a value as secret even if the exact
# name is unknown (defence in depth for redact_for_log).
_SECRET_HINT = re.compile(r"(api[_-]?key|token|secret|password|passwd|pin)$",
                          re.IGNORECASE)


class ConfigError(Exception):
    """Config is unusable (corrupt file, no keyring backend, ...)."""


# ---------------------------------------------------------------------------
# Small utilities (proven: carried over from the settings_manager seed)
# ---------------------------------------------------------------------------

def deep_merge(base: dict, override: dict) -> dict:
    """Return a new dict: ``override`` wins; nested dicts merge recursively."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _split(path: str) -> list[str]:
    return path.split(".")


_MISSING = object()


def _get_path(data: dict, parts: list[str]):
    node = data
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _path_exists(data: dict, parts: list[str]) -> bool:
    node = data
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


def _delete_path(data: dict, parts: list[str]) -> None:
    node = data
    for part in parts[:-1]:
        if not isinstance(node, dict):
            return
        node = node.get(part)
    if isinstance(node, dict):
        node.pop(parts[-1], None)


def _prune_empty(data: dict) -> None:
    for key in list(data.keys()):
        value = data[key]
        if isinstance(value, dict):
            _prune_empty(value)
            if not value:
                del data[key]


def _set_path(data: dict, parts: list[str], value) -> None:
    node = data
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[parts[-1]] = value


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class Field:
    """Validation spec for one leaf setting.

    Strictness (deliberate, learned from v1's C-B4):
      * ``bool`` is NOT accepted where ``int``/``float`` is expected and
        vice versa (Python's ``isinstance(True, int)`` trap).
      * ``int`` IS accepted where ``float`` is expected (lossless widening).
      * No other coercion, ever: ``""`` for a list, ``"true"`` for a bool
        are rejected, never converted.
    """

    def __init__(self, type, default, *, min=None, max=None,
                 choices=None, item_type=None):
        self.type = type
        self.default = default
        self.min = min
        self.max = max
        self.choices = choices
        self.item_type = item_type


def _walk_schema(schema: dict, prefix: str = ""):
    for key, node in schema.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(node, Field):
            yield path, node
        elif isinstance(node, dict):
            yield from _walk_schema(node, path)
        else:
            raise TypeError(f"Schema node at {path!r} must be Field or dict")


def _type_matches(value, ftype) -> bool:
    if ftype is bool:
        return isinstance(value, bool)
    if ftype is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if ftype is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if ftype is str:
        return isinstance(value, str)
    if ftype is list:
        return isinstance(value, list)
    if ftype is dict:
        return isinstance(value, dict)
    return False


def _validate_value(path: str, value, field: Field) -> list[str]:
    """Human-readable problems; empty means valid."""
    problems = []
    if not _type_matches(value, field.type):
        expected = field.type.__name__
        problems.append(
            f"{path}: expected {expected}, got "
            f"{type(value).__name__} ({value!r}) — rejected, not coerced"
        )
        return problems
    if field.choices is not None and value not in field.choices:
        problems.append(f"{path}: {value!r} not in allowed choices {field.choices}")
    if field.min is not None and isinstance(value, (int, float)) and value < field.min:
        problems.append(f"{path}: {value!r} below minimum {field.min}")
    if field.max is not None and isinstance(value, (int, float)) and value > field.max:
        problems.append(f"{path}: {value!r} above maximum {field.max}")
    if field.type is list and field.item_type is not None:
        for i, item in enumerate(value):
            if not _type_matches(item, field.item_type):
                problems.append(
                    f"{path}[{i}]: expected {field.item_type.__name__}, got "
                    f"{type(item).__name__} ({item!r})"
                )
    return problems


def _canonicalise(value, field: Field):
    if field.type is float and isinstance(value, int) and not isinstance(value, bool):
        return float(value)
    return copy.deepcopy(value)


def _build_defaults(schema: dict) -> dict:
    defaults: dict = {}
    for path, field in _walk_schema(schema):
        _set_path(defaults, _split(path), copy.deepcopy(field.default))
    return defaults


class ValidationError:
    """One rejected value. Collected, never raised, during load/save."""

    def __init__(self, path: str, message: str, rejected_value=None):
        self.path = path
        self.message = message
        self.rejected_value = rejected_value

    def __str__(self):
        return f"[{self.path}] {self.message}"


# ---------------------------------------------------------------------------
# Secrets: OS keyring first, environment fallback. Never logged.
# ---------------------------------------------------------------------------

class _WinCredBackend:
    """Windows Credential Manager via ctypes — no dependencies.

    Stores secrets as generic credentials under
    ``<service>/<name>``. Only constructed on win32; every call is
    guarded so a failure degrades to "no backend" instead of a crash.
    """

    def __init__(self, service: str) -> None:
        import ctypes
        from ctypes import wintypes
        self._service = service
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

        class CREDENTIALW(ctypes.Structure):
            _fields_ = [
                ("Flags", wintypes.DWORD),
                ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR),
                ("LastWritten", wintypes.FILETIME),
                ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.c_void_p),
                ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD),
                ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR),
                ("UserName", wintypes.LPWSTR),
            ]

        self._CREDENTIALW = CREDENTIALW
        self._CredWriteW = advapi32.CredWriteW
        self._CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), wintypes.DWORD]
        self._CredWriteW.restype = wintypes.BOOL
        self._CredReadW = advapi32.CredReadW
        self._CredReadW.argtypes = [wintypes.LPWSTR, wintypes.DWORD,
                                    wintypes.DWORD,
                                    ctypes.POINTER(ctypes.POINTER(CREDENTIALW))]
        self._CredReadW.restype = wintypes.BOOL
        self._CredFree = advapi32.CredFree
        self._CredFree.argtypes = [ctypes.c_void_p]
        # Sanity probe: read a name that cannot exist.
        self.get_password("definitely-not-a-real-credential-xyz")

    def _target(self, name: str) -> str:
        return f"{self._service}/{name}"

    def get_password(self, service: str, name: str):  # noqa: ARG002
        import ctypes
        from ctypes import wintypes
        pcred = ctypes.POINTER(self._CREDENTIALW)()
        ok = self._CredReadW(self._target(name), 1, 0, ctypes.byref(pcred))
        if not ok:
            return None
        try:
            cred = pcred.contents
            size = cred.CredentialBlobSize
            if not size:
                return None
            raw = ctypes.string_at(cred.CredentialBlob, size)
            return raw.decode("utf-16-le")
        finally:
            self._CredFree(pcred)

    def set_password(self, service: str, name: str, value: str) -> None:  # noqa: ARG002
        import ctypes
        blob = value.encode("utf-16-le")
        buf = ctypes.create_string_buffer(blob)
        cred = self._CREDENTIALW()
        cred.Flags = 0
        cred.Type = 1  # CRED_TYPE_GENERIC
        cred.TargetName = self._target(name)
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = ctypes.cast(buf, ctypes.c_void_p)
        cred.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE
        cred.UserName = self._target(name)
        if not self._CredWriteW(ctypes.byref(cred), 0):
            raise OSError("CredWriteW failed")


class Secrets:
    """Secret lookup with redaction guarantees.

    Read order: OS keyring (service "JARVIS") -> ``JARVIS_<NAME>`` env var.
    Values are NEVER written to the config file and NEVER appear in logs;
    use :func:`redact_for_log` before logging anything that might contain
    them. ``repr(Secrets(...))`` shows names only.
    """

    SERVICE = "JARVIS"

    def __init__(self, extra_keys: set[str] | frozenset[str] | None = None):
        self._keys = frozenset(SECRET_KEYS) | frozenset(extra_keys or ())
        self._keyring = None
        self._wincred = None
        try:
            import keyring  # optional dependency
            # Probe the backend: some installs have keyring with no backend.
            try:
                keyring.get_keyring()
                self._keyring = keyring
            except Exception:
                self._keyring = None
        except ImportError:
            self._keyring = None
        if self._keyring is None and sys.platform == "win32":
            # No keyring package: use Windows Credential Manager directly
            # via ctypes. Real OS keyring, zero dependencies.
            try:
                self._wincred = _WinCredBackend(self.SERVICE)
            except Exception:
                self._wincred = None

    @property
    def keys(self) -> frozenset[str]:
        return self._keys

    @property
    def has_keyring(self) -> bool:
        return self._keyring is not None

    def get(self, name: str, default: str | None = None) -> str | None:
        """Return the secret value, or ``default``. Never logs the value."""
        if self._keyring is not None:
            try:
                value = self._keyring.get_password(self.SERVICE, name)
                if value:
                    return value
            except Exception as exc:
                log.warning("keyring read failed for %r: %s", name, exc)
        if self._wincred is not None:
            try:
                value = self._wincred.get_password(self.SERVICE, name)
                if value:
                    return value
            except Exception as exc:
                log.warning("wincred read failed for %r: %s", name, exc)
        return os.environ.get(f"JARVIS_{name.upper()}", default)

    def set(self, name: str, value: str) -> None:
        """Store a secret in the OS keyring. Env vars are read-only."""
        if self._keyring is not None:
            self._keyring.set_password(self.SERVICE, name, value)
            return
        if self._wincred is not None:
            self._wincred.set_password(self.SERVICE, name, value)
            return
        raise ConfigError(
            "no keyring backend available; cannot store secrets "
            "(set JARVIS_<NAME> env var instead, or install keyring)"
        )

    def __repr__(self) -> str:  # values never shown
        return f"Secrets(keys={sorted(self._keys)}, values=<redacted>)"


def _looks_secret(key: str, secret_keys: frozenset[str]) -> bool:
    kl = key.lower()
    return kl in secret_keys or bool(_SECRET_HINT.search(kl))


def redact_for_log(obj, secret_keys: frozenset[str] = SECRET_KEYS):
    """Return a copy of ``obj`` with secret values replaced by "***".

    Walks dicts and lists. A value is redacted when its key is a known
    secret name or looks like one (token/password/api_key/...).
    """
    if isinstance(obj, dict):
        return {
            k: ("***" if _looks_secret(str(k), secret_keys) else redact_for_log(v, secret_keys))
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        redacted = [redact_for_log(v, secret_keys) for v in obj]
        return type(obj)(redacted) if isinstance(obj, tuple) else redacted
    return obj


# ---------------------------------------------------------------------------
# The config manager
# ---------------------------------------------------------------------------

class Config:
    """Layered, validated, crash-safe config store.

    Layers (later wins): schema defaults < file contents < runtime overrides.
    Corrupt file -> quarantined aside + ConfigError raised (never wiped,
    never silent defaults). Use ``redact_for_log`` before logging exports.
    """

    def __init__(self, path: str, schema: dict,
                 overrides: dict | None = None,
                 secrets: Secrets | None = None):
        self.path = os.path.abspath(path)
        self.schema = schema
        self._fields = dict(_walk_schema(schema))
        self._defaults = _build_defaults(schema)
        self.overrides = copy.deepcopy(overrides or {})
        self.secrets = secrets or Secrets()
        self.errors: list[ValidationError] = []
        self._known: dict = {}
        self._unknown: dict = {}
        self._tmp_prefix = f".{os.path.basename(self.path)}.tmp-"

    # -- reading ---------------------------------------------------------

    def load(self) -> dict:
        """(Re)load from disk.

        Raises ConfigError if the file exists but is corrupt (it is
        quarantined aside first — bytes are never lost). Bad *values*
        keep defaults and are reported in ``self.errors`` (the C-B4 fix).
        """
        self.errors = []
        raw = self._read_raw_file()  # may raise ConfigError
        known: dict = {}
        for path, field in self._fields.items():
            parts = _split(path)
            if _path_exists(raw, parts):
                self._validate_leaf(path, _get_path(raw, parts), known)
            else:
                _set_path(known, parts, copy.deepcopy(field.default))

        unknown = copy.deepcopy(raw)
        for path in self._fields:
            _delete_path(unknown, _split(path))
        _prune_empty(unknown)

        self._known = known
        self._unknown = unknown
        return self.export()

    def _validate_leaf(self, path: str, value, known: dict) -> None:
        field = self._fields[path]
        problems = _validate_value(path, value, field)
        if problems:
            for problem in problems:
                self.errors.append(ValidationError(path, problem, value))
            _set_path(known, _split(path), copy.deepcopy(field.default))
        else:
            _set_path(known, _split(path), _canonicalise(value, field))

    def _read_raw_file(self) -> dict:
        """Read raw JSON. Missing file -> {}. Corrupt -> quarantine + raise."""
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "rb") as fh:
                raw_bytes = fh.read()
        except OSError as exc:
            raise ConfigError(f"cannot read config {self.path!r}: {exc}") from exc
        try:
            data = json.loads(raw_bytes.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            dest = self._quarantine_corrupt(raw_bytes)
            raise ConfigError(
                f"config file corrupt ({exc}); quarantined to {dest}, "
                "nothing was wiped"
            ) from exc
        if not isinstance(data, dict):
            dest = self._quarantine_corrupt(raw_bytes)
            raise ConfigError(
                f"config top-level is {type(data).__name__}, not an object; "
                f"quarantined to {dest}, nothing was wiped"
            )
        return data

    def _quarantine_corrupt(self, raw_bytes: bytes) -> str:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dest = f"{self.path}.corrupt-{stamp}"
        try:
            with open(dest, "wb") as fh:
                fh.write(raw_bytes)
                fh.flush()
                os.fsync(fh.fileno())
        except OSError as exc:
            log.error("could not quarantine corrupt config: %s", exc)
        return dest

    # -- accessors -------------------------------------------------------

    def get(self, path: str, default=None):
        value = _get_path(self.export(), _split(path))
        return default if value is None else value

    def set(self, path: str, value) -> None:
        """Stage a value in the file layer. Raises ValueError if invalid."""
        if path not in self._fields:
            raise KeyError(f"unknown setting {path!r}")
        field = self._fields[path]
        problems = _validate_value(path, value, field)
        if problems:
            for problem in problems:
                self.errors.append(ValidationError(path, problem, value))
            raise ValueError("; ".join(problems))
        _set_path(self._known, _split(path), _canonicalise(value, field))

    def export(self) -> dict:
        """Effective config: defaults < file < overrides (new dict)."""
        merged = deep_merge(self._defaults, self._known)
        merged = deep_merge(merged, self._unknown)
        return deep_merge(merged, self.overrides)

    def export_redacted(self) -> dict:
        """Export safe for logs: secret-looking values replaced."""
        return redact_for_log(self.export(), self.secrets.keys)

    # -- writing ---------------------------------------------------------

    def save(self) -> None:
        """Persist the file layer atomically. Raises OSError on I/O failure.

        Re-reads the file from disk and merges our layer on top, so keys
        written by another process between load() and save() survive.
        """
        self.errors = []
        disk = self._read_raw_file_quiet()
        payload = deep_merge(disk, self._known)
        payload = deep_merge(payload, self._unknown)
        self._atomic_write(payload)

    def _read_raw_file_quiet(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _atomic_write(self, payload: dict) -> None:
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        data = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")

        fd, tmp_path = tempfile.mkstemp(dir=directory,
                                        prefix=self._tmp_prefix,
                                        suffix=".json")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            if os.path.exists(self.path):
                self._rotate_backup()
            os.replace(tmp_path, self.path)  # atomic on POSIX and Windows
            self._fsync_dir(directory)
            self._cleanup_stale_tmps(directory)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _rotate_backup(self) -> None:
        try:
            with open(self.path, "rb") as src:
                content = src.read()
            with open(self.path + ".bak", "wb") as dst:
                dst.write(content)
                dst.flush()
                os.fsync(dst.fileno())
        except OSError:
            pass  # backup is best-effort; the atomic write still protects data

    @staticmethod
    def _fsync_dir(directory: str) -> None:
        try:
            dfd = os.open(directory, os.O_DIRECTORY)
        except (OSError, AttributeError):
            return  # Windows has no O_DIRECTORY; os.replace is enough there
        try:
            os.fsync(dfd)
        except OSError:
            pass
        finally:
            os.close(dfd)

    def _cleanup_stale_tmps(self, directory: str) -> None:
        pattern = os.path.join(directory, self._tmp_prefix + "*")
        for stray in glob.glob(pattern):
            try:
                os.unlink(stray)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Default v2 schema (mirrors the v1 settings panel, C-B4 fields fixed)
# ---------------------------------------------------------------------------

def default_schema() -> dict:
    """Schema with the v1 corruption bugs fixed.

    ``telegram.allowed_user_ids`` is a *list* defaulting to ``[]``: v1's
    panel rewrote it to ``""`` on every OK; here ``""`` is rejected and
    reported, never silently stored.
    """
    return {
        "voice": {
            "engine": Field(str, "piper",
                            choices=["piper", "fish", "elevenlabs"]),
            "speech_language": Field(str, "auto",
                                     choices=["auto", "en", "hi"]),
            "sensitivity": Field(float, 0.5, min=0.0, max=1.0),
        },
        "brain": {
            "temperature": Field(float, 0.7, min=0.0, max=2.0),
            "max_tokens": Field(int, 1024, min=1, max=32000),
        },
        "telegram": {
            "enabled": Field(bool, False),
            "allowed_user_ids": Field(list, [], item_type=int),
        },
        "safety": {
            "watching_eyes": Field(bool, False),
            "watch_interval_sec": Field(int, 60, min=5, max=3600),
        },
    }
