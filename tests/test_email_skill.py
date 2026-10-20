"""Tests for skills/email — drafts-first email (Team 21 steals).

Covers: manifest validity + clean static scan; not-configured honesty;
hash-bound send (approve -> edit -> refused, wrong hash refused, happy
path sends exactly once); rate limit (persisted); audit redaction (no
body / no password bytes in audit.jsonl); IMAP list/read through fake
transports incl. OTP redaction, size cap, and the DCL-unavailable
fail-closed path; SMTP failure semantics (connect = failed, mid-send =
unknown); and end-to-end registry dispatch.
"""

import importlib.util
import json
import shutil
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / "skills" / "email"
SKILL_PATH = SKILL_DIR / "skill.py"
spec = importlib.util.spec_from_file_location("email_skill", SKILL_PATH)
em = importlib.util.module_from_spec(spec)
spec.loader.exec_module(em)

from jarvis.skills.registry import SkillContext, SkillManifest, SkillRegistry, scan_skill

ALLOW_ALL = lambda tool, tier, args, ctx: True  # noqa: E731

PASSWORD = "sup3r-secret-app-password"
BODY_TOKEN = "TOPSECRET-BODY-TOKEN-xyz"
ACCOUNT_SECRETS = {
    "email:main:imap_host": "imap.example.com",
    "email:main:smtp_host": "smtp.example.com",
    "email:main:user": "owais@example.com",
    "email:main:password": PASSWORD,
}


class _Ctx:
    def __init__(self, jail):
        self.jail_dir = str(jail)


class FakeSecrets:
    def __init__(self, values):
        self.values = values

    def get(self, name, default=None):
        return self.values.get(name, default)


class FakeSMTP:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail
        self.quit_called = False

    def send_message(self, msg):
        if self.fail:
            raise RuntimeError("connection dropped mid-send")
        self.sent.append(msg)

    def quit(self):
        self.quit_called = True


HDR1 = (b"From: Alice Example <alice@example.com>\r\n"
        b"Subject: Lunch tomorrow?\r\n"
        b"Date: Mon, 19 Oct 2026 10:00:00 +0530\r\n\r\n")
HDR2 = (b"From: Bank Alerts <alerts@bank.example>\r\n"
        b"Subject: Statement ready\r\n"
        b"Date: Tue, 20 Oct 2026 09:15:00 +0530\r\n\r\n")
FULL2 = HDR2 + (b"Hello Owais,\r\n"
                b"Your verification code is 482913. "
                b"It expires in 10 minutes.\r\n")


class FakeIMAP:
    def __init__(self):
        self.headers = {b"1": (b"\\Seen", HDR1), b"2": (b"", HDR2)}
        self.full = {b"2": FULL2}
        self.queries = []

    def select(self, folder, readonly=False):
        return ("OK", [b"2"])

    def search(self, charset, criteria):
        return ("OK", [b"1 2"])

    def fetch(self, mid, query):
        self.queries.append(query)
        mid = mid if isinstance(mid, bytes) else str(mid).encode()
        if "HEADER.FIELDS" in query:
            if mid not in self.headers:
                return ("OK", [])
            flags, raw = self.headers[mid]
            meta = (mid + b" (FLAGS (" + flags +
                    b") BODY[HEADER.FIELDS (FROM SUBJECT DATE)] {" +
                    str(len(raw)).encode() + b"}")
            return ("OK", [(meta, raw), b")"])
        if mid not in self.full:
            return ("OK", [])
        raw = self.full[mid]
        meta = mid + b" (BODY[] {" + str(len(raw)).encode() + b"}"
        return ("OK", [(meta, raw), b")"])

    def logout(self):
        return ("BYE", [b"bye"])


@pytest.fixture()
def ctx(tmp_path):
    return _Ctx(tmp_path)


@pytest.fixture()
def configured(monkeypatch):
    monkeypatch.setattr(em, "SECRETS_PROVIDER", FakeSecrets(ACCOUNT_SECRETS))


@pytest.fixture()
def smtp_box(monkeypatch):
    box = {"conn": FakeSMTP(), "cfgs": []}

    def factory(cfg):
        box["cfgs"].append(cfg)
        return box["conn"]

    monkeypatch.setattr(em, "SMTP_FACTORY", factory)
    return box


@pytest.fixture()
def imap_box(monkeypatch):
    box = {"conn": FakeIMAP()}

    def factory(cfg):
        return box["conn"]

    monkeypatch.setattr(em, "IMAP_FACTORY", factory)
    return box


