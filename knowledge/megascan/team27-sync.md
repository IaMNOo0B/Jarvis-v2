# MEGA-SCAN TEAM 27 — Multi-Device Sync & Federation

Reverse-engineering how personal/local-first systems keep **the same memory and state on
PC + phone + other devices** — P2P sync, CRDTs, local-first data, encrypted sync —
for JARVIS v2's future (`session_store.py` is an append-only event log; `memory.py` is
SQLite/FTS5 with provenance tiers and supersede semantics; phone today = Telegram R0/R1/R2).

**Method note (honesty):** all reads are from local `git clone --depth 1` clones in
`.work27/` (GitHub API avoided per 429 protocol; oversized repos cloned
`--filter=blob:none --no-checkout` and read via `git show`). Facts are tagged
**[CODE]** (read in source), **[README]** (project's own documentation in-repo),
**[STRUCT]** (repo tree / file structure only), **[INFERENCE]**. Licenses were read from
the LICENSE file in each clone unless marked otherwise.

**Coverage: 43 repos attempted, 41 cloned, ~25 read at code level, ~16 structural/triage.**
Two honest gaps after 3 clone attempts each (large repos, slow link): **LocalSend** and
**Jazz** — not read, nothing below rests on them. Partial-clone casualties covered at
triage level only and flagged: SparkleShare (18 files), Peergos, Notesnook, Ente.

---

## 1. The CRDT cores — conflict resolution is *math*, not merging

### 1.1 automerge/automerge — MIT — the reference sync protocol
- **Model** [CODE — `rust/automerge/src/sync.rs`]: op-based CRDT document; every change
  is a hash-identified object in a DAG; document state = the op set at a set of *heads*.
- **Sync protocol** [CODE — same file, module docs]: based on arXiv:2012.00472
  (van Hardenberg–Kleppmann). Each peer keeps a per-peer `State`; messages carry the
  sender's **heads plus a Bloom filter of the change hashes it already has** (`sync/have.rs`
  in the C bindings mirrors this). The receiver computes exactly which changes the sender
  is missing and sends only those; the loop runs until both sides generate `None`
  ("nothing new") — sync termination is *proven by the protocol*, not by timeouts.
- **Conflict rule**: concurrent ops commute by construction; multi-value registers keep
  all concurrent values, LWW views pick deterministically by op-id ordering
  (Lamport-style counter, then actor id).
- **Python**: no maintained official Python binding in-repo (Rust core → JS/WASM + C FFI).
  → For v2, Automerge is a *design reference*, not a dependency.
- **Steal verdict:** the Bloom-filter "have" summary — a fixed-size, privacy-lean digest
  that lets two JARVIS devices find their delta without shipping the whole log.

### 1.2 y-crdt/y-crdt (Yrs) + Yjs/Yjs + y-crdt/pycrdt — all MIT — **the Python door**
- **Model** [CODE — `yrs/src/sync/protocol.rs`]: YATA algorithm. Every struct carries
  `(clientID, clock)`; the **state vector** (client → max clock) is a complete,
  compact summary of "what I have".
- **Sync protocol** [CODE — protocol.rs header comment, verbatim design]:
  **SyncStep1** = send your state vector → peer replies **SyncStep2** = exactly the
  structs you're missing + the delete set. P2P adds **SyncDone**; client-server reverses
  initiation so servers only answer. Two round trips to full convergence, and the
  *diff is computed from the vectors*, never by scanning content.
- **pycrdt** [CODE — repo root + README]: official Python bindings over Yrs —
  `Doc`, shared types, update encode/decode, 100% coverage badge. **This is the only
  production-grade CRDT that a stdlib-adjacent Python app can adopt as a library**
  (it is a compiled wheel, so v2's stdlib-only rule would need an explicit exception —
  flagged, not hidden).
- **Steal verdict:** the state-vector handshake shape (summary → delta → done-ack) is the
  exact protocol v2's device sync should speak, whatever the payload turns out to be.

### 1.3 loro-dev/loro — MIT — version vectors vs *frontiers*
- **Model** [CODE — `crates/loro-internal/src/sync.rs`; `skills/loro/references/sync-versioning-and-events.md`]:
  op id = `(peerId, counter)`; **peer IDs must never be reused** across sessions or
  convergence breaks. Text uses the Fugue algorithm (kills the interleaving artifacts
  YATA can produce).
