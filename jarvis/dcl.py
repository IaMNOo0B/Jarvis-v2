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
# Module-level convenience API (backed by a default DCL instance)
# ---------------------------------------------------------------------------

_default_dcl = DCL()


def classify(text: str) -> tuple[DataClass, list[Finding]]:
    return _default_dcl.classify(text)


def redact(text: str,
           findings: list[Finding] | None = None
           ) -> tuple[str, list[Finding]]:
    return _default_dcl.redact(text, findings)


def feed_entry(destination: str, items: list[dict],
               source: str = "chat") -> list[dict]:
    return _default_dcl.feed_entry(destination, items, source)


def register_secret(name: str, value: str) -> None:
    _default_dcl.register_secret(name, value)