def _draft(ctx, **kw):
    args = {"to": "friend@example.com", "subject": "Hello there",
            "body": f"Body text. {BODY_TOKEN}"}
    args.update(kw)
    return em.handle("email_draft", args, ctx)


# ---------------------------------------------------------------------------
# Manifest, scan, lazy transports
# ---------------------------------------------------------------------------

class TestBoundary:
    def test_manifest_validates_with_expected_tools_and_tiers(self):
        raw = json.loads((SKILL_DIR / "skill.json").read_text(encoding="utf-8"))
        manifest = SkillManifest.from_dict(raw, source="email")
        assert manifest.name == "email"
        tiers = {t.name: t.tier for t in manifest.tools}
        assert tiers == {"email_list": 1, "email_read": 1,
                         "email_draft": 1, "email_send": 2}
        assert set(raw["capabilities"]) == {"net.outbound", "fs.read",
                                            "fs.write"}

    def test_static_scan_is_clean(self):
        assert scan_skill(SKILL_DIR) == []

    def test_transports_are_lazy(self):
        # No imaplib/smtplib import at module top level: real connections
        # are built only inside the factory functions.
        import ast
        tree = ast.parse(SKILL_PATH.read_text(encoding="utf-8"))
        top_imports = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                top_imports.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                top_imports.add(node.module.split(".")[0])
        assert "imaplib" not in top_imports
        assert "smtplib" not in top_imports


# ---------------------------------------------------------------------------
# Not configured: honest everywhere
# ---------------------------------------------------------------------------

class TestNotConfigured:
    @pytest.fixture(autouse=True)
    def _no_secrets(self, monkeypatch):
        monkeypatch.setattr(em, "SECRETS_PROVIDER", FakeSecrets({}))

    def test_list_is_honest(self, ctx):
        out = em.handle("email_list", {}, ctx)
        assert out["configured"] is False
        assert "email:main:imap_host" in out["note"]

    def test_read_is_honest(self, ctx):
        out = em.handle("email_read", {"id": "7"}, ctx)
        assert out["configured"] is False

    def test_draft_still_stores_locally(self, ctx, tmp_path):
        out = _draft(ctx)
        assert out["configured"] is False
        assert out["draft_id"] and out["hash"]
        store = json.loads((tmp_path / "drafts.json").read_text())
        assert out["draft_id"] in store["drafts"]

    def test_send_refuses_honestly(self, ctx):
        draft = _draft(ctx)
        out = em.handle("email_send",
                        {"draft_id": draft["draft_id"], "hash": draft["hash"]},
                        ctx)
        assert out["sent"] is False
        assert out["configured"] is False


# ---------------------------------------------------------------------------
# Hash-bound send — the core proof
# ---------------------------------------------------------------------------

class TestHashBoundSend:
    def test_happy_path_sends_once(self, ctx, configured, smtp_box, tmp_path):
        draft = _draft(ctx)
        out = em.handle("email_send",
                        {"draft_id": draft["draft_id"], "hash": draft["hash"]},
                        ctx)
        assert out["sent"] is True
        assert len(smtp_box["conn"].sent) == 1
        msg = smtp_box["conn"].sent[0]
        assert msg["To"] == "friend@example.com"
        assert msg["Subject"] == "Hello there"
        store = json.loads((tmp_path / "drafts.json").read_text())
        assert store["drafts"][draft["draft_id"]]["status"] == "sent"
        again = em.handle("email_send",
                          {"draft_id": draft["draft_id"],
                           "hash": draft["hash"]}, ctx)
        assert again["sent"] is False
        assert "already sent" in again["reason"]
        assert len(smtp_box["conn"].sent) == 1

    def test_wrong_hash_refused(self, ctx, configured, smtp_box):
        draft = _draft(ctx)
        out = em.handle("email_send",
                        {"draft_id": draft["draft_id"], "hash": "0" * 64},
                        ctx)
        assert out["sent"] is False
        assert "changed after approval" in out["reason"]
        assert smtp_box["conn"].sent == []

    def test_edit_after_approval_invalidates(self, ctx, configured,
                                              smtp_box, tmp_path):
        draft = _draft(ctx)
        # Tamper with the stored body — the approval hash no longer
        # matches the current content, however the edit happened.
        path = tmp_path / "drafts.json"
        store = json.loads(path.read_text())
        store["drafts"][draft["draft_id"]]["body"] = "tampered body"
        path.write_text(json.dumps(store))
        out = em.handle("email_send",
                        {"draft_id": draft["draft_id"], "hash": draft["hash"]},
                        ctx)
        assert out["sent"] is False
        assert "changed after approval" in out["reason"]
        assert out["current_hash"] != draft["hash"]
        assert smtp_box["conn"].sent == []

    def test_edit_and_rehash_still_refused(self, ctx, configured,
                                           smtp_box, tmp_path):
        # Even an edit that updates the stored hash cannot reuse the old
        # approval: current != approved.
        draft = _draft(ctx)
        path = tmp_path / "drafts.json"
        store = json.loads(path.read_text())
        rec = store["drafts"][draft["draft_id"]]
        rec["body"] = "new body"
        rec["hash"] = em.content_hash(rec["to"], rec["subject"], rec["body"])
        path.write_text(json.dumps(store))
        out = em.handle("email_send",
                        {"draft_id": draft["draft_id"], "hash": draft["hash"]},
                        ctx)
        assert out["sent"] is False
        assert smtp_box["conn"].sent == []

    def test_unknown_draft_refused(self, ctx, configured, smtp_box):
        out = em.handle("email_send",
                        {"draft_id": "d_nope", "hash": "0" * 64}, ctx)
        assert out["sent"] is False
        assert "no such draft" in out["reason"]