- **Key distinction** [CODE — same doc]: *VersionVector* = explicit peer→counter map,
  best for sync/inclusion checks; *Frontiers* = the compact set of boundary op ids,
  best for checkpoints/time-travel. Loro keeps both and converts. Also: **state version
  vs oplog version are different things** once you `checkout()` history (detached mode).
- **Steal verdict:** v2's memory already versions facts; Loro's rule — *sync cursors are
  frontiers (exact boundary events), not timestamps* — is the correct cursor type for
  `session_store` sync.

### 1.4 matrix-org/matrix-spec — Apache-2.0 — State Resolution v2 (federation's hardest problem)
- **Problem shape** [CODE — `content/rooms/fragments/v2-state-res.md`]: in a federated
  room there is no single log; each server has a partial event DAG, and "current state"
  must be *derived identically by everyone* from conflicting state snapshots.
- **Algorithm** [CODE — same fragment]: split state into unconflicted map vs conflicted
  set; take the **auth chains** of all conflicted events; sort conflicted *power events*
  first by **reverse topological power ordering** (depth in the auth DAG weighted by
  sender power level), run iterative auth checks (drop events their sender wasn't
  authorized to send *at that point in history*), then resolve the rest against the
  resulting mainline order.
- **Lesson for JARVIS:** when devices disagree about *authorization-shaped* state
  (which device may approve what, trust ladder positions), content-CRDT rules are the
  wrong tool — you need an auth-aware resolution pass. v2's phone R0/R1/R2 tiers are
  exactly this kind of state; they must sync as *signed, ordered claims*, never as
  last-writer-wins facts.
- **Steal verdict:** pattern only (spec is a document, not code to lift).

### 1.5 bluesky-social/atproto — MIT (code) — the anti-CRDT: one writer, signed chain
- **Model** [CODE — `packages/repo/src/`]: each user's repo is a **Merkle Search Tree**
  (`mst/mst.ts`, `mst/diff.ts`, `mst/walker.ts`) of records keyed by path; every mutation
  creates a new signed **commit** pointing at the previous commit and the new MST root.
- **Sync** [CODE — `packages/repo/src/sync/provider.ts`, `consumer.ts`, `car.ts`]:
  a consumer asks for the commits since a known revision, receives a **CAR file** (a
  slice of content-addressed blocks), verifies the signature chain back to a commit it
  already trusts, then applies the MST diff. Federation (relays/firehose) works because
  *anyone can verify without trusting the transport*.
