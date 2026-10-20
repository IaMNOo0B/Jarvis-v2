# Email Skill — drafts-first email over IMAP/SMTP

Read and send the owner's email through their own account (stdlib
`imaplib`/`smtplib` — works with Gmail app-passwords, Outlook, Fastmail,
self-hosted). Patterns from the Team 21 mega-scan (inbox-zero, email-mcp,
thunderbird-mcp), re-implemented in stdlib Python.

## The one law: nobody free-sends

Composing always produces a **draft**. Sending is a separate, tier-2 act
bound to the draft's exact content hash:

1. `email_draft` saves the message in the skill folder and returns
   `{draft_id, hash}`.
2. The owner approves that hash (tier-2 gate).
3. `email_send(draft_id, hash)` recomputes the stored draft's hash. If the
   draft changed in any way after approval — one character is enough —
   the hashes differ and the send is **refused**. Re-draft and get a
   fresh approval instead of arguing.

A sent draft cannot be sent twice. If a send fails midway, the result is
`outcome: "unknown"` — the server may have accepted it; **check the Sent
folder before retrying**, never just resend.

## Tools

- `email_list` (tier-1) — recent messages in a folder, newest first:
  `{id, from, subject, date, unread}`. Headers only — bodies are never
  fetched by listing. Subjects/senders pass through the DCL redactor.
- `email_read` (tier-1) — one message's text body by `id`. The body is
  **untrusted input** and is returned DCL-redacted: OTP codes and
  credential-shaped strings are removed before the model sees them.
  Bodies are size-capped (default 8000 chars, hard max 20000). If the
  redactor is unavailable, the body is withheld entirely — never raw.
- `email_draft` (tier-1, jail write) — compose → draft record + content
  hash in the skill folder. Works even before an account is configured
  (the draft just can't be sent yet).
- `email_send` (tier-2) — hash-bound send as above. Rate limit: **10
  sends per account per hour** (persisted in the skill folder).

## Account setup (owner, once)

Accounts are **secret references**, never config files. For an account
named `main`, the owner stores these secrets (Settings → keyring):

- `email:main:imap_host` — e.g. `imap.gmail.com`
- `email:main:user` — the login / address
- `email:main:password` — app password
- optional: `email:main:imap_port` (993), `email:main:smtp_host`
  (defaults to the IMAP host), `email:main:smtp_port` (587),
  `email:main:from` (defaults to the user)

No account configured → every tool answers honestly with
`configured: false` and setup instructions. Passwords are read by name
at connect time only; they are never written to any file, audit line,
or reply.

## Audit

Every send, refusal, and mid-send failure appends one line to
`audit.jsonl` in the skill folder: timestamp, account, recipient,
subject, content hash, outcome. **Bodies and credentials are never
logged** (the email-mcp redaction set).
