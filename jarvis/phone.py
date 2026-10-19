"""Phone Remote (Telegram) — the phone is a window into JARVIS, never hands.

Spec: learn-phone-remote-spec.md (Cycle 24). Tiers enforced in deterministic
code on the PC; the phone sends *requests*, the PC decides what they *mean*.

    R0 (default)  read-only: questions, status, memory recall. No state change.
    R1            writes via explicit command table, each with per-command
                  confirmation: exact action + action hash shown, 4-digit PIN
                  reply, 10-minute expiry. One confirmation = one action.
    R2            never remotely: execute_code, destructive system actions,
                  secrets, skill install, updater, memory delete, capability
                  changes. Refused before the brain ever sees the request.

Security notes:
- The bot token lives in the OS keyring (parent's job); this module only
  ever holds it in memory and NEVER lets it reach logs, exceptions, or chat.
- The PIN is never stored: only a salted PBKDF2 hash. Comparison is
  hmac.compare_digest.
- Pairing replaces the old static allowlist: one-time 6-digit code, 5-minute
  expiry, single use. Strangers get silence, not an error message.
- Voice notes: 10MB streaming cap, local STT only, temp file deleted after
  transcription, and voice can NEVER confirm an R1 action.

Stdlib only: urllib, json, hmac, hashlib, threading, time, re, os.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from typing import Any, Callable, Optional

try:
    from jarvis.gate import Verdict, action_hash
except Exception:  # pragma: no cover - importable in tests via package
    Verdict = None  # type: ignore

    def action_hash(tool_name: str, args: dict) -> str:  # type: ignore
        import hashlib as _h, json as _j
        canon = _j.dumps({"t": tool_name, "a": args}, sort_keys=True,
                         separators=(",", ":"))
        return _h.sha256(canon.encode()).hexdigest()


# --------------------------------------------------------------------------- #
# Constants (all [PROPOSED] per spec §3 — soak-test to calibrate)
# --------------------------------------------------------------------------- #

PAIR_CODE_TTL_S = 5 * 60
PAIR_CODE_LEN = 6
CONFIRM_TTL_S = 10 * 60
PHONE_SESSION_IDLE_TTL_S = 24 * 3600
VOICE_MAX_BYTES = 10 * 1024 * 1024
PBKDF2_ROUNDS = 200_000

LIMIT_TEXTS_PER_MIN = 20
LIMIT_TURNS_PER_5MIN = 10
LIMIT_VOICE_PER_5MIN = 5
LIMIT_CONFIRMS_PER_10MIN = 5
LIMIT_PAIR_ATTEMPTS_PER_15MIN = 3

USER_ERROR = "Something went wrong on my end, sir \u2014 the desktop has the details."
SLOW_DOWN = "Slow down a touch, sir \u2014 I'm catching up."
AT_CAPACITY = "I'm at capacity right now, sir \u2014 try again in a bit."
HOLD_MSG = ("I'm holding further write requests for now, sir "
            "(fatigue guard). Reply RESUME when ready.")
SESSION_EXPIRED = ("Phone session expired after 24h of inactivity, sir \u2014 "
                   "pair again from the desktop (Settings \u2192 Phone).")
VOICE_TOO_BIG = "Voice note too long, sir \u2014 keep it under ~10 minutes."
VOICE_NO_STT = "I have no speech recognizer configured, sir \u2014 please type it."
VOICE_CANT_CONFIRM = ("Voice notes can't confirm actions, sir \u2014 "
                      "reply with your 4-digit PIN.")
NO_PIN_SET = ("No phone PIN is set, sir \u2014 set one on the desktop first "
              "(Settings \u2192 Phone).")


# --------------------------------------------------------------------------- #
# R1 command table — explicit allowlist, never pattern-guessing.
# Maps a command word -> (tool_name, arg_builder, turn_allowances).
# Extend here (and only here) to add remote-writable actions.
# --------------------------------------------------------------------------- #

def _note_args(rest: str) -> dict:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return {"path": f"phone-{stamp}.txt", "content": rest.strip()}


R1_COMMANDS: dict[str, tuple[str, Callable[[str], dict], list[str]]] = {
    "note": ("notes_write", _note_args, ["fs.write", "fs.read"]),
    # "draft": ("message_draft", ...)  -- extension point; no skill yet (v2).
}


# R2: refused at the phone surface before the brain sees the request.
# Word-boundary match on plain intent words; the gate is the second layer.
R2_PATTERNS: list[tuple[str, str]] = [
    (r"\bdelete\b|\bremove\b.*\bfile", "deleting things"),
    (r"\bshutdown\b|\bpower off\b|\brestart\b|\breboot\b|\blog ?off\b", "system power actions"),
    (r"\bexecute\b|\brun\b.*\bcode\b|\beval\b", "running code"),
    (r"\binstall\b.*\bskill\b|\benable\b.*\bskill\b", "installing skills"),
    (r"\bupdate\b.*\bjarvis\b|\bpull\b.*\blatest\b|\bupgrade\b", "updating JARVIS"),
    (r"\bforget\b.*\bmemory\b|\bwipe\b.*\bmemory\b|\bdelete\b.*\bmemory\b", "deleting memories"),
    (r"\bsecret\b|\bpassword\b|\bapi[-_ ]?key\b|\btoken\b", "secret management"),
    (r"\bchange\b.*\bpermission\b|\bgrant\b.*\baccess\b", "changing what the phone may do"),
]


# --------------------------------------------------------------------------- #
# Sliding-window rate limiter
# --------------------------------------------------------------------------- #

class RateLimiter:
    """Per-key sliding windows. allow() -> True if under the limit."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()
        self._clock = clock

    def allow(self, key: str, limit: int, window_s: float) -> bool:
        now = self._clock()
        with self._lock:
            dq = self._hits.setdefault(key, deque())
            while dq and dq[0] <= now - window_s:
                dq.popleft()
            if len(dq) >= limit:
                return False
            dq.append(now)
            return True

    def count(self, key: str, window_s: float) -> int:
        now = self._clock()
        with self._lock:
            dq = self._hits.get(key, deque())
            while dq and dq[0] <= now - window_s:
                dq.popleft()
            return len(dq)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


