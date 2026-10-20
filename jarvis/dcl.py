"""Data Classification Layer (DCL) — SEC12.

Deterministic pipeline stage between the gate and the network. Every piece of
content bound for the cloud gets exactly one class:

    PUBLIC     - no privacy impact if disclosed. Send freely.
    PERSONAL   - about the user but not exploitable. Send, feed-logged.
    SENSITIVE  - exploitable with effort or embarrassing. Confirm-first.
    SECRET     - credential-equivalent. NEVER leaves the machine.

Detection tiers (cheapest first):
    Tier A - known-secrets registry: salted-hash fingerprints of registered
             secrets. Match = SECRET by construction (zero false positives).
    Tier B - secret patterns (regex + Luhn + decode-then-scan, 2 layers).
             Match = SECRET. Tuned for RECALL.
    Tier C - semantic PII baseline (regex). Email -> PERSONAL, identifiers
             -> SENSITIVE.

Doctrine: when in doubt, ESCALATE the class. False positives cost annoyance
(recoverable); false negatives cost leaks (irrecoverable). On ANY internal
error the classifier fails CLOSED to SENSITIVE, never PUBLIC.

Vault round-trip (Presidio/LLM-Guard pattern): substitute()/restore() swap
SECRET and PERSONAL spans for stable placeholders (<SECRET_1>,
<PERSONAL_1>, ...) so the model can reason about identity -- "is this the
same key as before?" -- without the raw value ever leaving the machine.
The placeholder -> value mapping lives in an in-memory Vault only: never
logged, never persisted, never sent.

Stdlib only: re, hashlib, hmac, base64, urllib.parse, os, json, time.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum
from urllib.parse import unquote_plus


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------

class DataClass(IntEnum):
    """Ordered so max() composes: a composite's class is the max of its parts."""
    PUBLIC = 0
    PERSONAL = 1
    SENSITIVE = 2
    SECRET = 3


@dataclass
class Finding:
    """One detection. Spans are relative to the text that was classified.

    detail is a SAFE human note (pattern name, layer) -- never the secret value.
    """
    data_class: DataClass
    tier: str            # "A", "B", "C", or "ERR"
    pattern: str
    start: int
    end: int
    detail: str = ""

    @property
    def masked_span(self) -> str:
        return f"[{self.start}:{self.end}]"


# ---------------------------------------------------------------------------
# Tier A -- known-secrets registry
# ---------------------------------------------------------------------------

class SecretRegistry:
    """Salted-hash fingerprints of known secrets.

    The VALUE is never stored -- only an HMAC-SHA256 digest plus its length.
    Matching slides a window of the secret's length over the text and compares
    digests, so the secret is found wherever it is pasted, with zero chance of
    a false positive on the system's own secrets.
    """

    def __init__(self, salt: bytes | None = None) -> None:
        self._salt: bytes = salt if salt is not None else os.urandom(32)
        self._entries: list[tuple[str, str, int]] = []  # (name, hexdigest, length)

    def _digest(self, value: str) -> str:
        return hmac.new(self._salt, value.encode("utf-8"), hashlib.sha256).hexdigest()

    def register_secret(self, name: str, value: str) -> None:
        """Register a secret. Only the salted hash is kept -- never the value."""
        if not value:
            return
        digest = self._digest(value)
        # Replace any prior registration under the same name.
        self._entries = [e for e in self._entries if e[0] != name]
        self._entries.append((name, digest, len(value)))

    def find_matches(self, text: str) -> list[Finding]:
        findings: list[Finding] = []
        n = len(text)
        for name, digest, length in self._entries:
            if length == 0 or length > n:
                continue
            # Only hash windows whose first char could plausibly start a secret.
            # (Full scan; texts here are prompts, not gigabytes.)
            for i in range(n - length + 1):
                window = text[i:i + length]
                # Cheap pre-filter: compare first digest byte via first chars is
                # not possible with HMAC; just hash. Bounded by text size.
                if self._digest(window) == digest:
                    findings.append(Finding(
                        DataClass.SECRET, "A", f"registered-secret:{name}",
                        i, i + length,
                        detail="exact fingerprint match -- SECRET by construction",
                    ))
        return findings

    # -- persistence (salt + digests only; values never touch disk) ----------

    def save(self, path: str) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({
                "salt": self._salt.hex(),
                "entries": [
                    {"name": n, "digest": d, "length": ln}
                    for n, d, ln in self._entries
                ],
            }, f)
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: str) -> "SecretRegistry":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        reg = cls(salt=bytes.fromhex(data["salt"]))
        for e in data["entries"]:
            reg._entries.append((e["name"], e["digest"], e["length"]))
        return reg