- **Conflicts:** impossible by construction — exactly one writer (the owner's key) per
  repo. Federation ≠ multi-writer.
- **Steal verdict for JARVIS:** this is the right shape for the **phone-as-second-device**
  case *if* JARVIS enforces one-writer-per-stream: PC is the writer for PC-originated
  event streams, phone for phone-originated ones; each stream is a hash-chained,
  ULID-ordered log (v2 already has ULIDs + causal parents in `session_store`), and sync
  is "verify chain, append blocks". No CRDT needed where write ownership is partitioned.

### 1.6 amark/gun — MIT — HAM: convergence with amnesia
- **Model** [CODE — `gun.js`, `src/`]: graph database; every node property carries a
  *state* number (a timestamp-like logical value). **HAM (Hypothetical Amnesia Machine)**
  decides every incoming write locally: if `incoming_state > current_state` accept;
  if `<` reject; if equal, compare values lexicographically — a deterministic rule any
  peer can apply with *no history at all*, which is why Gun tolerates peers that forget
  everything ("amnesia") and still converge.
- **Cost:** no causality tracking → no true concurrency detection; it's LWW with a
  tiebreak, wearing CRDT clothes. The codebase itself flags unfinished HAM integration
  (`src/root.js`: "TODO: BUG! This needs to call HAM instead").
- **Steal verdict:** the equal-state lexical tiebreak is a fine *last-resort* rule for
  scalar settings sync; nothing more.

### 1.7 orbitdb/orbitdb — MIT — oplog + Lamport clock + ACL-on-append
- **Model** [CODE — `src/oplog/clock.js`, `src/sync.js`, `src/access-controllers/`]:
  each database is an append-only log; entries are content-hashed and linked
  (a DAG), ordered by a **Lamport clock**; the materialized view is a deterministic
  fold over the log. Writes are gated by an access controller (identity-based ACL)
  checked at append time; replication exchanges log heads and pulls missing entries.
- **Steal verdict:** closest open-source cousin of v2's session_store design
  (event log + deterministic fold). Its lesson: *the log is the product; every view
  (memory, settings, history) is a fold* — sync the log and the views follow.

### 1.8 p2panda/p2panda — Apache-2.0/MIT (LICENSES/ dir) — operations, not state [STRUCT]
- Operation = signed, hash-linked log entry per author per stream; materialization is
  a separate deterministic step ("logs are transport, views are local"). Same
  partitioned-writer insight as ATProto, generalized to many authors.
- **Steal verdict:** reinforces the §1.5 pattern. No code read beyond structure.

---

## 2. Pragmatic sync — message logs, checkpoints, watermarks (the 90% solution)

### 2.1 actualbudget/actual — MIT — **HULC + Merkle trie over a message log** ★
- **Model** [CODE — `packages/crdt/src/crdt/timestamp.ts`]: Actual is **not** a value
  CRDT. Every mutation is a *message* stamped with a **Hybrid Unique Logical Clock**
  timestamp: `2015-04-24T22:23:42.123Z-1000-0123456789ABCDEF` — wall time + counter +
  node id, serialized as a 46-char *collatable string* (lexicographic sort = causal
  sort). `send()` stamps local messages; `recv(remote_ts)` advances the local clock so
  causality survives clock skew, stutter and regression (bounded by max-drift config).
- **Diffing** [CODE — `packages/crdt/src/crdt/merkle.ts`]: all message timestamps are
  inserted into a **trinary radix Merkle trie** keyed by time-in-minutes; each node
  holds a hash of its subtree. Two devices compare trie roots and walk down only the
  branches whose hashes differ → they find the *exact minute-window where their logs
  diverge* in O(divergence) hashes, then exchange only messages after it.
- **Sync state choice**: sync **only the message log**; the SQL database on each device
  is a materialization. The sync server stores the log **end-to-end encrypted**
  (password-derived; server can't read budgets) [README/docs in repo].
- **Steal verdict: ★ THE #1 STEAL.** v2's `session_store` is already an append-only
  event log with ULIDs and causal parents. Adding (a) an HLC stamp per event and
  (b) a persisted Merkle trie over event stamps gives PC↔phone sync with logarithmic
  divergence-finding, in pure stdlib (`hashlib`), no CRDT library, no server trust.

### 2.2 pouchdb/pouchdb — Apache-2.0 — CouchDB replication: rev trees + bilateral checkpoints
- **Model** [CODE — `packages/node_modules/pouchdb-replication/src/replicate.js`,
  `pouchdb-checkpointer`]: each document carries a **revision tree** (generation +
  content hash per revision). Concurrent edits = multiple leaf revisions (a *conflict
  the data model keeps*, not an error); the "winning" leaf for reads is deterministic:
  longest tree, then highest hash. Winners are a view; no data is destroyed until the
  app resolves.
- **Checkpoints** [CODE — replicate.js]: a checkpoint doc (`_local/<replication-id>`,
  where the id hashes source id + target id + filter) is written to **both** sides with
  `last_seq`; on resume both checkpoints are *compared* — if they disagree, replication
  restarts from the lower common point instead of trusting either side. Changes feed =
  the database's own sequence number, so resume is exact.
- **Steal verdict:** checkpoint discipline for v2: per-peer sync cursors stored as
  first-class rows on **both** devices, compared before trusted, with the
  compare-fail → resync-from-common-ancestor path built in from day one. And the
  rev-tree lesson maps 1:1 onto memory.py's existing supersede semantics — *conflicts
  are data, presented deterministically, resolved explicitly.*

### 2.3 Nozbe/WatermelonDB — MIT — two-phase pull/push, per-column resolution
- **Model** [CODE — `docs-website/docs/docs/Implementation/SyncImpl.md`]: server is
  source of truth; client holds a full replica. Local rows track `_status`
  (created/updated/deleted/synced) + `_changed` (columns touched since last sync).
  Sync = **pull** (server sends everything newer than client's `lastPulledAt`
  watermark) then **push** (client sends its tracked changes).
- **Conflict rule** [CODE — same doc]: *content-based, not time-based*: server version
  wins **except for columns the client changed since last sync** (per-column
  client-wins), resolved on the client during pull.
- **Steal verdict:** the pragmatic floor. If JARVIS ever syncs a plain table
  (reminders!), this — watermark + changed-columns — is the entire protocol, and it's
  honest about being master/replica rather than pretending to be P2P.

### 2.4 pubkey/rxdb + aspen-cloud/triplit + electric-sql/electric — the modern sync engines [STRUCT/README]
- **RxDB** [STRUCT — LICENSE.txt present]: replication as *plugins* over a common
  checkpointed protocol (CouchDB, GraphQL, custom HTTP): pull stream + push batch,
  per-collection checkpoints, conflict = custom handler or default LWW on the doc's
  `_meta.lww` — same skeleton as §2.2/2.3, industrialized.
- **Triplit** [README]: server+client "full-stack database": triple store, incremental
  query sync (you sync *query results*, not tables), **property-level conflict
  resolution**. Lesson: sync scope can be *a query*, not a dataset — for JARVIS,
  "phone sees today's reminders + open loops" is a query-shaped sync scope.
- **Electric** [README + LICENSE, Apache-2.0]: Postgres logical replication →
  **Shapes** (a table + WHERE clause) streamed to clients as a log of changes with
  shape-scoped cursors; clients keep local copies and read locally. Same lesson as
  Triplit from the server side: *the unit of sync is a declared subset with its own
  cursor*, and the subset declaration is a security boundary (a device only ever
  receives its shape).
- **Steal verdict (all three):** declare **sync shapes** for JARVIS: `memory-facts`,
  `reminders`, `golden-pairs`, `settings-nonsecret` — each with its own cursor,
  direction and DCL ceiling (see §6). Electric/Triplit prove the shape abstraction is
  how sync stays comprehensible at scale.

### 2.5 benbjohnson/litestream — Apache-2.0 — and rqlite/rqlite — MIT — the SQLite-native answers
- **Litestream** [README]: replicates SQLite by **streaming the WAL** to object storage
  (LTX files: page-level snapshots + increments). It is *backup/replication for one
  writer*, not multi-device sync: restore = replay. For JARVIS this is the correct
  answer to a different question — **PC failure recovery**: WAL-stream `sessions.db`
  to a local/encrypted target and the phone (or a new PC) can rebuild the exact store.
- **rqlite** [STRUCT — `db/` tree]: distributed SQLite via **Raft consensus** —
  one leader, followers replicate the Raft log; strong consistency, needs a quorum.
  Wrong tool for a home PC + phone (no quorum when the PC sleeps), included because
  every "just replicate the SQLite" proposal eventually reinvents one of these two;
  the scan's verdict: **Litestream's model fits JARVIS's topology; Raft does not.**
- **Steal verdict:** adopt Litestream thinking as the *disaster-recovery* layer under
  the event-log sync, not instead of it.

---

## 3. File & device sync — the transport generation

### 3.1 syncthing/syncthing — MPL-2.0 — version vectors + the untrusted-device envelope ★
- **Metadata sync** [CODE — `lib/protocol/bep_fileinfo.go`, `lib/protocol/vector.go`]:
  every file carries a **version vector** (`Vector`: per-device counters with
  `Update/Merge/Equal/LesserEqual`). Devices exchange *index* messages (metadata only)
  continuously; blocks are pulled on demand from whoever has them.
- **Conflicts** [CODE — `lib/model/folder_sendrecv.go`]: if two version vectors are
  **incomparable** (both sides advanced), neither wins: the loser is renamed
  `name.sync-conflict-<date>-<device>.<ext>` and kept. Comparable → newer silently
  replaces. *No silent data destruction, ever* — the same ethic as PouchDB's rev trees,
  expressed in filenames.
- **Untrusted devices** [CODE — `lib/protocol/encryption.go`]: a device can hold a
  folder it **cannot read**. Design, read in code: folder password → **scrypt** →
  folder key; per-file keys derived by **HKDF**; file data encrypted with
  **XChaCha20-Poly1305** (24-byte nonces, 16-byte tags); **file names** encrypted with
  **AES-SIV** (deterministic — the untrusted side can still deduplicate and index
  without learning names); blocks padded to a 1 KiB minimum to blunt size analysis;
  encrypted trees live under `.syncthing-enc` dirs.
- **Trust bootstrap**: device identity = a keypair; the device ID is a hash of the
  certificate — *the address is the public key*, no accounts, no directory server
  required for trust (discovery is a separate, untrusted service).
- **Steal verdict: ★ THE ENVELOPE REFERENCE.** If JARVIS sync ever transits a relay
  (Telegram servers, a VPS, cloud storage), the relay must be modeled as a Syncthing
  *untrusted device*: it stores ciphertext + deterministic-encrypted names, holds no
  keys, and its compromise leaks metadata sizes only (see §5 for the full v2 envelope).

### 3.2 bcpierce00/unison — GPL-3.0 (ideas only) — three-way roots, the oldest correct answer
- **Model** [README + docs in clone]: Unison stores, per replica pair, the **last
  synchronized root** (a fingerprint tree of the filesystem as it was after the last
  successful sync). Update detection = compare each replica's current root against
  the common ancestor root: changed-on-one-side → propagate; changed-on-both →
  *conflict, shown to a human*. Twenty-five years of production use of the
  ancestor-diff idea that §2.1's Merkle trie automates.
- **Steal verdict:** the ancestor principle — *never diff two states directly; diff
  each against the last state both agreed on.* v2's sync cursors should store the
  agreed frontier (Loro's word, §1.3), and both sides diff against it.

### 3.3 haiwen/seafile — GPLv2 (client; ideas only) — libraries, blocks, history-based conflicts [README]
- Files grouped into **libraries**, each independently syncable and independently
  password-encryptable; content is split into blocks so sync transfers **deltas only**,
  resumably; conflicts decided "based on history instead of timestamp" [README].
- **Steal verdict:** per-collection encryption keys + per-collection sync toggles —
  the library is the unit of trust, exactly like §2.4's shapes.

### 3.4 schollz/croc — MIT — and magic-wormhole/magic-wormhole — MIT — PAKE pairing ★
- **croc** [CODE — `src/croc/croc.go`]: transfer begins with **PAKE** (schollz/pake)
  over a relay: a short human code (e.g. `code phrase`) authenticates the channel;
  payload then flows encrypted, relay-assisted or P2P. The relay learns nothing and
  *cannot MITM without detection because the code is the authentication*.
- **magic-wormhole** [CODE — `src/wormhole/_key.py`]: **SPAKE2** with the code split
  into a *nameplate* (rendezvous slot) + password; the SPAKE2 master key is then
  expanded with **purpose strings** (`HKDF expand(purpose)`) so transit keys, verify
  keys etc. are cryptographically separated from one key exchange.
- **Steal verdict: ★ THE PAIRING REFERENCE.** v2's phone pairing today is a 6-digit
  code + PIN over Telegram. For any future native pairing, PAKE is strictly better:
  the human code *is* the key exchange — offline-verifiable, relay-blind, and immune
  to the "server saw the code" problem. The purpose-string key separation maps
  directly onto v2's DCL: derive `sync-key`, `approval-key`, `backup-key` from one
  pairing, never reuse one key for two jobs.

### 3.5 n0-computer/iroh — Apache-2.0/MIT — content-addressed transport [STRUCT]
- Workspace split [STRUCT — repo root]: `iroh` (QUIC connections keyed by node public
  keys, NAT traversal + relays), `iroh-base`, `iroh-dns(-server)` (pkarr-based
  discovery), `iroh-relay`. Blobs/gossip/docs live in sibling repos in current
  versions. The transferable idea: **node identity = public key; connections are
  end-to-end encrypted by default; relay is a dumb fallback path**, same trust shape
  as Syncthing, one layer lower.
- **Steal verdict:** architecture confirmation, no code (Rust).

### 3.6 vrtmrz/obsidian-livesync — MIT — CouchDB as the personal sync hub [README/CODE-light]
- An Obsidian plugin that syncs a vault through **self-hosted CouchDB or object
  storage** (S3/R2/MinIO), with **optional end-to-end encryption** of the chunks the
  server stores [README]. It is §2.2's replication protocol wearing end-user clothes,
  and it proves a *single user will self-host a sync hub if the payoff is their own
  notes on every device*.
- **Steal verdict:** the deployment shape for JARVIS's hub option: owner's own
  CouchDB-shaped dumb store (or object bucket) + client-side envelope — no JARVIS
  cloud needs to exist.

---

## 4. The E2EE applications — envelope design in production

### 4.1 laurent22/joplin — AGPL-3.0 (ideas only) — master keys over dumb file storage
- **What syncs** [CODE — `packages/lib/services/e2ee/`, `services/synchronizer/`]:
  every item (note, resource, tag) is serialized and encrypted **before** it touches
  the sync target; the target can be Dropbox/OneDrive/WebDAV/local files — all dumb.
  Ciphertext carries a self-describing header (`JED01` + metadata length + key id)
  [CODE — `EncryptionService.ts` header validation], so mixed-key corpora decrypt
  without trial-and-error and key rotation doesn't re-encrypt the world.
- **Key design** [CODE — same dir + `ppk/`]: a random **master key** encrypts items;
  the master key itself is encrypted with a password-derived key. **Multiple master
  keys** can coexist (rotation, per-shared-notebook). Sharing uses **PPK**: an RSA
  keypair per user; the master key is wrapped to the recipient's public key.
- **Deliberately not synced in plaintext:** everything. The server learns item sizes,
  counts and timing only.
- **Steal verdict:** the *key-id-in-header* trick + multi-master-key coexistence —
  v2's envelope should version every ciphertext with `(envelope_v, key_id)` from the
  first byte, so the 2027 key rotation is a non-event.

### 4.2 standardnotes/app — AGPL-3.0 (ideas only) [STRUCT] — versioned crypto protocols
- Monorepo contains a dedicated `packages/encryption` package; Standard Notes'
  distinguishing discipline is **protocol versioning of the encryption scheme itself**
  (successive protocol versions coexist; items declare theirs). Same lesson as
  Joplin's header, taken further: *the crypto format is a versioned protocol, not a
  flag day.*
- **Steal verdict:** version the envelope (`jarvis-sync-envelope/v1`), plan v2 of it
  before v1 ships.

### 4.3 cryptomator/cryptomator — GPL-3.0 (ideas only) [STRUCT] — the vault pattern
- [STRUCT — `src/main/java/org/cryptomator/common/vaults/`, `common/recovery/MasterkeyService.java`]:
  a vault = a directory of ciphertext + one **masterkey file** (vault key wrapped by
  a scrypt-derived key from the vault password). Filenames and contents use different
  constructions (deterministic SIV-mode for names, chunked AEAD for contents) — the
  same split as Syncthing's untrusted mode, arrived at independently. Includes a
  *recovery key* flow (the wrapped vault key can be re-wrapped under a printed
  recovery key) — the "owner loses password" story is designed, not improvised.
- **Steal verdict:** the recovery-key ceremony for JARVIS's sync envelope: losing the
  PC must not mean losing the memory; losing the password must have exactly one
  designed recovery path, printed and offline.

### 4.4 restic/restic — BSD-2-Clause — and kopia/kopia — Apache-2.0 — backup-grade envelopes
- **restic** [CODE — `doc/design.rst`, `internal/crypto/`]: password → **scrypt
  (N=65536, r=8, p=1)** → 64 derived bytes (32 B AES-256 key + 32 B Poly1305-AES MAC
  key) that **unwrap a random master key stored in a key file**; a repository can hold
  *several key files* (several passwords, one master key). Data is content-addressed
  and encrypted AES-256-CTR + Poly1305 MAC. This is the canonical **KEK → master key →
  data** hierarchy in its simplest auditable form.
- **kopia** [STRUCT — `repo/content/`]: same hierarchy at the content layer —
  content-addressed encrypted blobs + a **committed content index** (the index itself
  is encrypted content), so even the catalog of what exists is protected.
- **Steal verdict:** restic's key-file pattern is the cheapest correct answer for
  JARVIS-at-rest too: `data/` already holds SQLite files; a sync envelope that wraps
  one random master key per *device-pair*, re-wrappable per password, is ~a page of
  design because restic proved the shape. (Cipher caveat in §6.)

### 4.5 Tahoe-LAFS/tahoe-lafs — GPL-2.0+/TSPL (ideas only) — capabilities: keys *are* addresses
- **Model** [README/docs — `docs/architecture.rst`]: the store's keys are
  **capabilities** — cryptographic strings that *grant* the access they name.
  From a write-cap you can one-way-derive the read-cap, and from that the verify-cap;
  nobody can go the other way. Files are encrypted then **erasure-coded** across
  untrusted storage servers; servers hold shares, never keys.
- **Steal verdict:** capability derivation is the cleanest model for *sharing one
  thing* (export this memory pack to my phone) without sharing the master key: derive
  a read-only capability per export. Overkill for v2's first sync; exactly right for
  its sharing story later.

### 4.6 FiloSottile/age — BSD-3-Clause — the envelope, miniaturized [README]
- age encrypts a random **file key** once, then wraps it per **recipient stanza**
  (X25519 key, or scrypt passphrase). One payload, many envelopes. This is the design
  atom underneath Joplin/restic/Cryptomator, isolated: *encrypt data under a random
  key; wrap that key per recipient/purpose; version the format in the header.*
- **Steal verdict:** if JARVIS ever exports an encrypted backup for the phone, the
  age file shape (recipient stanzas + versioned header) is the format to mirror.

### 4.7 nextcloud/end_to_end_encryption — AGPL (ideas only) [STRUCT] · anyproto/anytype-heart — **Any Source Available License (not OSS)** [CODE — LICENSE.md] · AppFlowy — AGPL-3.0 [CODE — LICENSE] · ente/notesnook — triage only
- Nextcloud E2EE: per-folder keys wrapped per-user, encrypted metadata files — the
  "server is an untrusted folder store" pattern at app scale [STRUCT].
- Anytype: local-first "spaces" with device sync; **license is source-available, not
  open source** — concepts only, and a standing warning: *check the LICENSE file, not
  the marketing page* (AFFiNE shows the same trap in milder form: split licensing —
  backend/native under a separate LICENSE [CODE — `LICENSE` in clone]).
- Ente/Notesnook: cloned metadata-only in this pass; both are E2EE-sync products whose
  public designs follow the §4 hierarchy (user key → collection keys → file keys);
  **not code-verified here — flagged, not claimed.**

---

## 5. Cross-cutting: what they sync — and what they *refuse* to

| System | Syncs | Deliberately does NOT sync / never in plaintext |
|---|---|---|
| Automerge/Yjs/Loro | The op log / document updates | Nothing by design — encryption is *your* layer (a real gap) |
| Actual | The HLC message log (E2EE at rest on server) | Plaintext anything; the DB itself (it's a local fold) |
| PouchDB/CouchDB | Documents incl. conflict leaves + `_local` checkpoints | `_local` docs themselves (checkpoints never replicate — sync state is per-pair) |
| Syncthing | File blocks + metadata index | Plaintext to untrusted devices; the folder password |
| Joplin | Encrypted items + encrypted master-key entities | Plaintext items; the password that unwraps master keys |
| Watermelon/RxDB | Rows/tables in a declared scope | Anything outside the sync scope; conflict losers' columns |
| Electric/Triplit | A declared **shape/query** subset | Everything outside the shape — scope *is* the security model |
| ATProto | Signed commits + MST blocks (public by design!) | Private data — the model simply has no private tier (federation ≠ privacy) |
| Tahoe | Encrypted erasure-coded shares | Keys/capabilities never leave the client |

Three laws fall out of the table:
1. **Sync state is per-pair and never itself synced** (PouchDB's `_local` rule).
2. **The scope declaration is the security boundary** (shapes, libraries, folders) —
   "sync everything" is how systems leak.
3. **Plaintext is a per-item decision made before transport**, not a transport
   property (Joplin/Syncthing encrypt even on "trusted" paths, so trust can be
   revoked by reclassifying a peer, not by re-architecting).

---

## 6. Verdict for JARVIS v2 — the sync blueprint

**Topology.** PC (primary, RTX 2060) + phone (Telegram today). No quorum exists, no
always-on third party is trusted → Raft/consensus designs are out (§2.5); public
federation designs are out (§1.5's privacy row). What remains is the strongest
combination this scan found:

1. **Substrate — sync the log, fold the views** (OrbitDB §1.7, Actual §2.1).
   `session_store` events are the sync payload. Memory facts, reminders, golden pairs
   are folds/materializations that already exist locally; they converge because the
   log converges.
2. **Ordering — HLC stamps + frontier cursors** (Actual §2.1, Loro §1.3). Stamp every
   event with a hybrid logical clock (`<iso>-<counter>-<device_id>`, collatable);
   per-peer cursors store the agreed **frontier ULIDs**, and checkpoints live on both
   devices and are compared before trusted (PouchDB §2.2).
3. **Delta-finding — Merkle trie over event stamps** (Actual §2.1), with Automerge's
   Bloom "have" (§1.1) as the fallback summary when the trie itself is too big to
   exchange. Divergence cost: logarithmic, stdlib-only (`hashlib`).
4. **Write partitioning** (ATProto §1.5, p2panda §1.8): each device writes only its own
   event stream (PC stream, phone stream); streams are append-only and hash-chained
   via existing causal-parent ULIDs → cross-device conflicts are *structurally
   impossible* for events. The only shared-mutable state — semantic memory facts —
   resolves with memory.py's existing supersede + provenance rules, ties broken
   deterministically (HLC, then device id) — Gun's tiebreak (§1.6) as last resort.
5. **Authorization state is not a fact** (Matrix §1.4): phone tier grants, pairing
   state and PIN-adjacent material sync as *signed PC-issued claims* or not at all;
   a phone can never raise its own tier by syncing a edited fact.
6. **Scope = shapes with DCL ceilings** (Electric §2.4, §5 law 2):
   `events-personal` (sync, enveloped), `memory-facts` (sync, enveloped),
   `reminders` (sync, enveloped), `settings-nonsecret` (sync), `provider-stats /
   watcher-state / parked-providers` (device-local, never sync — PouchDB's `_local`
   rule), **`secrets`, API keys, approval tokens, PIN material, DCL-SECRET anything:
   never sync, never even enveloped** — they are not in any shape, so no bug in the
   sync engine can leak them.
7. **Envelope — restic hierarchy + Syncthing untrusted-relay treatment** (§4.4, §3.1):
   owner passphrase → scrypt (stdlib `hashlib.scrypt`) → KEK; KEK wraps a random
   sync master key (re-wrappable per device/password, restic key-file pattern);
   per-shape keys via HKDF; every ciphertext prefixed `(v=1, key_id, nonce)`
   (Joplin §4.1). Any relay — Telegram, a bucket, a future VPS — is an *untrusted
   device*: it stores ciphertext and can be fully compromised without exposing
   content. **Honest cipher caveat:** Python stdlib has scrypt/HKDF-parts/SHA-256 but
   **no AEAD** (no AES-GCM/ChaCha20-Poly1305). Options, in order: (a) accept the
   `cryptography` package as v2's single crypto dependency for sync only;
   (b) pure-Python ChaCha20-Poly1305 (~150 lines, test-vector-verified) behind the
   same envelope interface. The envelope *design* is settled by this scan either way;
   the cipher is a build-time decision for the owner, flagged not fudged.
8. **Pairing — PAKE when a native channel exists** (§3.4): SPAKE2 with purpose-string
   key separation (`sync`, `approval`, `backup` keys from one human code). Until
   then, the existing Telegram pairing stands — it authenticates the *channel*, and
   the envelope (7) means channel compromise still doesn't expose content.
9. **Recovery** (Litestream §2.5, Cryptomator §4.3): the enveloped event log *is* the
   backup; add a printed recovery-key ceremony before sync v1 ships, not after the
   first lost PC.
10. **If live co-editing ever arrives** (PC + phone editing one note): adopt **pycrdt**
    (§1.2) as a scoped exception to stdlib-only; do not hand-roll a text CRDT —
    YATA/Fugue conflict math is the part of this scan nobody should re-derive.

**What JARVIS should NOT copy:** ATProto's public-by-default posture; Gun's
amnesia-tolerant LWW for anything but scalar settings; Raft (rqlite) for a two-device
home topology; any design where sync scope = "the database" (the field's one
unanimous mistake).

---

## 7. Repo index (43 attempted · 41 cloned · licenses as read)

**CRDT/federation cores:** automerge (MIT, deep) · y-crdt/Yrs (MIT, deep) · Yjs (MIT,
deep) · loro (MIT, deep) · pycrdt (MIT, light) · matrix-spec (Apache-2.0, deep) ·
atproto (MIT, deep) · gun (MIT, deep) · orbitdb (MIT, deep) · p2panda (Apache/MIT,
structural) · dxos (**FSL-1.1 — not OSI**, structural) · earthstar (LGPL-3.0,
structural)
**Message-log/pragmatic:** actual (MIT, deep) · pouchdb (Apache-2.0, deep) ·
WatermelonDB (MIT, deep) · electric (Apache-2.0, light) · rxdb (LICENSE.txt,
structural) · triplit (structural, README) · litestream (Apache-2.0, light) ·
rqlite (MIT, structural)
**File/device transport:** syncthing (MPL-2.0, deep) · unison (GPL-3.0, deep) ·
seafile (GPLv2, light) · croc (MIT, deep) · magic-wormhole (MIT, deep) · iroh
(Apache/MIT, structural) · obsidian-livesync (MIT, light) · SparkleShare (partial
clone — gap)
**E2EE apps & envelopes:** joplin (AGPL-3.0, deep) · standardnotes/app (AGPL-3.0,
structural) · cryptomator (GPL-3.0, structural) · restic (BSD-2, deep) · kopia
(Apache-2.0, structural) · tahoe-lafs (GPL/TSPL, light) · age (BSD-3, light) ·
nextcloud/end_to_end_encryption (AGPL, structural) · anytype-heart (**source-available**,
structural) · AppFlowy (AGPL-3.0, structural) · AFFiNE (split license, structural) ·
ente (triage — not code-verified) · notesnook (triage — not code-verified) ·
Peergos (partial clone — gap)
**Failed clones (3 attempts, recorded not invented):** localsend/localsend_app ·
jazz-tools/jazz