# ---------------------------------------------------------------------------
# Rate limit (persisted)
# ---------------------------------------------------------------------------

class TestRateLimit:
    def test_limit_enforced_and_persisted(self, ctx, configured, smtp_box,
                                          tmp_path, monkeypatch):
        monkeypatch.setattr(em, "MAX_SENDS_PER_HOUR", 2)
        for i in range(2):
            draft = _draft(ctx, subject=f"Msg {i}")
            out = em.handle("email_send",
                            {"draft_id": draft["draft_id"],
                             "hash": draft["hash"]}, ctx)
            assert out["sent"] is True
        draft = _draft(ctx, subject="Msg 3")
        out = em.handle("email_send",
                        {"draft_id": draft["draft_id"], "hash": draft["hash"]},
                        ctx)
        assert out["sent"] is False
        assert "rate limit" in out["reason"]
        assert len(smtp_box["conn"].sent) == 2
        state = json.loads((tmp_path / "rate_state.json").read_text())
        assert len(state["main"]) == 2
        assert all(time.time() - t < 3600 for t in state["main"])


# ---------------------------------------------------------------------------
# Audit: metadata yes, bodies/passwords never
# ---------------------------------------------------------------------------

class TestAudit:
    def test_audit_records_metadata_only(self, ctx, configured, smtp_box,
                                         tmp_path):
        draft = _draft(ctx)
        em.handle("email_send",
                  {"draft_id": draft["draft_id"], "hash": draft["hash"]}, ctx)
        draft2 = _draft(ctx, subject="Second")
        em.handle("email_send",
                  {"draft_id": draft2["draft_id"], "hash": "0" * 64}, ctx)
        raw = (tmp_path / "audit.jsonl").read_bytes()
        assert PASSWORD.encode() not in raw
        assert BODY_TOKEN.encode() not in raw
        text = raw.decode()
        assert "friend@example.com" in text
        assert "Hello there" in text
        assert draft["hash"] in text
        events = [json.loads(line)["event"] for line in text.splitlines()]
        assert events == ["send", "send_refused"]


# ---------------------------------------------------------------------------
# SMTP failure semantics: connect = failed, mid-send = unknown
# ---------------------------------------------------------------------------

class TestFailureSemantics:
    def test_connect_failure_is_failed(self, ctx, configured, monkeypatch):
        def bad_factory(cfg):
            raise RuntimeError("cannot connect")

        monkeypatch.setattr(em, "SMTP_FACTORY", bad_factory)
        draft = _draft(ctx)
        out = em.handle("email_send",
                        {"draft_id": draft["draft_id"], "hash": draft["hash"]},
                        ctx)
        assert out["sent"] is False
        assert out["outcome"] == "failed"

    def test_mid_send_failure_is_unknown(self, ctx, configured, monkeypatch,
                                         tmp_path):
        conn = FakeSMTP(fail=True)
        monkeypatch.setattr(em, "SMTP_FACTORY", lambda cfg: conn)
        draft = _draft(ctx)
        out = em.handle("email_send",
                        {"draft_id": draft["draft_id"], "hash": draft["hash"]},
                        ctx)
        assert out["sent"] is False
        assert out["outcome"] == "unknown"
        assert "Sent folder" in out["reason"]
        # Conservatively counted against the rate budget.
        state = json.loads((tmp_path / "rate_state.json").read_text())
        assert len(state["main"]) == 1