def load_registry(path: str) -> SecretRegistry:
    """Load a persisted secret registry (salt + digests, never values)."""
    return SecretRegistry.load(path)


# The registry's home inside the owner's data dir. Only salted HMAC-SHA256
# digests + lengths are ever written -- a secret VALUE never touches disk.
REGISTRY_FILENAME = "known_secrets.json"


def registry_path(data_dir: str) -> str:
    return os.path.join(data_dir, REGISTRY_FILENAME)


def load_or_create_registry(data_dir: str) -> SecretRegistry:
    """Load the data dir's registry, creating a fresh one if absent.

    A corrupt registry file is quarantined to '<name>.corrupt' and a fresh
    registry returned: startup must not die, but the owner should re-register
    (the quarantine file is the visible evidence)."""
    path = registry_path(data_dir)
    if os.path.exists(path):
        try:
            return SecretRegistry.load(path)
        except Exception:
            try:
                os.replace(path, path + ".corrupt")
            except OSError:
                pass
            return SecretRegistry()
    return SecretRegistry()


# ---------------------------------------------------------------------------
# Tier B -- secret patterns (decode-then-scan)
# ---------------------------------------------------------------------------

# (name, compiled regex) -- every match is SECRET.
_TIER_B_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("github-token",
     re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b")),
    ("openai-key",
     re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}\b")),
    ("aws-access-key",
     re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("telegram-bot-token",
     re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{35}\b")),
    ("private-key-block",
     re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
    ("labeled-secret",
     re.compile(r"(?i)\b(password|passwd|pwd|api[_-]?key|secret|client[_-]?secret"
                r"|auth[_-]?token|access[_-]?token)\s*[:=]\s*\S{4,}")),
    ("otp-code",
     re.compile(r"(?i)\b(?:otp|2fa|two-factor|verification code|auth code|"
                r"login code)\b.{0,30}?\b\d{6}\b")),
]

# 12 or 24 lowercase words in a row = seed-phrase SHAPE. Full BIP-39 wordlist
# validation is deferred (needs the wordlist file); shape-based now, recall-first.
_SEED_12 = re.compile(r"\b(?:[a-z]{3,8} ){11}[a-z]{3,8}\b")
_SEED_24 = re.compile(r"\b(?:[a-z]{3,8} ){23}[a-z]{3,8}\b")

# Credit-card candidate: 13-19 digits with optional separators, then Luhn.
_CARD_RE = re.compile(r"\b(?:\d[ \-\.]?){13,19}\b")

# Encoded blobs for decode-then-scan (up to 2 layers; deeper = suspicious).
_B64_RE = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")
_HEX_RE = re.compile(r"\b(?:0x)?[0-9a-fA-F]{32,}\b")
_URL_RE = re.compile(r"(?:%[0-9A-Fa-f]{2}){4,}")
_MAX_DECODE_BLOBS = 32
_MAX_DECODE_DEPTH = 2


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = ord(ch) - 48
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0 and len(digits) >= 13


def _shannon_entropy(s: str) -> float:
    from math import log2
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * log2(c / n) for c in freq.values())


_ENTROPY_RE = re.compile(r"[A-Za-z0-9+/=]{32,}")

_PRINTABLE_RE = re.compile(r"^[\x09\x0a\x0d\x20-\x7e]+$")


def _try_decode(kind: str, blob: str) -> str | None:
    """Decode one encoded blob. Returns printable text or None."""
    try:
        if kind == "b64":
            s = blob.strip()
            # Fix padding.
            s += "=" * (-len(s) % 4)
            raw = base64.b64decode(s, validate=True)
        elif kind == "hex":
            h = blob[2:] if blob.lower().startswith("0x") else blob
            if len(h) % 2 == 1:
                return None
            raw = bytes.fromhex(h)
        elif kind == "url":
            return unquote_plus(blob)
        else:
            return None
        text = raw.decode("utf-8", errors="strict")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    if not text or not _PRINTABLE_RE.match(text):
        return None
    return text


# ---------------------------------------------------------------------------
# Tier C -- semantic PII baseline (regex)
# ---------------------------------------------------------------------------

# (name, compiled regex, class)
_TIER_C_PATTERNS: list[tuple[str, re.Pattern, DataClass]] = [
    ("email", re.compile(
        r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
     DataClass.PERSONAL),
    ("phone-in", re.compile(
        r"(?:\+91[\s\-]?)?\b[6-9]\d{4}[\s\-]?\d{5}\b"),
     DataClass.SENSITIVE),
    ("phone-intl", re.compile(
        r"\+\d{1,3}[\s\-]\d{2,5}[\s\-]\d{3,}[0-9\s\-]*"),
     DataClass.SENSITIVE),
    ("aadhaar-shape", re.compile(
        r"\b\d{4}\s\d{4}\s\d{4}\b|\b\d{12}\b"),
     DataClass.SENSITIVE),
    ("address", re.compile(
        r"(?i)\b\d{1,5}\s+[A-Za-z][A-Za-z .]*?\b(street|st\.|road|rd\.|avenue|"
        r"ave\.|lane|sector|nagar|colony|marg|chowk)\b"),
     DataClass.SENSITIVE),
    ("pincode", re.compile(
        r"(?i)\bpin(?:code)?\s*[:=\-]?\s*\d{6}\b"),
     DataClass.SENSITIVE),
    ("money-amount", re.compile(
        r"(?:₹|\$|€|Rs\.?)\s?[\d,]+(?:\.\d{1,2})?"),
     DataClass.SENSITIVE),
    ("health-mention", re.compile(
        r"(?i)\b(diagnos(?:is|ed)|hospital|clinic|prescription|disease|"
        r"cancer|diabetes|doctor|medical|surgery|patient|pharmacy)\b"),
     DataClass.SENSITIVE),
]


# ---------------------------------------------------------------------------
# Placeholder round-trip -- the Vault (Team 16 steal #2; Presidio pattern,
# code-confirmed via microsoft/presidio + LLM Guard's Anonymize/Vault)
# ---------------------------------------------------------------------------
#
# redact() is one-way: the value is GONE from what the model sees, so the
# model cannot reason about identity ("is that the same key as before?")
# and a reply can never hand the value back to the user. The vault fixes
# both:
#
#   substitute(text)     -> SECRET/PERSONAL spans become stable
#                           placeholders (<SECRET_1>, <PERSONAL_1>, ...);
#                           the Vault keeps placeholder -> original.
#   restore(text, vault) -> placeholders in the model's reply are swapped
#                           back to the originals before display.
#
# Scope (deliberate): substitute() vaults SECRET and PERSONAL spans only.
# SENSITIVE spans pass through, exactly as redact() passes PERSONAL --
# callers that must withhold SENSITIVE content still use redact().
#
# Two Presidio FP-reducers ride along, in THIS path only (classify()'s
# behaviour and tests are untouched):
#   1. validate() hooks -- a recognizer may attach a shape validator; a
#      candidate that fails validation is NOT substituted (this is the
#      hook that lets Presidio beat raw regex on false positives).
#   2. Context boost -- a PERSONAL span near a label word ("key",
#      "token", "password", "api") is handled as SECRET: a "password
#      recovery email" is a credential path, not ordinary PII.

_PLACEHOLDER_RE = re.compile(r"<(SECRET|PERSONAL)_(\d+)>")


def _body_shape(body: str, lo: int, hi: int, charset: re.Pattern) -> bool:
    """Length + charset shape check -- the stdlib stand-in for a checksum
    validator where the format has no checksum to verify."""
    return lo <= len(body) <= hi and charset.fullmatch(body) is not None


_ALNUM_RE = re.compile(r"[A-Za-z0-9]+")
_HEX_CHARS_RE = re.compile(r"[0-9a-fA-F]+")  # NOT _HEX_RE: that name is
# the decode-then-scan blob finder above -- shadowing it floods the blob
# cap with 1-2 char matches and silently disables encoded-secret scans.
_TOKEN_CHARS_RE = re.compile(r"[A-Za-z0-9_\-]+")


# Shape validators for the provider key fingerprints (llm_compat.py's
# /key prefixes). Real keys: groq gsk_+52 alnum, openrouter sk-or-v1-+64
# hex, nvidia nvapi-+~44 token chars, gemini AIza+35 (=39 total),
# perplexity pplx-+~48 alnum, xai-+~48 alnum. Ranges are generous;
# look-alikes (too short, wrong charset, wrong total length) fail.
def _validate_groq_key(v: str) -> bool:
    return v.startswith("gsk_") and _body_shape(v[4:], 40, 64, _ALNUM_RE)


def _validate_openrouter_key(v: str) -> bool:
    return (v.startswith("sk-or-v1-")
            and _body_shape(v[len("sk-or-v1-"):], 32, 128, _HEX_CHARS_RE))


def _validate_nvidia_key(v: str) -> bool:
    return (v.startswith("nvapi-")
            and _body_shape(v[len("nvapi-"):], 32, 128, _TOKEN_CHARS_RE))


def _validate_gemini_key(v: str) -> bool:
    # Classic AI Studio shape: AIza + 35 (= 39 total).
    if (v.startswith("AIza") and len(v) == 39
            and _TOKEN_CHARS_RE.fullmatch(v[4:]) is not None):
        return True
    # Current AI Studio shape (2025+): "AQ." + a long opaque body.
    return (v.startswith("AQ.") and len(v) >= 40
            and _TOKEN_CHARS_RE.fullmatch(v[3:]) is not None)


def _validate_perplexity_key(v: str) -> bool:
    return (v.startswith("pplx-")
            and _body_shape(v[len("pplx-"):], 32, 64, _ALNUM_RE))


def _validate_xai_key(v: str) -> bool:
    return (v.startswith("xai-")
            and _body_shape(v[len("xai-"):], 32, 64, _ALNUM_RE))


# Provider-key recognizers. These live ONLY in the substitution path:
# classify() never sees them, so its recall-first doctrine is unchanged.
# Each regex is deliberately loose (prefix + >=8 token chars) so that
# near-miss look-alikes become candidates -- the attached validator is
# what decides, exactly Presidio's recognizer/validate_result split.
_PROVIDER_KEY_RECOGNIZERS: list[tuple[str, re.Pattern,
                                      Callable[[str], bool]]] = [
    ("provider-key-groq",
     re.compile(r"\bgsk_[A-Za-z0-9_\-]{8,}"), _validate_groq_key),
    ("provider-key-openrouter",
     re.compile(r"\bsk-or-[A-Za-z0-9_\-]{8,}"), _validate_openrouter_key),
    ("provider-key-nvidia",
     re.compile(r"\bnvapi-[A-Za-z0-9_\-]{8,}"), _validate_nvidia_key),
    ("provider-key-gemini",
     re.compile(r"\b(?:AIza[A-Za-z0-9_\-]{8,}|AQ\.[A-Za-z0-9_\-]{8,})"),
     _validate_gemini_key),
    ("provider-key-perplexity",
     re.compile(r"\bpplx-[A-Za-z0-9_\-]{8,}"), _validate_perplexity_key),
    ("provider-key-xai",
     re.compile(r"\bxai-[A-Za-z0-9_\-]{8,}"), _validate_xai_key),
]

# The validate() hook table, keyed by recognizer/finding pattern name.
# Any candidate (from classify() findings OR the recognizers above) whose
# pattern name appears here must pass its validator to be substituted.
_PATTERN_VALIDATORS: dict[str, Callable[[str], bool]] = {
    name: validate for name, _rx, validate in _PROVIDER_KEY_RECOGNIZERS
}

# Context boost: label words near a PERSONAL span raise its floor.
_LABEL_WORD_RE = re.compile(r"(?i)\b(?:key|token|password|api)\b")
_CONTEXT_CHARS_BEFORE = 48
_CONTEXT_CHARS_AFTER = 32


def _raised_class(text: str, start: int, end: int,
                  cls: DataClass) -> DataClass:
    """Context boost (substitution path ONLY). A PERSONAL span whose
    surrounding words include a label word is handled as SECRET."""
    if cls != DataClass.PERSONAL:
        return cls
    lo = max(0, start - _CONTEXT_CHARS_BEFORE)
    hi = min(len(text), end + _CONTEXT_CHARS_AFTER)
    if _LABEL_WORD_RE.search(text[lo:hi]):
        return DataClass.SECRET
    return cls


class Vault:
    """Placeholder -> original map for one substitution scope.

    IN MEMORY ONLY: a Vault is never written to disk, never logged
    (repr shows counts, never values), and is meant to be dropped when
    the turn ends. The same value always maps to the same placeholder
    within a vault, so the model can reason about identity ("that is
    the same <SECRET_1> you mentioned") without seeing any value.

    `unknown_seen` counts placeholders restore() met that this vault
    never issued (model hallucinations): they pass through unchanged --
    restore never invents a value and never crashes.

    Known edge (shared with Presidio): literal placeholder-shaped text
    (<SECRET_1>) typed by the user is indistinguishable from an issued
    placeholder on the restore path.
    """

    def __init__(self) -> None:
        self._values: dict[str, str] = {}       # placeholder -> original
        self._by_value: dict[str, str] = {}     # original -> placeholder
        self._counters: dict[DataClass, int] = {
            DataClass.SECRET: 0, DataClass.PERSONAL: 0}
        self.unknown_seen: int = 0

    def placeholder_for(self, value: str, data_class: DataClass) -> str:
        """The stable placeholder for `value`, minting one if needed."""
        existing = self._by_value.get(value)
        if existing is not None:
            return existing
        n = self._counters.get(data_class, 0) + 1
        self._counters[data_class] = n
        placeholder = f"<{data_class.name}_{n}>"
        self._values[placeholder] = value
        self._by_value[value] = placeholder
        return placeholder

    def lookup(self, placeholder: str) -> str | None:
        return self._values.get(placeholder)

    @property
    def placeholders(self) -> list[str]:
        """Issued placeholder names (names only -- never values)."""
        return list(self._values)

    def __contains__(self, placeholder: str) -> bool:
        return placeholder in self._values

    def __getitem__(self, placeholder: str) -> str:
        return self._values[placeholder]

    def __len__(self) -> int:
        return len(self._values)

    def restore(self, text: str) -> str:
        """Swap this vault's placeholders in `text` back to originals.
        Unknown placeholders pass through unchanged and are counted."""
        if not isinstance(text, str):
            return text

        def _sub(m: re.Match) -> str:
            placeholder = m.group(0)
            value = self._values.get(placeholder)
            if value is None:
                self.unknown_seen += 1
                return placeholder
            return value

        return _PLACEHOLDER_RE.sub(_sub, text)

    def __repr__(self) -> str:
        counts = ", ".join(
            f"{cls.name}={n}" for cls, n in sorted(
                self._counters.items(), key=lambda kv: kv[0].value) if n)
        return (f"<Vault: {len(self)} placeholders ({counts or 'none'}), "
                f"unknown_seen={self.unknown_seen}>")


# ---------------------------------------------------------------------------
# The DCL
# ---------------------------------------------------------------------------

class DCL:
    """Data Classification Layer. Deterministic. Fail-closed."""

    def __init__(self, registry: SecretRegistry | None = None) -> None:
        self.registry = registry if registry is not None else SecretRegistry()

    # -- public API --------------------------------------------------------

    def register_secret(self, name: str, value: str) -> None:
        self.registry.register_secret(name, value)

    def classify(self, text: str) -> tuple[DataClass, list[Finding]]:
        """Classify text. Returns (class, findings). Fail-closed: any internal
        error -> SENSITIVE, never PUBLIC."""
        try:
            if not isinstance(text, str):
                return DataClass.SENSITIVE, [
                    Finding(DataClass.SENSITIVE, "ERR", "non-string-input", 0, 0,
                            detail="input was not text -- escalated")]

            findings: list[Finding] = []
            findings.extend(self.registry.find_matches(text))   # Tier A
            findings.extend(self._tier_b(text, depth=0))        # Tier B
            findings.extend(self._tier_c(text))                 # Tier C

            cls = DataClass.PUBLIC
            for f in findings:
                if f.data_class > cls:
                    cls = f.data_class
            return cls, findings
        except Exception:
            # Fail CLOSED: a broken classifier must never bless content PUBLIC.
            return DataClass.SENSITIVE, [
                Finding(DataClass.SENSITIVE, "ERR", "classifier-error", 0, 0,
                        detail="internal error during classification -- escalated")]

    def redact(self, text: str,
               findings: list[Finding] | None = None
               ) -> tuple[str, list[Finding]]:
        """Replace SECRET spans with [REDACTED:SECRET] and SENSITIVE spans with
        [REDACTED:SENSITIVE]. PERSONAL/PUBLIC pass through. Overlapping spans
        merge with the highest class winning."""
        if findings is None:
            _, findings = self.classify(text)

        spans = sorted(
            ((f.start, f.end, f.data_class) for f in findings
             if f.data_class in (DataClass.SECRET, DataClass.SENSITIVE)),
            key=lambda s: (s[0], -(s[1] - s[0])),
        )
        # Merge overlaps: highest class wins.
        merged: list[list] = []
        for start, end, cls in spans:
            if end <= start:
                continue
            if merged and start < merged[-1][1]:
                prev = merged[-1]
                prev[1] = max(prev[1], end)
                if cls > prev[2]:
                    prev[2] = cls
            else:
                merged.append([start, end, cls])

        out: list[str] = []
        pos = 0
        for start, end, cls in merged:
            out.append(text[pos:start])
            out.append("[REDACTED:SECRET]" if cls == DataClass.SECRET
                       else "[REDACTED:SENSITIVE]")
            pos = end
        out.append(text[pos:])
        return "".join(out), findings

    def substitute(self, text: str,
                   vault: Vault | None = None) -> tuple[str, Vault]:
        """Reversible redaction (Presidio vault pattern).

        Every SECRET/PERSONAL span is replaced by a stable placeholder
        (<SECRET_1>, <PERSONAL_1>, ... -- numbered per class in order of
        first appearance; the SAME value always gets the SAME placeholder
        within a vault, so the model can reason about identity). Returns
        (clean_text, vault); pass the vault to restore() on the reply
        path. Pass an existing `vault` to keep numbering/dedup coherent
        across several texts (e.g. every message of one brain turn).

        SENSITIVE spans pass through unchanged (see the section header).
        Fail-closed like classify(): any internal error falls back to
        one-way redact() output, so a substitution bug can never leak.
        """
        v = vault if vault is not None else Vault()
        if not isinstance(text, str):
            return text, v
        try:
            spans = self._substitution_candidates(text)
            if not spans:
                return text, v
            # Effective class per distinct value: the highest class any
            # occurrence earned (context boost included), so one value
            # never wears two placeholders of different classes.
            best: dict[str, DataClass] = {}
            order: list[str] = []
            for start, end, cls in spans:
                value = text[start:end]
                if value not in best:
                    best[value] = cls
                    order.append(value)
                elif cls > best[value]:
                    best[value] = cls
            for value in order:
                v.placeholder_for(value, best[value])
            out: list[str] = []
            pos = 0
            for start, end, _cls in spans:
                out.append(text[pos:start])
                out.append(v.placeholder_for(text[start:end],
                                             best[text[start:end]]))
                pos = end
            out.append(text[pos:])
            return "".join(out), v
        except Exception:
            redacted, _ = self.redact(text)
            return redacted, v

    def _substitution_candidates(
            self, text: str) -> list[tuple[int, int, DataClass]]:
        """Merged (start, end, class) spans substitute() will vault.

        Sources: (a) SECRET/PERSONAL findings from classify(), filtered
        by any validate() hook registered for their pattern and raised
        by the context boost; (b) the provider-key recognizers, which
        exist only in this path. Overlaps merge with the highest class
        winning, exactly as in redact()."""
        spans: list[tuple[int, int, DataClass]] = []
        _, findings = self.classify(text)
        for f in findings:
            if f.data_class not in (DataClass.SECRET, DataClass.PERSONAL):
                continue
            validate = _PATTERN_VALIDATORS.get(f.pattern.split("@")[0])
            if validate is not None and not validate(text[f.start:f.end]):
                continue  # validate() hook: look-alike, do not substitute
            spans.append((f.start, f.end,
                          _raised_class(text, f.start, f.end, f.data_class)))
        for _name, rx, validate in _PROVIDER_KEY_RECOGNIZERS:
            for m in rx.finditer(text):
                if validate(m.group(0)):
                    spans.append((m.start(), m.end(), DataClass.SECRET))
        spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
        merged: list[list] = []
        for start, end, cls in spans:
            if end <= start:
                continue
            if merged and start < merged[-1][1]:
                prev = merged[-1]
                prev[1] = max(prev[1], end)
                if cls > prev[2]:
                    prev[2] = cls
            else:
                merged.append([start, end, cls])
        return [(s, e, c) for s, e, c in merged]

    def feed_entry(self, destination: str,
                   items: list[dict],
                   source: str = "chat") -> list[dict]:
        """Build 'what left the machine' metadata. METADATA ONLY -- the
        content itself is never included, by construction: callers pass
        class/source/byte counts, never text.

        items: [{data_class, source, byte_count, action}]
        action in {"sent", "withheld", "held_for_confirm"}.
        """
        ts = time.time()
        entries = []
        for it in items:
            dc = it.get("data_class", DataClass.PUBLIC)
            dc_name = dc.name if isinstance(dc, DataClass) else str(dc)
            entries.append({
                "ts": ts,
                "source": str(it.get("source", source)),
                "destination": str(destination),
                "class": dc_name,
                "byte_count": int(it.get("byte_count", 0)),
                "action": str(it.get("action", "sent")),
            })
        return entries

    # -- Tier B ------------------------------------------------------------

    def _tier_b(self, text: str, depth: int) -> list[Finding]:
        findings: list[Finding] = []
        findings.extend(self._tier_b_patterns(text))
        if depth < _MAX_DECODE_DEPTH:
            findings.extend(self._decode_then_scan(text, depth))
        else:
            # Deeper nesting than we unwrap is itself suspicious.
            if (_B64_RE.search(text) or _HEX_RE.search(text)
                    or _URL_RE.search(text)):
                findings.append(Finding(
                    DataClass.SENSITIVE, "B", "deep-encoding", 0, len(text),
                    detail=f"encoding nested deeper than {_MAX_DECODE_DEPTH} "
                           "layers -- suspicious, escalated"))
        return findings

    def _tier_b_patterns(self, text: str) -> list[Finding]:
        findings: list[Finding] = []
        for name, rx in _TIER_B_PATTERNS:
            for m in rx.finditer(text):
                findings.append(Finding(
                    DataClass.SECRET, "B", name, m.start(), m.end(),
                    detail=f"credential-shaped pattern: {name}"))
        for m in _SEED_12.finditer(text):
            findings.append(Finding(
                DataClass.SECRET, "B", "seed-phrase-12", m.start(), m.end(),
                detail="12-word lowercase sequence -- possible seed phrase"))
        for m in _SEED_24.finditer(text):
            findings.append(Finding(
                DataClass.SECRET, "B", "seed-phrase-24", m.start(), m.end(),
                detail="24-word lowercase sequence -- possible seed phrase"))
        for m in _CARD_RE.finditer(text):
            digits = re.sub(r"\D", "", m.group(0))
            if 13 <= len(digits) <= 19 and _luhn_ok(digits):
                findings.append(Finding(
                    DataClass.SECRET, "B", "card-number-luhn", m.start(), m.end(),
                    detail="Luhn-valid card number"))
        # High-entropy tokens: the recall arm's last resort. SENSITIVE, not
        # SECRET -- hashes and UUIDs live here too (the known FP source).
        for m in _ENTROPY_RE.finditer(text):
            tok = m.group(0).strip("=")
            if len(tok) >= 32 and _shannon_entropy(tok) > 4.7:
                findings.append(Finding(
                    DataClass.SENSITIVE, "B", "high-entropy-token",
                    m.start(), m.end(),
                    detail="high-entropy token -- could be an unlabeled secret"))
        return findings

    def _decode_then_scan(self, text: str, depth: int) -> list[Finding]:
        """Decode base64/hex/URL blobs, scan the decoded content, and remap any
        findings onto the ORIGINAL blob span (so redaction removes the blob)."""
        findings: list[Finding] = []
        blobs: list[tuple[str, int, int, str]] = []  # (kind, start, end, blob)
        for rx, kind in ((_B64_RE, "b64"), (_HEX_RE, "hex"), (_URL_RE, "url")):
            for m in rx.finditer(text):
                blobs.append((kind, m.start(), m.end(), m.group(0)))
                if len(blobs) >= _MAX_DECODE_BLOBS:
                    break
            if len(blobs) >= _MAX_DECODE_BLOBS:
                break

        for kind, start, end, blob in blobs:
            decoded = _try_decode(kind, blob)
            if decoded is None:
                continue
            # Tier A applies to decoded layers too: a REGISTERED secret does
            # not stop being a secret because someone base64'd it. (Before
            # this, decode-then-scan only re-ran Tier B patterns, so an
            # encoded registered secret sailed past the registry.)
            for f in self.registry.find_matches(decoded):
                findings.append(Finding(
                    DataClass.SECRET, "A",
                    f"{f.pattern}@encoded-{kind}-L{depth + 1}",
                    start, end,
                    detail=f"registered secret found in {kind}-decoded "
                           f"layer {depth + 1}"))
            sub = self._tier_b(decoded, depth + 1)
            for f in sub:
                # Remap onto the original encoded blob's span.
                findings.append(Finding(
                    f.data_class, "B",
                    f"{f.pattern}@encoded-{kind}-L{depth + 1}",
                    start, end,
                    detail=f"found in {kind}-decoded layer {depth + 1}: "
                           f"{f.pattern}"))
        return findings

    # -- Tier C ------------------------------------------------------------

    def _tier_c(self, text: str) -> list[Finding]:
        findings: list[Finding] = []
        for name, rx, cls in _TIER_C_PATTERNS:
            for m in rx.finditer(text):
                findings.append(Finding(
                    cls, "C", name, m.start(), m.end(),
                    detail=f"PII pattern: {name}"))
        return findings


# ---------------------------------------------------------------------------
# Egress audit -- the durable "what left the machine" feed (P1-13, L341)
# ---------------------------------------------------------------------------

EGRESS_EVENT_TYPE = "dcl.egress"


def record_egress(store, session_id: str, destination: str,
                  data_class, action: str = "sent", byte_count: int = 0,
                  source: str = "chat") -> str | None:
    """Append one dcl.egress event to the session store. METADATA ONLY (via
    feed_entry): timestamp, class, destination, byte count, action -- the
    content itself is never recorded, by construction.

    Returns the event_id, or None if recording failed. Recording is audit:
    it must never raise into the egress path it observes."""
    try:
        entry = _default_dcl.feed_entry(
            destination,
            [{"data_class": data_class, "source": source,
              "byte_count": byte_count, "action": action}],
            source=source)[0]
        return store.emit(session_id, EGRESS_EVENT_TYPE, entry,
                          actor="system", trust="system")
    except Exception:
        return None


def make_egress_sink(store, session_id: str, source: str = "chat"):
    """Build the callable Gate(egress_sink=...) expects: one metadata dict
    in, one dcl.egress event out. Bridges the gate to the session store."""
    def _sink(entry: dict) -> None:
        record_egress(store, session_id,
                      str(entry.get("destination", "unknown")),
                      str(entry.get("class", "PUBLIC")),
                      action=str(entry.get("action", "sent")),
                      byte_count=int(entry.get("byte_count", 0)),
                      source=source)
    return _sink


def what_left(store, limit: int = 50,
              session_id: str | None = None) -> list[tuple]:
    """The audit reader: the last `limit` egress events as
    (timestamp, classification, destination) tuples, chronological order.

    With session_id, reads that session's events from the store. Without
    one, scans the store's JSONL spillover (its durable cross-session copy)
    so the answer spans sessions. Metadata only -- there is no content in
    these events to leak."""
    payloads: list[tuple] = []  # (envelope_ts, payload)
    if session_id is not None:
        for ev in store.get_events(session_id, limit=1_000_000):
            if ev.get("type") == EGRESS_EVENT_TYPE:
                payloads.append((ev.get("ts"), ev.get("payload") or {}))
    else:
        import glob as _glob
        for path in sorted(_glob.glob(
                os.path.join(store.dir, "sessions-*.jsonl"))):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            env = json.loads(line)
                        except ValueError:
                            continue
                        if env.get("type") == EGRESS_EVENT_TYPE:
                            payloads.append(
                                (env.get("ts"), env.get("payload") or {}))
            except OSError:
                continue
    out: list[tuple] = []
    for env_ts, p in payloads[-limit:] if limit > 0 else []:
        out.append((p.get("ts", env_ts), p.get("class", ""),
                    p.get("destination", "")))
    return out


# ---------------------------------------------------------------------------
# Module-level convenience API (backed by a default DCL instance)
# ---------------------------------------------------------------------------

_default_dcl = DCL()
_default_registry_path: str | None = None


def configure_registry(data_dir: str) -> SecretRegistry:
    """Point the module-level DCL at the data dir's persisted registry and
    make future register_secret() calls persist immediately. Returns the
    registry in use."""
    global _default_registry_path
    _default_dcl.registry = load_or_create_registry(data_dir)
    _default_registry_path = registry_path(data_dir)
    return _default_dcl.registry


def classify(text: str) -> tuple[DataClass, list[Finding]]:
    return _default_dcl.classify(text)


def redact(text: str,
           findings: list[Finding] | None = None
           ) -> tuple[str, list[Finding]]:
    return _default_dcl.redact(text, findings)


def substitute(text: str,
               vault: Vault | None = None) -> tuple[str, Vault]:
    """Module-level substitute() on the default DCL. See DCL.substitute."""
    return _default_dcl.substitute(text, vault)


def restore(text: str, vault: Vault | None) -> str:
    """Swap placeholders in `text` back to `vault`'s originals.

    Unknown placeholders (never issued by this vault) pass through
    unchanged and bump vault.unknown_seen. A None vault is a no-op."""
    if vault is None or not isinstance(text, str):
        return text
    return vault.restore(text)


def feed_entry(destination: str, items: list[dict],
               source: str = "chat") -> list[dict]:
    return _default_dcl.feed_entry(destination, items, source)


def register_secret(name: str, value: str) -> None:
    """Register a secret with the default DCL. If configure_registry() has
    run, the registry (digests only) is persisted to the data dir at once,
    so the registration survives restarts."""
    _default_dcl.register_secret(name, value)
    if _default_registry_path is not None:
        try:
            _default_dcl.registry.save(_default_registry_path)
        except OSError:
            pass  # in-memory registration still protects this process
