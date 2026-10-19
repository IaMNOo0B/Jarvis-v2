# Privacy Engineering & Data Lifecycle for JARVIS

**OMEGA §19 gaps.** Written 2026-10-19. LEARNING ONLY — no project code touched.

**Skip-if-learned applied:** OS keyring secrets (R9), data minimization, prompt-injection-as-exfiltration, log redaction — all covered elsewhere; not re-taught. This file covers only the gaps: lifecycle model, deletion verification, differential privacy verdict, consent/revocation, cross-device sync.

---

## 1. Data Lifecycle Model for JARVIS

Seven stages. For each: what data exists, where it lives (concrete files), who can access it.

### Stage 1 — Collection

| Source | Data captured | Lives in |
|---|---|---|
| Voice loop | Audio waveforms, transcripts | RAM only (never disk by default); transcripts → session log |
| Screen watcher | Screenshots (RAM-only) | RAM only; discarded after brain judgment |
| Browser automation | Page text, cookies, session tokens | Browser profile dir; page text → tool results → session log |
| User chat | Messages, corrections, preferences | `memory_bank/` SQLite + event log |
| Tool results | File contents, API responses, web data | Session log, skill working dirs |
| System | Mic/camera device handles, OS username, paths | Config, logs |

**Access:** the JARVIS process (user's account). No network exfiltration by default. Cloud brain calls (Gemini/Groq/OpenRouter) send: current turn text + tool results + compressed memory context. This is the one place user data leaves the machine — governed by provider privacy policies, not by JARVIS.

### Stage 2 — Processing

- In-memory: STT transcription, brain inference, TTS synthesis.
- Bystander audio (other voices in mic range) is processed transiently and must never be persisted [R13 privacy-safe defaults].
- Webhook/poll payloads (Telegram) are **untrusted content** → REA evidence markers before reaching the brain.

### Stage 3 — Storage (the concrete map)

| Store | File(s) | Contents | At-rest protection |
|---|---|---|---|
| Event log | `%APPDATA%/JARVIS/events.jsonl` (+ rotated) | Full-fidelity: user messages, tool args/results, brain decisions | NTFS ACL (user-only); consider SQLCipher for memories |
| Memory DB | `%APPDATA%/JARVIS/memory.db` (SQLite WAL) | Episodic/semantic/procedural memories with provenance, confidence, expiry | NTFS ACL; `PRAGMA key` option |
| Vector store | `%APPDATA%/JARVIS/vectors/` (Chroma) | Embeddings of memory chunks | NTFS ACL; embeddings are reversible-ish — treat as sensitive |
| FTS5 index | Inside `memory.db` | Tokenized copies of memory text — **survives row deletion** (see §2) |
| App logs | `%APPDATA%/JARVIS/jarvis.log` (+ rotated ×3) | Structured logs, trace_ids | Redaction processor (fail-closed) |
| Crash reports | `%APPDATA%/JARVIS/crashes/` | Stack traces, last events | Exclude from debug bundles by default |
| Backups | `%APPDATA%/JARVIS/backups/` | Rotating DB snapshots | Same ACL; included in deletion scope |
| Skill working dirs | `%APPDATA%/JARVIS/skills/<name>/` | Downloads, temp files from tool runs | Swept on a schedule |
| Secrets | **OS keyring only** (Windows Credential Manager / DPAPI) | API keys, OAuth refresh tokens | Never in files, never in logs |
| Config | `%APPDATA%/JARVIS/settings.local.yaml` | Non-secret preferences | May contain paths/usernames — low sensitivity |

### Stage 4 — Retrieval

- Memory retrieval (hybrid search) pulls from memory DB + vector store + FTS5.
- **Isolation rule:** `profile_id` on every retrieval call; separate SQLite files per profile is the strongest option (trivial to implement, impossible to forget a `WHERE`).
- Retrieval contamination risk: deleted-then-reindexed content must not resurrect via stale embeddings — re-embed or tombstone on delete.

### Stage 5 — Sharing

| Recipient | What leaves | Basis |
|---|---|---|
| Cloud LLM providers | Turn text, tool results, compressed context | Needed for the brain; user-configurable (local-only mode exists) |
| Skill webhooks/APIs | Only what the skill's declared scope allows | Capability permissions (Deno-style) |
| Crash/debug bundles | Logs, traces | **Opt-in only**; redaction pass first |
| Nobody else | — | No analytics, no telemetry without explicit opt-in |

### Stage 6 — Retention

- Session logs: user-configurable retention (default suggestion: 90 days, then auto-summarize → archive → delete).
- Memories: per-memory TTL (`until:` temporal markers); unreinforced memories decay per the attention-economics rule.
- Logs: rotation (1MB × 3) + age-based purge.
- Backups: rotating (e.g., 7 daily + 4 weekly); **backups are the deletion lag** — see §2.
- Rule: every store has a named retention policy. A store with no retention policy is a compliance gap (GDPR Art. 5(1)(e), Art. 30).

### Stage 7 — Deletion

See §2 — the full checklist.

---

## 2. Deletion Verification: What "Delete My Data" Must Actually Do

### Why `DELETE FROM` isn't enough [VC]

Three independent mechanisms keep "deleted" data recoverable in SQLite:

1. **Freelist pages.** SQLite marks the page free but doesn't zero the bytes. The old row content sits in the file until overwritten by a future write. Forensic recovery of freelist pages is routine.
   - Mitigation: `PRAGMA secure_delete = ON` (overwrites deleted content with zeros; default is OFF). Cost: more CPU/I/O.
   - **WAL caveat:** with `journal_mode=WAL`, `secure_delete=ON` does NOT scrub until a checkpoint occurs — and the old content may remain in the `-wal` file even after checkpoint (WAL files are only truncated/reset on clean shutdown, not on checkpoint).
2. **FTS5 index.** The full-text index keeps its **own copies** of indexed text, maintained separately from source tables. Delete the row from the source table and the FTS index still has the tokens — searchable.
   - Mitigation: delete from the FTS table too (or use content-sync triggers / rebuild the index after deletion).
3. **WAL/journal files.** Recent writes live in `memory.db-wal`; transactions in `memory.db-journal`. Both retain pre-delete content until checkpointed/cleaned.

Sources: antonz.org SQLite secure-delete analysis; dev.to SQLite forensics writeup (FTS, free pages, VACUUM); SQLite forensic toolkit docs on WAL behavior.

### The deletion checklist (every store, every time)

When the user says "forget X" or "delete my data":

- [ ] **Event log:** tombstone + purge entries; rotated JSONL files included (grep all rotations)
- [ ] **Memory DB:** `DELETE` from source tables **and** FTS5 index; `PRAGMA secure_delete=ON` set; then `VACUUM` to actually reclaim and rewrite pages
- [ ] **WAL files:** force `wal_checkpoint(TRUNCATE)` after deletion, or close all connections cleanly so `-wal`/`-shm` are removed
- [ ] **Vector store:** delete embeddings for the chunk IDs (embeddings can leak content — they're not opaque); re-index
- [ ] **Caches:** embedding cache (content-hash keys), prompt cache, tool-result cache — invalidate entries referencing the data
- [ ] **Backups:** mark for exclusion from restore ("beyond use"); document that physical purge happens on backup rotation expiry. Never restore deleted data from backup into live systems.
- [ ] **Skill working dirs:** sweep temp files, downloads, browser profile artifacts tied to the data
- [ ] **Logs:** purge matching lines from `jarvis.log` rotations (or document log-retention expiry as the bound)
- [ ] **Crash reports:** purge if they contain the data
- [ ] **Sync replicas:** if cross-device sync exists, propagate tombstones to all devices (§5)
- [ ] **Secrets:** if the "data" includes credentials, rotate them (deletion ≠ revocation — a copied key is still valid)
- [ ] **Verification:** after deletion, run a verification pass — query the stores, grep the files for known-unique strings, confirm FTS returns nothing. **Never claim erasure without this check.**
- [ ] **Receipt:** record what was deleted, from which stores, when, and what remains pending (e.g., backup expiry date). Honest receipts beat false "forgotten" claims.

### The honest bounds

- **Filesystem reality:** on SSDs with wear-leveling, even overwritten file bytes may persist in flash cells unreachable via the OS. True forensic-proof deletion needs full-disk encryption (BitLocker) so "deletion" = destroying the key. Recommendation: document that JARVIS relies on OS-level disk encryption as the last line; app-level deletion handles the logical layer.
- **Backups:** GDPR practice accepts "beyond use" (flagged, unrestorable without compliance review) until natural expiry — but it must be documented and communicated, not silent. An erasure receipt that says "forgotten" while a restorable backup sits untouched is a misrepresentation.
- **Third parties:** data already sent to cloud providers (Gemini/Groq/OpenRouter) or skill APIs cannot be recalled by JARVIS. The lifecycle model must state this plainly: local deletion is complete; provider-side retention follows provider policies. This is a design argument for local-first defaults.

---

## 3. Differential Privacy (Scoped)

### The core idea, plainly [VC]

Differential privacy (Dwork et al., 2006) is a mathematical promise about a **computation**, not a dataset: the output of the computation looks nearly the same whether or not any single person's data was included. Achieved by adding carefully calibrated random noise.

The knob is **ε (epsilon)** — the privacy budget. Small ε = strong privacy, noisy results. Large ε = accurate results, weak privacy. ε bounds how much an attacker's belief about you can shift after seeing the output (at ε=0.01, ~1% — negligible; at high ε, the guarantee is decorative).

Key subtlety: DP protects **individuals within an aggregate**. It answers "what can we learn about the group without learning about any person?" It does not protect a single user's own data from the system that holds it.

Sources: Dwork et al. 2006 (foundational); Apple/Google/Census Bureau deployments; metavert.io and openmined.org explainers.

### Honest verdict for JARVIS

**Not needed for the core product. [HC]**

Reason: DP solves the multi-user aggregate problem ("publish statistics about 10,000 users without exposing user #4,132"). JARVIS is a **single-user, local-first** system. There is no aggregate, no second user to protect the first from, no published statistics. Adding noise to Owais's own memories would destroy utility for zero privacy gain — the "adversary" DP defends against doesn't exist in this threat model.

**Where it WOULD matter — the three tripwires:**

1. **Telemetry leaves the machine.** If JARVIS ever ships usage analytics (even "anonymous"), DP is the right tool — Apple's model (on-device DP for emoji/typing stats) is the template. Until then: no telemetry without opt-in, no DP needed.
2. **Model trains on user data.** If the local brain is ever fine-tuned on Owais's conversations (continual learning track), DP-SGD bounds how much any single conversation can influence the weights. Relevant only if weights leave the machine or are shared.
3. **Multi-user futures.** If JARVIS ever becomes a household product (family profiles on one machine), cross-profile aggregate features need DP or hard isolation (isolation is simpler — see §1).

**Rule for the playbook:** DP is a tripwire, not a todo. Revisit if and only if: telemetry ships, weights train on user data and leave the device, or a second user profile is added. Until then, the privacy budget is better spent on: disk encryption, keyring discipline, log redaction, and the deletion checklist above.

---

## 4. Consent & Revocation: The Permission Lifecycle

### The four states

```
GRANT → ACTIVE (scoped, expiring) → REVOKED → PURGED
                  ↓
              EXPIRED → (re-grant or purge)
```

### Grant

- **Explicit, scoped, plain-language.** "JARVIS wants to read your Gmail to find receipts" — not "allow access to Google services."
- Scopes are **capabilities** (Deno-style): `gmail.read`, `calendar.write`, `fs.write:~/Documents` — never blanket grants.
- Record: what was granted, to which component, when, for what purpose, with what expiry.

### Active (scoped, expiring)

- **Expiry by default.** Permissions should have lifetimes (session / 24h / 30d / until-revoked). A permission granted in 2026 should not silently authorize actions in 2028.
- **Least privilege in time as well as scope:** a one-time task gets a one-time grant.
- **Visibility:** the user can inspect active grants (Settings → Permissions). Invisible permissions are un-revoked permissions.

### Revocation

- **Immediate effect:** revoked permission stops authorizing new actions at once. In-flight actions complete or roll back (never leave half-written state).
- **The hard question — what happens to data collected under a revoked permission?**
  - **Derived artifacts stay; source access dies.** If Gmail-read produced a summary the user kept, the summary is the user's data now. But JARVIS loses the ability to re-fetch, refresh, or re-derive.
  - **Cached credentials are destroyed:** OAuth refresh tokens deleted from keyring on revocation. A revoked permission with a live refresh token is not revoked.
  - **Provenance matters:** data tagged with its collection permission; on revocation, the system can show "this memory came from Gmail (access revoked)" and offer purge.
  - **No silent re-grant:** a skill must never re-request a revoked permission without the user explicitly re-granting. Repeated prompts after revocation = dark pattern.

### Purge

- Revocation ≠ deletion. Offer both: "revoke access" and "revoke + delete everything collected under it." The second runs the §2 checklist scoped to that permission's data.
- Audit trail of the lifecycle itself (granted/revoked/purged, timestamps) is kept — this is accountability metadata, not user content, and should itself have a retention policy.

### Design principles

1. **Revocation is a first-class action**, as easy as granting (one tap, not a settings maze).
2. **Expiry is the default; permanence is the exception** requiring explicit choice.
3. **Credentials die with the permission** (keyring deletion, not just a flag flip).
4. **Provenance-tagged data** makes "delete everything from X" actually executable.

---

## 5. Cross-Device Sync (Phone + PC Later)

### The problem

JARVIS on PC today; phone companion later. Memories, preferences, task state should follow the user. Threat model: sync infrastructure (relay server, or even LAN) must not become a plaintext data store.

### What syncs vs what stays local-only

| Syncs (E2E encrypted) | Stays local-only |
|---|---|
| Memories (semantic/episodic) | Voice audio waveforms |
| Preferences, settings | Screenshots / screen captures |
| Task state, reminders, scheduler | Browser cookies/session tokens |
| Conversation summaries | Crash dumps |
| Skill list + configs (not keys) | API keys / OAuth tokens (re-auth per device) |

**Rule:** secrets never sync. Each device holds its own credentials in its own OS keyring. A synced API key is a breach waiting for a relay compromise.

### Conflict-free approaches

- **CRDTs (Conflict-free Replicated Data Types):** the right primitive for offline-first sync. Two devices edit independently while offline; on reconnect, changes merge deterministically — no conflict-resolution code, no last-write-wins data loss. Convergence is a theorem, not a hope. Libraries: **Automerge**, **Yjs**, **Loro** (all have Python or FFI options; Automerge has Python bindings).
- **What fits CRDTs:** preferences (LWW registers), memory collections (add-wins sets — note: deletion needs tombstones, which interacts with §2's purge requirement), task lists.
- **What doesn't:** the append-only event log is already conflict-free by construction (append-only + per-device sequence numbers + content hashing). Don't CRDT-ify the log; replicate it.
- **Vector embeddings:** don't sync embeddings; sync the source chunks and re-embed per device (embeddings are model-version-dependent anyway).

### End-to-end encryption options

1. **Device-held keys (recommended):** each device generates an X25519 keypair; devices pair via QR code (out-of-band key exchange, Signal-style). Sync payloads encrypted with a shared symmetric key (XChaCha20-Poly1305) derived from the pairing. The relay server (if any) sees ciphertext only.
2. **Password-derived key:** Argon2id from a user passphrase → sync key. Simpler UX, weaker against guessing; acceptable if the relay never sees the password.
3. **What the relay must never have:** plaintext, or the key. A relay that can decrypt is not E2E — it's just TLS with extra steps.

### Transport options (in order of preference)

1. **LAN sync first** (mDNS discovery, mutually-authenticated TLS 1.3 with device Ed25519 keys) — no internet, no relay, no third party. Works for phone + PC on the same network.
2. **P2P over internet** (libp2p, NAT traversal) — no central server; harder to make reliable.
3. **Dumb relay** (ciphertext blob store, e.g., self-hosted or minimal service) — the relay stores and forwards encrypted blobs; cannot read them. Simplest to operate reliably.

### Sync + deletion interaction (critical)

- **Tombstones must propagate.** A delete on PC must become a delete on the phone. CRDT delete-wins sets or explicit tombstone records in the replicated log.
- **A device that's offline during purge** must receive the tombstone on next sync and purge locally — plus its own §2 checklist (WAL, FTS, backups).
- **Backup exclusion:** synced devices are each other's implicit backups. The "beyond use" doctrine (§2) applies per device.

### Unknowns [MC/UK]

- Automerge/Yjs Python maturity for production use in 2026 — verify before choosing.
- QR-pairing UX on Windows + Android — prototype needed.
- Whether phone companion is Tauri-mobile, PWA, or Telegram-only (Telegram already covers remote access; full sync may be overkill — **revisit when the phone requirement is real**).

---

## Confidence & Unknowns Summary

| Claim | Confidence |
|---|---|
| SQLite freelist/FTS/WAL deletion remnants | [VC] — documented, forensically demonstrated |
| `secure_delete=ON` + VACUUM + checkpoint as the mitigation stack | [HC] — documented; WAL-truncation timing verified in sources |
| SSD wear-leveling bound (need disk encryption) | [HC] — standard storage reality |
| DP definition and epsilon semantics | [VC] — Dwork et al. 2006, widely deployed |
| "JARVIS doesn't need DP today" verdict | [HC] — follows from single-user local threat model |
| Consent lifecycle design (grant/scope/expiry/revoke/purge) | [HC] — synthesized from GDPR Art. 7/17 + capability-security literature |
| CRDTs as the sync primitive | [HC] — Automerge/Yjs/Loro established; convergence is proven |
| E2E key management options | [HC] — standard Signal-style patterns |
| Phone sync transport choice | [UK] — requirement not yet real; LAN-first is a recommendation, not a decision |

## Cross-links

- R9 (OS keyring) — §1 storage map, §4 credential destruction on revocation
- R13 (privacy-safe defaults) — §1 collection rules (RAM-only audio/screenshots)
- learn-advanced-cs.md §event-log-security — §1 storage map, §2 checklist
- learn-observability.md §redaction — §1 logs row, §2 logs checklist item
- learn-databases.md §isolation — §1 retrieval isolation rule
- learn-continual-learning.md §unlearning-warning — §2 (don't promise weight-level deletion)
- DECISION-PLAYBOOK S6 — §1 secrets row

## References (verified, no fabrications)

- SQLite secure delete: https://antonz.org/sqlite-secure-delete/
- SQLite forensics (FTS/free pages/VACUUM): https://dev.to/ikkun1222/sqlite-forensics-why-deleting-rows-doesnt-erase-secrets-fts-free-pages-vacuum-3oh9
- SQLite WAL forensics: https://sqliteforensictoolkit.com/q-when-is-secure-delete-not-secure/
- GDPR Art. 17 erasure + backups: https://www.probackup.io/blog/gdpr-and-backups-how-to-handle-deletion-requests
- GDPR erasure checklist (multi-store): https://bex.co/blog/2026/09/23/tenant-offboarding-gdpr-erasure-checklist
- DP explainer (Dwork 2006, Apple/Google/Census): https://metavert.io/differential-privacy
- DP epsilon semantics: https://openmined.org/blog/differential-privacy-using-pysyfy/
- E2E encrypted apps + CRDTs (Yjs/Automerge): https://gitnation.com/contents/building-end-to-end-encrypted-apps-web-and-react-native
- P2P CRDT sync (DefraDB): https://source.network/blog/how-peer-to-peer-communication-works-in-defradb
