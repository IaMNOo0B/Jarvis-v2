"""Email skill — drafts-first email over stdlib IMAP/SMTP (Team 21 steals).

DOCTRINE (from the Team 21 mega-scan: inbox-zero, email-mcp, thunderbird-mcp
— patterns re-implemented, never copied; inbox-zero is AGPL, email-mcp LGPL):

1. **Nobody free-sends.** The compose path produces a DRAFT stored in the
   skill jail with a content hash. `email_send` (tier-2) sends only a
   previously drafted record whose CURRENT stored hash equals the hash the
   owner approved — any edit after approval invalidates the send.
2. **Secrets are references, never values.** Account settings live in the
   OS-backed Secrets store under `email:<account>:*` names (imap_host,
   user, password, ...). This file never reads a config file containing a
   password, and never logs a password.
3. **Redaction at the log boundary.** The append-only audit JSONL records
   timestamp / account / to / subject / content-hash / outcome — NEVER
   bodies, NEVER credentials (the email-mcp redaction set).
4. **Rate discipline.** Max 10 successful sends per account per hour,
   enforced from a persisted counter in the jail.
5. **Unknown outcomes are reported as unknown.** If SMTP fails after the
   message may have been accepted, the result says "unknown — check Sent
   before retrying" (thunderbird-mcp's rule), never a fake success/failure.

Transports are built lazily through the IMAP_FACTORY / SMTP_FACTORY hooks
and secrets through SECRETS_PROVIDER, so tests inject fakes and no network
is touched at import time. Mail bodies are untrusted input: `email_read`
returns them DCL-redacted (OTPs and credential-shaped strings are SECRET
to the DCL); if the DCL is unavailable the body is withheld, fail-closed.

Stdlib only: imaplib, smtplib, email.
"""

import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path

DRAFTS_NAME = "drafts.json"
AUDIT_NAME = "audit.jsonl"
RATE_NAME = "rate_state.json"

MAX_SENDS_PER_HOUR = 10          # task spec: persisted per-account cap
RATE_WINDOW_S = 3600
DEFAULT_LIMIT = 20
MAX_LIMIT = 50
DEFAULT_READ_CHARS = 8000
MAX_READ_CHARS = 20000           # hard cap on body chars returned to the model
LIST_HEADER_QUERY = "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"

# ---------------------------------------------------------------------------
# DCL (fail-closed for bodies) — system/web skill precedent: jarvis.dcl is
# importable from skill context; if it ever is not, bodies are withheld.
# ---------------------------------------------------------------------------

try:
    from jarvis.dcl import DCL as _DCL_CLS

    _DCL = _DCL_CLS()
except Exception:  # pragma: no cover — jarvis package not importable
    _DCL = None


def _redact(text):
    """DCL-redact text. Returns (text, redacted?) or (None, False) when the
    DCL is unavailable — callers handling bodies must withhold on None."""
    if _DCL is None:
        return None, False
    out, findings = _DCL.redact(text)
    return out, bool(findings)


# ---------------------------------------------------------------------------
# Secrets: account config by reference — `email:<account>:<field>` names in
# the owner's Secrets store (keyring -> Windows Credential Manager -> file
# -> env). The skill only ever ASKS for values by name, at connect time.
# ---------------------------------------------------------------------------

SECRETS_PROVIDER = None  # tests inject; None -> jarvis.config.Secrets


def _secrets():
    if SECRETS_PROVIDER is not None:
        return SECRETS_PROVIDER
    from jarvis.config import Secrets

    return Secrets()


_ACCOUNT_FIELDS = ("imap_host", "imap_port", "smtp_host", "smtp_port",
                   "user", "password", "from")


def _port(value, default):
    try:
        return int(value) if value else default
    except (TypeError, ValueError):
        return default


def resolve_account(account, secrets=None):
    """Resolve `email:<account>:*` secret references into a config dict.

    Returns None when the account is not configured (any of imap_host /
    user / password missing). The password value is returned for connect
    use only — it must never be logged, audited, or returned to the model.
    """
    secrets = secrets if secrets is not None else _secrets()
    cfg = {}
    for field in _ACCOUNT_FIELDS:
        value = secrets.get(f"email:{account}:{field}")
        if value:
            cfg[field] = value
    if not (cfg.get("imap_host") and cfg.get("user") and cfg.get("password")):
        return None
    cfg["account"] = account
    cfg["imap_port"] = _port(cfg.get("imap_port"), 993)
    cfg["smtp_host"] = cfg.get("smtp_host") or cfg["imap_host"]
    cfg["smtp_port"] = _port(cfg.get("smtp_port"), 587)
    cfg["from"] = cfg.get("from") or cfg["user"]
    return cfg