# ---------------------------------------------------------------------------
# IMAP list/read via fake transport
# ---------------------------------------------------------------------------

class TestListRead:
    def test_list_headers_newest_first(self, ctx, configured, imap_box):
        out = em.handle("email_list", {}, ctx)
        assert out["configured"] is True
        assert out["count"] == 2
        first, second = out["messages"]
        assert first["id"] == "2" and first["unread"] is True
        assert first["subject"] == "Statement ready"
        assert "bank.example" in first["from"]
        assert second["id"] == "1" and second["unread"] is False
        # Listing never fetches bodies.
        assert all("HEADER.FIELDS" in q for q in imap_box["conn"].queries)

    def test_read_redacts_otp(self, ctx, configured, imap_box):
        out = em.handle("email_read", {"id": "2"}, ctx)
        assert out["found"] is True
        assert "482913" not in out["body"]
        assert "[REDACTED:SECRET]" in out["body"]
        assert out["redacted"] is True
        assert out["truncated"] is False

    def test_read_size_cap(self, ctx, configured, imap_box):
        out = em.handle("email_read", {"id": "2", "max_chars": 10}, ctx)
        assert out["truncated"] is True
        assert len(out["body"]) <= 10

    def test_read_unknown_id(self, ctx, configured, imap_box):
        out = em.handle("email_read", {"id": "99"}, ctx)
        assert out["found"] is False

    def test_read_body_withheld_without_dcl(self, ctx, configured, imap_box,
                                            monkeypatch):
        monkeypatch.setattr(em, "_DCL", None)
        out = em.handle("email_read", {"id": "2"}, ctx)
        assert out["body"] is None
        assert "withheld" in out["body_withheld"]


# ---------------------------------------------------------------------------
# End-to-end through the real registry pipeline
# ---------------------------------------------------------------------------

class TestRegistryDispatch:
    @pytest.fixture()
    def reg(self, tmp_path):
        skills = tmp_path / "skills"
        skills.mkdir()
        shutil.copytree(SKILL_DIR, skills / "email")
        data = tmp_path / "data"
        data.mkdir()
        registry = SkillRegistry(skills, data)
        registry.discover()
        return registry

    def _skill_ctx(self, tmp_path):
        jail = tmp_path / "jail"
        jail.mkdir(exist_ok=True)
        return SkillContext(skill_name="email",
                            capabilities=["net.outbound", "fs.read",
                                          "fs.write"],
                            jail_dir=str(jail))

    def test_quarantined_until_approved(self, reg, tmp_path):
        ctx = self._skill_ctx(tmp_path)
        assert reg.quarantine() == ["email"]
        out = reg.dispatch("email_draft",
                           {"to": "a@b.c", "subject": "s", "body": "b"},
                           ctx, ALLOW_ALL)
        assert out["ok"] is False
        assert out["error"]["code"] == "skill_quarantined"

    def test_dispatch_draft_and_hash_bound_send(self, reg, tmp_path):
        ctx = self._skill_ctx(tmp_path)
        reg.approve("email")
        out = reg.dispatch("email_draft",
                           {"to": "a@b.c", "subject": "Hi", "body": "text"},
                           ctx, ALLOW_ALL)
        assert out["ok"] is True
        result = out["result"]
        assert result["draft_id"] and result["hash"]
        # The registry dispatches with its own jail: data_dir/<skill>.
        on_disk = json.loads(
            (reg.data_dir / "email" / "drafts.json").read_text())
        assert result["draft_id"] in on_disk["drafts"]
        # Wrong approval hash -> refusal through the full pipeline
        # (deterministic in any config state: hash is checked first).
        out = reg.dispatch("email_send",
                           {"draft_id": result["draft_id"], "hash": "0" * 64},
                           ctx, ALLOW_ALL)
        assert out["ok"] is True
        assert out["result"]["sent"] is False
        # Unknown draft -> honest refusal.
        out = reg.dispatch("email_send",
                           {"draft_id": "d_nope", "hash": "0" * 64},
                           ctx, ALLOW_ALL)
        assert out["ok"] is True
        assert out["result"]["sent"] is False