# --------------------------------------------------------------------------- #
# The remote
# --------------------------------------------------------------------------- #

class PhoneRemote:
    """Telegram long-polling phone surface.

    brain_fn(text, user_id) -> str   R0 turns (remote-scoped allowances).
    gate                             the R2 enforcement point.
    executor(tool_name, args) -> str executes an approved skill tool
                                 (parent wires registry.dispatch).
    stt_fn(path) -> str              local speech-to-text; None = unconfigured.
    """

    REMOTE_R0_ALLOWANCES = ["fs.read", "time.read"]  # read-only brain turns

    def __init__(
        self,
        brain_fn: Callable[[str, int], str],
        gate: Any,
        allowed_user_id: Optional[int] = None,
        *,
        token: Optional[str] = None,
        api_base: str = "https://api.telegram.org",
        executor: Optional[Callable[[str, dict], str]] = None,
        stt_fn: Optional[Callable[[str], str]] = None,
        clock: Callable[[], float] = time.time,
        on_alert: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.brain_fn = brain_fn
        self.gate = gate
        self.executor = executor
        self.stt_fn = stt_fn
        self._clock = clock
        self._on_alert = on_alert or (lambda msg: None)

        self._token = token or ""
        self._api_base = api_base.rstrip("/")
        self._offset = 0
        self._disabled_reason: Optional[str] = None
        self._auth_failures = 0

        # Pairing state
        self._pair_code: Optional[dict] = None  # {code, expires_at}
        self._paired: Optional[dict] = None     # {user_id, chat_id, paired_at, last_active}
        if allowed_user_id is not None:
            # Pre-paired (migration path); chat_id binds on first contact.
            self._paired = {"user_id": allowed_user_id, "chat_id": None,
                            "paired_at": clock(), "last_active": clock()}

        # PIN: only the salted hash is ever stored.
        self._pin: Optional[dict] = None  # {salt: hex, hash: hex}

        # Pending R1 confirmations: cid -> {...}
        self._pending: dict[str, dict] = {}
        self._hold: set[int] = set()  # chat_ids under confirmation HOLD
        self._last_slowdown_warn: dict[int, float] = {}

        self.limiter = RateLimiter(clock)
        self.contact_log: list[dict] = []  # strangers / group attempts (desktop-visible)
        self._lock = threading.Lock()
        self._stop = threading.Event()

    # -- token hygiene ------------------------------------------------------ #
    def _redact(self, text: str) -> str:
        if self._token:
            text = text.replace(self._token, "***")
        return text

    def _url(self, method: str) -> str:
        return f"{self._api_base}/bot{self._token}/{method}"

    def _api(self, method: str, payload: Optional[dict] = None,
             timeout: float = 35.0) -> dict:
        """POST to the Bot API. Token never escapes into logs/exceptions."""
        if not self._token:
            raise RuntimeError("phone not configured: no bot token")
        data = json.dumps(payload or {}).encode()
        req = urllib.request.Request(
            self._url(method), data=data,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            # Read the error body WITHOUT the token-bearing URL.
            try:
                err = json.loads(exc.read().decode())
            except Exception:
                err = {"ok": False, "description": f"HTTP {exc.code}"}
            err["_http_status"] = exc.code
            return err
        except Exception as exc:  # transport failure: no token in message
            return {"ok": False, "description": "transport error",
                    "_exception": type(exc).__name__}
        return body

    # -- pairing ------------------------------------------------------------ #
    def issue_pairing_code(self) -> str:
        """Desktop calls this; show the code to the user once."""
        code = "".join(secrets.choice("0123456789") for _ in range(PAIR_CODE_LEN))
        self._pair_code = {"code": code,
                           "expires_at": self._clock() + PAIR_CODE_TTL_S}
        return code

    def revoke(self) -> None:
        """One-click desktop revocation. Immediate."""
        with self._lock:
            self._paired = None
            self._pair_code = None
            self._pending.clear()
            self._hold.clear()

    @property
    def is_paired(self) -> bool:
        return self._paired is not None

    def _try_pair(self, code: str, user_id: int, chat_id: int) -> Optional[str]:
        if not self.limiter.allow(f"pair:{chat_id}", LIMIT_PAIR_ATTEMPTS_PER_15MIN, 900):
            self._on_alert(f"pairing locked for chat {chat_id}: too many attempts")
            return None  # silence + desktop alert (no hint to attacker)
        pc = self._pair_code
        now = self._clock()
        if pc is None or pc.get("used") or now > pc["expires_at"]:
            return None
        if not hmac.compare_digest(pc["code"], code.strip()):
            return None
        pc["used"] = True
        with self._lock:
            self._paired = {"user_id": user_id, "chat_id": chat_id,
                            "paired_at": now, "last_active": now}
        return ("Paired, sir \u2014 this phone is now linked. "
                "Replies stay in this chat only.")

    # -- PIN ---------------------------------------------------------------- #
    def set_pin_from_plaintext(self, pin: str) -> None:
        if not re.fullmatch(r"\d{4}", pin or ""):
            raise ValueError("PIN must be exactly 4 digits")
        salt = os.urandom(16)
        digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, PBKDF2_ROUNDS)
        self._pin = {"salt": salt.hex(), "hash": digest.hex()}

    def set_pin(self, pin_record: dict) -> None:
        """Restore a previously stored {salt, hash} record."""
        if "salt" not in pin_record or "hash" not in pin_record:
            raise ValueError("pin record needs 'salt' and 'hash'")
        self._pin = {"salt": pin_record["salt"], "hash": pin_record["hash"]}

    def verify_pin(self, pin: str) -> bool:
        if self._pin is None:
            return False
        try:
            salt = bytes.fromhex(self._pin["salt"])
            expect = bytes.fromhex(self._pin["hash"])
        except (ValueError, KeyError):
            return False
        got = hashlib.pbkdf2_hmac("sha256", (pin or "").encode(), salt,
                                  PBKDF2_ROUNDS)
        return hmac.compare_digest(got, expect)

    # -- messaging ----------------------------------------------------------- #
    def send(self, chat_id: int, text: str) -> None:
        if self._disabled_reason:
            return
        self._api("sendMessage",
                  {"chat_id": chat_id, "text": text[:4000]})

    # -- update handling ----------------------------------------------------- #
    def _is_private(self, message: dict) -> bool:
        return (message.get("chat") or {}).get("type") == "private"

    def _identity_ok(self, message: dict) -> bool:
        p = self._paired
        if p is None:
            return False
        chat = message.get("chat") or {}
        frm = message.get("from") or {}
        if p["chat_id"] is None:
            # Pre-paired migration: bind chat on first contact from the user.
            if frm.get("id") == p["user_id"]:
                p["chat_id"] = chat.get("id")
                return True
            return False
        return frm.get("id") == p["user_id"] and chat.get("id") == p["chat_id"]

    def process_message(self, message: dict) -> Optional[str]:
        """Core dispatcher. Returns reply text, or None for silence."""
        chat = message.get("chat") or {}
        frm = message.get("from") or {}
        chat_id = chat.get("id")
        user_id = frm.get("id")

        # 1. Group chats: ignored entirely (H-X10).
        if not self._is_private(message):
            self.contact_log.append({"kind": "group_ignored",
                                     "chat_id": chat_id,
                                     "ts": self._clock()})
            return None

        text = (message.get("text") or "").strip()
        voice = message.get("voice")

        # 2. Not paired: only a pairing code is answered (with silence on miss).
        if not self._identity_ok(message):
            if text and re.fullmatch(r"\d{6}", text):
                paired_msg = self._try_pair(text, user_id, chat_id)
                if paired_msg:
                    return paired_msg
                self.contact_log.append({"kind": "pair_failed",
                                         "chat_id": chat_id, "ts": self._clock()})
                return None
            self.contact_log.append({"kind": "stranger",
                                     "chat_id": chat_id, "user_id": user_id,
                                     "ts": self._clock()})
            return None

        # 3. Session expiry: 24h inactivity -> re-pair from desktop.
        now = self._clock()
        if now - self._paired["last_active"] > PHONE_SESSION_IDLE_TTL_S:
            self.revoke()
            return SESSION_EXPIRED
        self._paired["last_active"] = now

        # 4. Text rate limit.
        if not self.limiter.allow(f"text:{chat_id}", LIMIT_TEXTS_PER_MIN, 60):
            last = self._last_slowdown_warn.get(chat_id, 0)
            if now - last > 300:
                self._last_slowdown_warn[chat_id] = now
                return SLOW_DOWN
            return None

        # 5. HOLD state: only RESUME is honored.
        if chat_id in self._hold:
            if text.upper() == "RESUME":
                self._hold.discard(chat_id)
                return "Resumed, sir \u2014 write requests accepted again."
            return HOLD_MSG

        # 6. Voice notes.
        if voice:
            return self._handle_voice(message, chat_id, user_id)

        if not text:
            return None

        # 7. Pending R1 confirmation: PIN reply executes, anything else is a
        #    fresh turn (pending stays until expiry).
        pending = self._pending_for(chat_id)
        if pending and re.fullmatch(r"\d{4}", text):
            return self._confirm_pending(pending, text, chat_id, user_id)

        # 8. R1 commands (explicit allowlist).
        cmd = text.split(None, 1)[0].lower().lstrip("/")
        if cmd in R1_COMMANDS:
            return self._start_r1(cmd, text, chat_id, user_id)

        # 9. R2: refused before the brain sees it.
        for pattern, label in R2_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return (f"I can't do that from the phone, sir \u2014 {label} "
                        f"are never available remotely. You can do it from the desktop.")

        # 10. R0: brain turn with the remote-scoped (read-only) toolset.
        if not self.limiter.allow(f"turn:{chat_id}", LIMIT_TURNS_PER_5MIN, 300):
            return AT_CAPACITY
        try:
            return self.brain_fn(text, user_id)
        except Exception:
            return USER_ERROR

    # -- R1 flow -------------------------------------------------------------- #
    def _pending_for(self, chat_id: int) -> Optional[dict]:
        now = self._clock()
        for cid, p in list(self._pending.items()):
            if p["expires_at"] <= now:
                del self._pending[cid]
                continue
            if p["chat_id"] == chat_id:
                return p
        return None

    def _start_r1(self, cmd: str, text: str, chat_id: int, user_id: int) -> str:
        if self._pin is None:
            return NO_PIN_SET
        if not self.limiter.allow(f"confirm:{chat_id}", LIMIT_CONFIRMS_PER_10MIN, 600):
            self._hold.add(chat_id)
            self._on_alert(f"confirmation HOLD for chat {chat_id} (F3 guard)")
            return HOLD_MSG
        tool_name, arg_builder, _allow = R1_COMMANDS[cmd]
        rest = text.split(None, 1)[1] if " " in text.strip() else ""
        if not rest:
            return f"Usage: {cmd} <text>, sir."
        args = arg_builder(rest)
        ah = action_hash(tool_name, args)
        cid = secrets.token_urlsafe(8)
        with self._lock:
            self._pending[cid] = {
                "tool": tool_name, "args": args, "action_hash": ah,
                "chat_id": chat_id, "user_id": user_id,
                "expires_at": self._clock() + CONFIRM_TTL_S,
            }
        arg_summary = ", ".join(f"{k}={str(v)[:60]!r}" for k, v in args.items())
        return (f"Confirm, sir: {tool_name}({arg_summary})\n"
                f"action hash: {ah[:16]}…\n"
                f"Reply with your 4-digit PIN within 10 minutes. "
                f"Anything else cancels nothing \u2014 this request simply expires.")

    def _confirm_pending(self, pending: dict, pin: str,
                         chat_id: int, user_id: int) -> str:
        if self._pin is None:
            return NO_PIN_SET
        if not self.verify_pin(pin):
            return "Wrong PIN, sir \u2014 request not executed."
        # Recompute the hash: the stored action can't have been swapped.
        ah = action_hash(pending["tool"], pending["args"])
        if not hmac.compare_digest(ah, pending["action_hash"]):
            return "Action changed since confirmation, sir \u2014 refusing."
        if self.executor is None:
            return USER_ERROR
        try:
            # The PIN was the out-of-band approval; dispatch still enforces
            # declaration + schema + capabilities + tier at execution time.
            _decision, out = self.gate.dispatch(
                pending["tool"], pending["args"],
                ["fs.write", "fs.read", "time.read"], self.executor)
            if out is None:
                return (f"Blocked at execution, sir: {_decision.reason}. "
                        f"Nothing ran.")
        except Exception:
            return USER_ERROR
        finally:
            with self._lock:
                self._pending = {k: v for k, v in self._pending.items()
                                 if v is not pending}
        return f"Done, sir: {str(out)[:500]}"

    # -- voice ---------------------------------------------------------------- #
    def _handle_voice(self, message: dict, chat_id: int, user_id: int) -> str:
        if not self.limiter.allow(f"voice:{chat_id}", LIMIT_VOICE_PER_5MIN, 300):
            return "Too many voice notes, sir \u2014 please type for a bit."
        if self._pending_for(chat_id):
            return VOICE_CANT_CONFIRM
        voice = message.get("voice") or {}
        if (voice.get("file_size") or 0) > VOICE_MAX_BYTES:
            return VOICE_TOO_BIG
        if self.stt_fn is None:
            return VOICE_NO_STT
        tmp = None
        try:
            info = self._api("getFile", {"file_id": voice.get("file_id")})
            fpath = ((info.get("result") or {}).get("file_path")) if info.get("ok") else None
            if not fpath:
                return USER_ERROR
            tmp = tempfile.NamedTemporaryFile(suffix=".oga", delete=False)
            tmp.close()
            self._download_capped(fpath, tmp.name)
            transcript = (self.stt_fn(tmp.name) or "").strip()
        except Exception:
            return USER_ERROR
        finally:
            if tmp and os.path.exists(tmp.name):
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass
        if not transcript:
            return "I couldn't make out that voice note, sir \u2014 could you type it?"
        # The transcript enters as a normal text turn (R0/R1/R2 rules apply).
        return self.process_message({**message, "text": transcript,
                                     "voice": None}) or ""

    def _download_capped(self, file_path: str, dest: str) -> None:
        """Stream the file with a hard byte cap enforced DURING transfer."""
        url = f"{self._api_base}/file/bot{self._token}/{file_path}"
        req = urllib.request.Request(url)
        seen = 0
        try:
            with urllib.request.urlopen(req, timeout=60) as resp, \
                    open(dest, "wb") as fh:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    seen += len(chunk)
                    if seen > VOICE_MAX_BYTES:
                        raise ValueError("voice note exceeds 10MB cap")
                    fh.write(chunk)
        except Exception as exc:
            try:
                os.unlink(dest)
            except OSError:
                pass
            raise

    # -- polling -------------------------------------------------------------- #
    def validate(self) -> bool:
        """Startup getMe check (M-I23). Empty token -> disabled, never a loop."""
        if not self._token:
            self._disabled_reason = "phone not configured: no bot token"
            return False
        body = self._api("getMe", timeout=10)
        if body.get("ok"):
            return True
        self._disabled_reason = (
            f"telegram getMe failed: {self._redact(str(body.get('description')))}")
        return False

    def poll_once(self) -> int:
        """Fetch updates, validate, enqueue (handle inline). Returns count."""
        if self._disabled_reason:
            return 0
        body = self._api("getUpdates",
                         {"offset": self._offset, "timeout": 30,
                          "allowed_updates": ["message"]},
                         timeout=40)
        if not body.get("ok"):
            status = body.get("_http_status")
            if status == 401:
                self._auth_failures += 1
                if self._auth_failures >= 3:
                    self._disabled_reason = (
                        "telegram auth failed 3x: check the bot token "
                        "in Settings \u2192 Phone")
                    self._on_alert(self._disabled_reason)
            return 0
        self._auth_failures = 0
        updates = body.get("result") or []
        for upd in updates:
            self._offset = max(self._offset, int(upd.get("update_id", 0)) + 1)
            # Skip stale updates (>24h) — a week-old "do X" must not resurface.
            msg = upd.get("message") or {}
            if self._clock() - int(msg.get("date", 0)) > 24 * 3600:
                continue
            reply = self.process_message(msg)
            if reply:
                chat = msg.get("chat") or {}
                try:
                    self.send(chat.get("id"), reply)
                except Exception:
                    pass  # send failure never kills the poll loop
        return len(updates)

    def run_forever(self, poll_interval: float = 1.0) -> None:
        """Poll loop. Only enqueues/handles; backoff on auth failure (C-I4)."""
        backoff = [5, 20, 60]
        while not self._stop.is_set():
            try:
                n = self.poll_once()
            except Exception:
                n = 0
            if self._disabled_reason:
                return
            if self._auth_failures:
                wait = backoff[min(self._auth_failures - 1, len(backoff) - 1)]
                self._stop.wait(wait)
            else:
                self._stop.wait(poll_interval if n else min(poll_interval * 10, 10))

    def stop(self) -> None:
        self._stop.set()