def _not_configured(account):
    return {
        "configured": False,
        "account": account,
        "note": (f"no email account {account!r} is configured — the owner "
                 f"can add email:{account}:imap_host, email:{account}:user "
                 f"and email:{account}:password secrets (Settings / "
                 f"keyring). Passwords are referenced by name only and "
                 f"never stored in files."),
    }


# ---------------------------------------------------------------------------
# Transports — lazy real constructors; tests replace the factories.
# ---------------------------------------------------------------------------

def _default_imap(cfg):
    import imaplib

    conn = imaplib.IMAP4_SSL(cfg["imap_host"], cfg["imap_port"])
    conn.login(cfg["user"], cfg["password"])
    return conn


def _default_smtp(cfg):
    import smtplib

    conn = smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"], timeout=30)
    conn.starttls()
    conn.login(cfg["user"], cfg["password"])
    return conn


IMAP_FACTORY = _default_imap
SMTP_FACTORY = _default_smtp


def _close(conn, method):
    try:
        getattr(conn, method)()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Jail stores: drafts (atomic JSON), rate state (atomic JSON), audit (JSONL)
# ---------------------------------------------------------------------------

def _jail(ctx) -> Path:
    return Path(ctx.jail_dir)


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(path)


def content_hash(to: str, subject: str, body: str) -> str:
    """The approval-binding hash: sha256 over the canonical message."""
    canonical = f"{to}\n{subject}\n{body}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _audit(jail: Path, entry: dict) -> None:
    """Append one audit line. Callers pass ONLY ts/account/to/subject/
    hash/outcome fields — bodies and credentials never reach this file."""
    jail.mkdir(parents=True, exist_ok=True)
    with open(jail / AUDIT_NAME, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _recent_sends(jail: Path, account: str, now: float) -> list:
    state = _load_json(jail / RATE_NAME, {})
    stamps = [float(t) for t in state.get(account, [])
              if now - float(t) < RATE_WINDOW_S]
    return stamps


def _record_send(jail: Path, account: str, now: float) -> None:
    state = _load_json(jail / RATE_NAME, {})
    stamps = _recent_sends(jail, account, now)
    stamps.append(now)
    state[account] = stamps
    _save_json(jail / RATE_NAME, state)


# ---------------------------------------------------------------------------
# IMAP reading
# ---------------------------------------------------------------------------

def _fetch_payload(data) -> bytes:
    """Extract message bytes from an imaplib fetch response (tolerant:
    payload lives in element [1] of tuple parts)."""
    chunks = []
    for part in data or []:
        if isinstance(part, tuple) and len(part) > 1 and \
                isinstance(part[1], (bytes, bytearray)):
            chunks.append(bytes(part[1]))
        elif isinstance(part, (bytes, bytearray)) and \
                b":" in bytes(part)[:200] and b"\n" in bytes(part):
            chunks.append(bytes(part))
    return b"".join(chunks)


_FLAGS_RE = re.compile(rb"FLAGS \(([^)]*)\)")


def _fetch_flags(data) -> list:
    for part in data or []:
        meta = part[0] if isinstance(part, tuple) else part
        if isinstance(meta, (bytes, bytearray)):
            m = _FLAGS_RE.search(bytes(meta))
            if m:
                return m.group(1).decode("ascii", "replace").split()
    return []


def _header(msg, name) -> str:
    value = msg.get(name, "")
    return str(value).replace("\r", " ").replace("\n", " ").strip()


def list_messages(cfg, folder="INBOX", limit=DEFAULT_LIMIT):
    limit = max(1, min(int(limit), MAX_LIMIT))
    conn = IMAP_FACTORY(cfg)
    try:
        typ, _ = conn.select(folder, readonly=True)
        if typ != "OK":
            return {"configured": True, "account": cfg["account"],
                    "folder": folder, "count": 0, "messages": [],
                    "note": f"folder {folder!r} could not be opened"}
        typ, data = conn.search(None, "ALL")
        ids = data[0].split() if typ == "OK" and data and data[0] else []
        recent = list(reversed(ids[-limit:]))
        messages = []
        for mid in recent:
            typ, fdata = conn.fetch(mid, LIST_HEADER_QUERY)
            if typ != "OK":
                continue
            raw = _fetch_payload(fdata)
            if not raw:
                continue
            msg = BytesParser(policy=policy.default).parsebytes(raw)
            flags = _fetch_flags(fdata)
            subject, _ = _redact(_header(msg, "Subject"))
            sender, _ = _redact(_header(msg, "From"))
            messages.append({
                "id": mid.decode("ascii", "replace"),
                "from": sender if sender is not None else "[withheld]",
                "subject": subject if subject is not None else "[withheld]",
                "date": _header(msg, "Date"),
                "unread": "\\Seen" not in flags,
            })
        return {"configured": True, "account": cfg["account"],
                "folder": folder, "count": len(messages),
                "messages": messages}
    finally:
        _close(conn, "logout")


_TAG_RE = re.compile(r"<[^>]+>")


def _extract_body(msg) -> str:
    """Plain-text body of a parsed message (HTML crudely stripped)."""
    part = None
    if msg.is_multipart():
        part = msg.get_body(preferencelist=("plain", "html"))
    else:
        part = msg
    if part is None:
        return ""
    try:
        content = part.get_content()
    except Exception:
        payload = part.get_payload(decode=True) or b""
        content = payload.decode(part.get_content_charset() or "utf-8",
                                 "replace")
    if part.get_content_type() == "text/html":
        content = _TAG_RE.sub(" ", content)
        content = re.sub(r"[ \t]+", " ", content)
    return content.strip()


def read_message(cfg, message_id, folder="INBOX",
                 max_chars=DEFAULT_READ_CHARS):
    max_chars = max(0, min(int(max_chars), MAX_READ_CHARS))
    conn = IMAP_FACTORY(cfg)
    try:
        typ, _ = conn.select(folder, readonly=True)
        if typ != "OK":
            return {"configured": True, "account": cfg["account"],
                    "id": str(message_id), "found": False,
                    "note": f"folder {folder!r} could not be opened"}
        typ, fdata = conn.fetch(str(message_id), "(BODY.PEEK[])")
        raw = _fetch_payload(fdata) if typ == "OK" else b""
        if not raw:
            return {"configured": True, "account": cfg["account"],
                    "id": str(message_id), "found": False,
                    "note": "message not found"}
        msg = BytesParser(policy=policy.default).parsebytes(raw)
        body = _extract_body(msg)
        truncated = len(body) > max_chars
        body = body[:max_chars]
        redacted_body, was_redacted = _redact(body)
        result = {
            "configured": True, "account": cfg["account"],
            "id": str(message_id), "found": True,
            "from": _header(msg, "From"), "to": _header(msg, "To"),
            "subject": _header(msg, "Subject"), "date": _header(msg, "Date"),
            "truncated": truncated,
        }
        if redacted_body is None:
            # DCL unavailable -> fail closed: metadata yes, body NO.
            result["body"] = None
            result["body_withheld"] = (
                "body withheld: the DCL redactor is unavailable, and mail "
                "bodies are never returned unredacted")
        else:
            result["body"] = redacted_body
            result["redacted"] = was_redacted
        return result
    finally:
        _close(conn, "logout")


# ---------------------------------------------------------------------------
# Drafts + hash-bound send
# ---------------------------------------------------------------------------

def create_draft(jail: Path, account: str, to: str, subject: str, body: str,
                 configured: bool):
    store = _load_json(jail / DRAFTS_NAME, {"drafts": {}})
    draft_id = "d_" + uuid.uuid4().hex[:16]
    record = {
        "id": draft_id, "account": account, "to": to, "subject": subject,
        "body": body, "hash": content_hash(to, subject, body),
        "created": _now_iso(), "status": "draft",
    }
    store.setdefault("drafts", {})[draft_id] = record
    _save_json(jail / DRAFTS_NAME, store)
    return {"draft_id": draft_id, "hash": record["hash"], "account": account,
            "to": to, "subject": subject, "configured": configured,
            "note": ("draft saved locally; sending needs email_send with "
                     "this exact hash after owner approval"
                     if configured else
                     "draft saved locally; the account is not configured, "
                     "so it cannot be sent until email secrets are added")}


def send_draft(jail: Path, draft_id: str, approved_hash: str):
    """Send a stored draft IFF its current hash == the approved hash."""
    store = _load_json(jail / DRAFTS_NAME, {"drafts": {}})
    record = store.get("drafts", {}).get(draft_id)
    if record is None:
        return {"sent": False, "draft_id": draft_id,
                "reason": "no such draft — compose it with email_draft "
                          "first"}
    if record.get("status") == "sent":
        return {"sent": False, "draft_id": draft_id,
                "reason": "this draft was already sent; compose a new "
                          "draft to send again"}
    current = content_hash(record["to"], record["subject"], record["body"])
    if current != record.get("hash") or current != (approved_hash or ""):
        _audit(jail, {"ts": _now_iso(), "event": "send_refused",
                      "account": record["account"], "to": record["to"],
                      "subject": record["subject"], "hash": current,
                      "reason": "hash_mismatch"})
        return {"sent": False, "draft_id": draft_id,
                "reason": "the draft changed after approval (content hash "
                          "mismatch) — sending is refused; re-draft and "
                          "get approval for the new hash",
                "current_hash": current}
    account = record["account"]
    cfg = resolve_account(account)
    if cfg is None:
        return {"sent": False, "draft_id": draft_id,
                **_not_configured(account)}
    now = time.time()
    recent = _recent_sends(jail, account, now)
    if len(recent) >= MAX_SENDS_PER_HOUR:
        _audit(jail, {"ts": _now_iso(), "event": "send_refused",
                      "account": account, "to": record["to"],
                      "subject": record["subject"], "hash": current,
                      "reason": "rate_limited"})
        return {"sent": False, "draft_id": draft_id,
                "reason": f"rate limit: {MAX_SENDS_PER_HOUR} sends per "
                          f"hour for this account — try again later",
                "sends_last_hour": len(recent)}
    msg = EmailMessage()
    msg["From"] = cfg["from"]
    msg["To"] = record["to"]
    msg["Subject"] = record["subject"]
    msg.set_content(record["body"])
    try:
        conn = SMTP_FACTORY(cfg)
    except Exception as exc:
        _audit(jail, {"ts": _now_iso(), "event": "send_failed",
                      "account": account, "to": record["to"],
                      "subject": record["subject"], "hash": current,
                      "reason": f"connect_failed: {type(exc).__name__}"})
        return {"sent": False, "draft_id": draft_id, "outcome": "failed",
                "reason": "could not connect or log in — nothing was "
                          "sent; check the account secrets and server"}
    try:
        conn.send_message(msg)
    except Exception:
        # The server may have accepted the message before the failure —
        # thunderbird-mcp's rule: report unknown, never guess.
        _record_send(jail, account, now)
        _audit(jail, {"ts": _now_iso(), "event": "send_unknown",
                      "account": account, "to": record["to"],
                      "subject": record["subject"], "hash": current,
                      "reason": "smtp_error_after_connect"})
        return {"sent": False, "draft_id": draft_id, "outcome": "unknown",
                "reason": "the send failed midway — the server may have "
                          "accepted it. Check the Sent folder before "
                          "retrying; do not assume it was not sent"}
    finally:
        _close(conn, "quit")
    record["status"] = "sent"
    record["sent_at"] = _now_iso()
    _save_json(jail / DRAFTS_NAME, store)
    _record_send(jail, account, now)
    _audit(jail, {"ts": _now_iso(), "event": "send", "account": account,
                  "to": record["to"], "subject": record["subject"],
                  "hash": current})
    return {"sent": True, "draft_id": draft_id, "hash": current,
            "account": account, "to": record["to"],
            "subject": record["subject"]}


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

def handle(tool_name, args, ctx):
    jail = _jail(ctx)
    if tool_name == "email_list":
        account = str(args.get("account") or "main")
        cfg = resolve_account(account)
        if cfg is None:
            return _not_configured(account)
        return list_messages(cfg, folder=str(args.get("folder") or "INBOX"),
                             limit=args.get("limit", DEFAULT_LIMIT))
    if tool_name == "email_read":
        account = str(args.get("account") or "main")
        cfg = resolve_account(account)
        if cfg is None:
            return _not_configured(account)
        return read_message(cfg, args["id"],
                            folder=str(args.get("folder") or "INBOX"),
                            max_chars=args.get("max_chars",
                                               DEFAULT_READ_CHARS))
    if tool_name == "email_draft":
        account = str(args.get("account") or "main")
        cfg = resolve_account(account)
        return create_draft(jail, account, str(args["to"]),
                            str(args["subject"]), str(args["body"]),
                            configured=cfg is not None)
    if tool_name == "email_send":
        return send_draft(jail, str(args["draft_id"]), str(args["hash"]))
    raise ValueError(f"unknown tool {tool_name!r}")
