# MEGA-SCAN TEAM 21 — PERSONAL PRODUCTIVITY: EMAIL, CALENDAR, FILES & PERSONAL RAG

**Mission:** PhD-level reverse engineering of AI email assistants, calendar agents, personal RAG
over local files, document-QA systems, and note-taking AI — as the design brief for JARVIS v2's
(not-yet-built) email/calendar skills and its personal-RAG upgrade.

**Method:** `git clone --depth 1` (blobless `--filter=blob:none --sparse` for monorepos:
inbox-zero, private-gpt, Khoj, LEANN, h2oGPT, meetily) into `megascan/.work21/`, read locally.
GitHub API used only for discovery searches.

**Honest count:** **34 repos covered — 30 read at code level from local clones, 4 at
README/docs level (marked [DOCS]).** Target was 40. Shortfall cause: after ~35 successful
clones the network path began cutting pack downloads (`fetch-pack: unexpected disconnect`);
9 repos failed repeatedly and are EXCLUDED, not padded: Nexus-JPF/note-companion,
rush86999/atom, tinyhumansai/tinycortex, Lapis0x0/obsidian-yolo, infiolab/infio-copilot,
arcadeai-labs/SlackAgent, ErezShahaf/Lore, LoadShine/tada, eugeniughelbur/obsidian-second-brain.
License rule applied throughout: MIT/Apache/ISC = code may be borrowed with attribution;
GPL/AGPL/LGPL/no-license = **patterns and ideas only**.

**Star counts** are from the discovery searches (2026-10-20).

---

## PART 1 — THE FIVE DATA-ACCESS ARCHETYPES (the PhD synthesis)

Every productivity assistant in the scan gets its data one of five ways. This taxonomy is the
single most useful output of the scan — v2's email/calendar design is a choice among these.

| # | Archetype | Exemplars | Auth | Cost to build |
|---|-----------|-----------|------|---------------|
| A | **Provider cloud API** (Gmail API, MS Graph, JMAP) | inbox-zero, fastmail-mcp, zele (Google/MS modes) | OAuth2 / scoped API token | High per provider, best semantics (labels, push, history cursors) |
| B | **Protocol level** (IMAP/SMTP/CalDAV) | email-mcp, zele (IMAP mode), DispatchMail | App password / XOAUTH2 | One build, works with every provider incl. self-hosted |
| C | **Mail-client parasite** (drive the owner's existing client) | thunderbird-mcp, apple-mail-mcp, apple-notes-mcp | The client's own session — nothing new stored | Zero re-indexing; inherits client's folders, filters, search index |
| D | **CLI as tool surface** (agent calls a CLI, not an API) | googleworkspace/cli, zele | CLI holds OAuth; agent holds nothing | CLI does auth+cache; agent surface = composable commands, YAML/JSON out |
| E | **Agent-owned identity** (the agent HAS an inbox) | caspian-sdk | Agent's own address + token | Different problem: agents as correspondents, not owner-mail access |

Sync mechanisms observed: Gmail `historyId` cursors (zele `SyncState` table), IMAP IDLE
push watcher (email-mcp), Gmail watch/Pub/Sub-style push (inbox-zero class), and the
**local SQLite cache as the CLI's source of truth** (zele — Drizzle over `node:sqlite`,
`~/.zele/sqlite.db`; API payloads cached, sync cursors persisted).

## PART 2 — CHUNKING & RETRIEVAL: THE FIELD'S CONSENSUS

- **Chunk sizes converge on small:** LEANN's email app defaults to **256 chars / 25 overlap**;
  localGPT default **512 tokens**; ragbase recursive fallback **2048 chars / 128 overlap**;
  h2oGPT client tests use **512**. Personal corpora (mail, notes) want the small end.
- **Structure-aware beats blind windows:** private-gpt uses a *sentence-tree* parser over
  LlamaIndex `TokenTextSplitter` (sentences merged up to token budget, never mid-sentence);
  LEANN's code app uses AST-aware chunking with a 256/64 plain-text fallback.
- **Semantic-first, recursive-fallback:** ragbase tries LangChain `SemanticChunker`
  (embedding-breakpoint splits) and falls back to recursive splitting; shinpr/mcp-local-rag
  implements its own semantic chunker whose merge threshold is a *sigmoid of chunk size*
  (`semantic-chunker.ts:455`) — the most original chunker in the scan.
- **Retrieval is two-stage everywhere serious:** dense bi-encoder → **cross-encoder rerank**
  (Khoj: SentenceTransformer + CrossEncoder, with a bi-encoder confidence threshold that can
  short-circuit), or hybrid sparse+dense (localGPT default `search_type: hybrid` over LanceDB;
  reor's LanceDB-backed search). mcp-local-rag makes **rerank a separate pipeline module**
  (`parser/ chunker/ embedder/ vectordb/ rerank/` — each swappable).
- **The storage insight (LEANN, MLSys'26 best paper):** a vector index does not need to STORE
  embeddings. Store an HNSW-style graph + raw text; **recompute embeddings on demand during
  graph traversal** (high-degree-preserving pruning keeps it fast). Result: 60M chunks in
  **6 GB instead of 201 GB (~97% saving)** — "RAG on everything" (mail, files, browser history,
  chat exports) on a laptop. MIT licensed.

## PART 3 — HOW DRAFTS GET APPROVED BEFORE SEND (the approval spectrum)

No serious system in the scan lets an LLM free-send. Four gate shapes, weakest→strongest:

1. **Audit + rate-limit only** — email-mcp: sends execute, but every write op lands in an
   append-only JSONL audit log with **bodies, passwords and OTP codes redacted**, and a
   token-bucket limiter caps sends (default **10/min/account**). DispatchMail is the
   anti-pattern baseline: no gate, no audit, plaintext password, Gmail host hardcoded.
2. **Draft-mediated** — thunderbird-mcp (`saveDraft`, `replyToMessage` with `saveAsDraft: true`
   builds the native reply *with signature and threading headers*, saves, never sends;
   a timed-out save returns `saveOutcome: "uncertain"` — check Drafts before retrying),
   apple-mail-mcp (rich drafts via pasteboard HTML), inbox-zero's `DRAFT_EMAIL` rule action.
   **The AI's output is a draft; the human's client is the send button.**
3. **Rule-mediated** — inbox-zero: the user authors rules (including by *prompt→rule*
   compilation); the engine then executes deterministically on each new mail and logs
   `ExecutedRule`/`ExecutedAction` rows. `SEND_EMAIL` exists as an action type, but it only
   fires inside a user-authored rule. Learning closes the loop via `ReplyMemory`
   (patterns mined from the user's own sent mail) and a `ColdEmail` blocker list.
4. **Doctrine-mediated** — zele's repo `AGENTS.md` is a written constitution for any agent
   touching real accounts: ask before ANY mutation, never send to addresses the owner doesn't
   own, clean up test artifacts, report what changed. Zero code — pure operating rules,
   directly analogous to v2's JARVIS-RULES.txt.

**v2 mapping:** v2's gate already has the tiers for shape 2+3 combined: read = tier-1,
create-draft = tier-2, send = tier-2 bound to an HMAC approval token, bulk ops / rule
creation = tier-3. email-mcp's audit+rate-limit kit bolts on as shape 1 underneath.

## PART 4 — PRIVACY POSTURES

- **Secrets as references, never values:** email-mcp's config stores `keychain:<account>` —
  the password lives in the OS keychain (macOS/Linux offer during setup). zele stores
  OAuth/app-passwords in its local DB only. (v2's Secrets already has keyring → Windows
  Credential Manager → file backends: plug-compatible.)
- **Localhost + session token:** thunderbird-mcp's in-extension HTTP server binds localhost,
  uses session-scoped auth tokens, and the bridge discovers port+token via a connection file;
  the extension reuses Thunderbird's own encrypted store and Gloda index — **no mail ever
  leaves the machine and no second copy of the mailbox exists.**
- **Redaction at the log boundary:** email-mcp redacts `body`, `bodyText`, `password`,
  `code`, `link` before audit write — OTPs/magic links can never leak through logs.
- **Fully local stacks:** chatd (Ollama + local embeddings, Electron), ragbase ("completely
  local RAG"), LEANN (local embedding modes incl. Ollama/MLX), reor (local models + LanceDB),
  insights-lm (NotebookLM clone re-plumbed onto Ollama + local Whisper + Coqui TTS + Supabase/
  pgvector — orchestration by n8n flows, all inference local).
- **The cautionary shape:** Caspian (archetype E) normalizes agents holding their own
  mailboxes and messaging identities — powerful, and exactly what v2's rules forbid
  (no auto-created accounts; the agent acts as the owner, with approval, or not at all).

---

## PART 5 — PER-REPO FINDINGS

### A. EMAIL

**1. elie222/inbox-zero** — 12,694★ · TypeScript · **AGPL-3.0 → ideas only**
The flagship. *Access:* Gmail API / MS Graph (archetype A), push-triggered processing.
*Engine:* user-authored **Rule → Action** model (Prisma: `Rule`, `Action`, `ExecutedRule`,
`ExecutedAction`, `RuleHistory`) with actions incl. LABEL, ARCHIVE, DRAFT_EMAIL, SEND_EMAIL,
FORWARD, REPLY, CALL_WEBHOOK, digest scheduling (`Digest`/`DigestItem`, `ScheduledAction`).
A chat assistant (utils/ai/assistant/) exposes inbox/label/calendar/memory tools per provider.
*Learning:* `ReplyMemory` mines the owner's sent mail for reply patterns; `ColdEmail` table
powers the cold-email blocker. *Approval:* rule-mediated + draft-mediated (Part 3.3).
*Steal verdict:* **the rule-engine + executed-action audit design is the blueprint for v2's
email autonomy** — reimplement, never copy (AGPL).

**2. codefuturist/email-mcp** — 133★ · TypeScript · **LGPL-3.0 → patterns only**
52 MCP tools over raw **IMAP/SMTP** (archetype B): read/search/send/manage/schedule, calendar
extraction from mail, contacts, templates, bulk ops. *Uniques:* IMAP **IDLE watcher** with
AI triage; **verification-code catching** (OTP/magic-link detection with clipboard copy);
provider-aware label management. *Safety stack* (`src/safety/`): redacting audit logger,
token-bucket send limiter, input validation, attachment guards; passwords in OS keychain
with `keychain:<account>` config refs; OAuth2 for the server itself marked experimental.
*Steal verdict:* **the safety kit + IDLE-watcher + OTP-catch designs** — highest-value
borrow in the email group; reimplement in stdlib (imaplib has IDLE via polling fallback).

**3. remorses/zele** — 301★ · TypeScript (Bun/Node) · **ISC → code borrowable**
Email & Calendar CLI for humans *and* agents. *Access:* Google OAuth, Microsoft OAuth
(Thunderbird's public client ID + localhost callback), IMAP/SMTP app-passwords incl.
Proton Bridge (STARTTLS + custom CA), plus receive-only `@zele.sh` agent inboxes.
*Internals:* single SQLite source of truth; `SyncState` Gmail history cursors; YAML output
for agent parsing; headless login = background daemon + printed URL + poll `whoami`
(built for agent shells). Command surface: `mail`, `mail-actions`, `draft`, `calendar`,
`watch` (filtered wait-for-mail with timeout), `filter`, `label`, `inbox`.
*Steal verdict:* **steal the CLI-as-skill shape and the sync-cursor design**; its AGENTS.md
doctrine (Part 3.4) is a ready-made template for v2's live-account rules.

**4. TKasperczyk/thunderbird-mcp** — 388★ · JavaScript · **MIT → code borrowable**
Archetype C reference implementation. A Thunderbird **extension embeds an HTTP server**
(localhost, session-scoped token); a Node bridge (`mcp-bridge.cjs`) translates MCP stdio ↔
HTTP and answers initialize/ping before Thunderbird even loads. *Retrieval:* Thunderbird's
own **Gloda full-text index** — zero re-indexing; search is token-AND with field prefixes,
dedup by RFC Message-ID across folders/labels, cooperative 20s scan budget. *Calendar:*
full tool set over Thunderbird's calendars (CalDAV beneath). *Failure semantics:* sends
report success only after SMTP succeeds; a 120s timeout yields an explicit **"unknown
outcome — check Sent/Outbox before retrying"** instead of a false success.
*Steal verdict:* **steal the unknown-outcome discipline and the draft mechanics**; the
parasite pattern itself is the fallback if v2 ever ships a companion mail client strategy.

**5. patrickfreyer/apple-mail-mcp** — 231★ · Python · **MIT → code borrowable**
Archetype C for macOS: drives Apple Mail through **osascript/AppleScript** with production-
grade process hygiene (in-flight child tracking, timeout injection into scripts, orphan
reaping on signals — issue-#58-driven). Tools: inbox listing, unread counts, statistics/
dashboard, export, forwarding, `create_rich_email_draft` (HTML built then pushed through the
pasteboard into a native draft), reply verification (`_verify_saved_reply_body`).
*Steal verdict:* pattern only for v2 (Windows house) — but its **draft-verify-after-save**
step is worth copying into any draft flow.

**6. MadLlama25/fastmail-mcp** — 130★ · TypeScript · **MIT → code borrowable**
The protocol-purity exemplar: **JMAP** for mail + contacts (`ContactCard/set`), **CalDAV**
for calendar, WebDAV for files — one scoped Fastmail API token, scopes enforced per tool.
*Steal verdict:* **proof that one skill can speak mail+calendar+contacts+files over open
protocols** — v2's calendar skill should be CalDAV-first for exactly this reason.

**7. dbish/DispatchMail** — 187★ · JS/Python · **Apache-2.0**
Locally-run Gmail triage UI: async IMAP (`aioimaplib`, `BODY.PEEK[]` fetches), mailparser,
LLM Q&A over the inbox. No chunking (whole threads to the model), no approval flow,
password auth, Gmail host hardcoded. *Steal verdict:* **negative exemplar** — shows the
floor v2 must stay above; its only borrowable idea is `BODY.PEEK` (read without marking read).

**8. TryCaspian/caspian-sdk** — 973★ · Python · **AGPL-3.0 → ideas only**
Archetype E: an SDK giving *agents their own* email/WhatsApp/iMessage/Discord identities
(`channels.add("email", via="self-host", from_address=...)`), webhook-served bots per channel.
*Steal verdict:* **do not steal for v2** — agent-owned accounts contradict v2's standing
rules. Documented here because the owner will meet this pattern in the wild; knowing it is
a different product category prevents category errors in v2's design.

### B. CALENDAR & MEETINGS

**9. googleworkspace/cli** — 31,703★ · Rust · **Apache-2.0 → code borrowable**
Google's own Workspace CLI (Gmail, Calendar, Drive, Docs, Sheets, Chat) **generated from the
Discovery Service documents**, and it ships `.agent/skills/` — SKILL.md packs
(`gws-calendar`, `gws-calendar-agenda`, `gws-calendar-insert`, …) that *teach agents* to use
the CLI instead of hardcoding API logic; skills are themselves generated and published by CI.
*Steal verdict:* **the generated-CLI + skill-pack pattern is the cheapest credible route to
a v2 Google Calendar skill**: wrap one CLI, ship a skill, no hand-rolled OAuth client.

**10. tavily-ai/meeting-prep-agent** — 205★ · Python (LangGraph) · **MIT → code borrowable**
Reads upcoming Google Calendar events, researches attendees/companies (Tavily), emits a
briefing note. Tiny (28 files) and complete: calendar-read → enrich → summarize.
*Steal verdict:* **steal as the `calendar brief` tool design** — compose with v2's mail
threads + notes (Part 7) instead of web research alone.

**11. Zackriya-Solutions/meetily** — 31,962★ · Rust/Tauri · **MIT** [DOCS-level: root files +
README + privacy policy read; backend sparse checkout was cut by the network failures]
Privacy-first meeting notes: **local Parakeet/Whisper transcription (claimed 4× faster),
speaker diarization, no cloud path**, summaries via local or user-keyed models.
*Steal verdict:* **the meeting pipeline shape** (record → local STT → diarize → summarize →
file into notes) slots directly onto v2's existing STT work; treat its speed claims as
vendor claims [MC].

### C. PERSONAL RAG & DOCUMENT QA

**12. zylon-ai/private-gpt** — 57,597★ · Python · **Apache-2.0 → code borrowable**
The reference local-RAG server. *Parsing:* Docling (OCR via EasyOCR, accurate table mode,
image placeholders). *Chunking:* sentence-tree node parser over a non-stripping
`TokenTextSplitter` — chunks respect sentence boundaries up to a token budget.
*Store:* Qdrant default (pluggable); *retrieval:* LlamaIndex hybrid. *Platform:* Celery/arq
task queues for ingestion and chat, an `artifact_index`, skills/tools/MCP support in current
versions, API-first (UI is secondary). *Steal verdict:* **steal the sentence-tree chunker
design and the ingest-as-background-task shape**; too heavy to embed, right weight as the
"server mode" reference for v2's knowledge skill.

**13. PromtEngineer/localGPT** — 22,196★ · Python · **MIT → code borrowable**
The classic: chat with documents, nothing leaves the device. Current form: **LanceDB** tables
with dense + optional **late-chunking** retrievers, `search_type: hybrid` default, 512-token
default chunks, ingest config-driven; a separate eval harness (`eval/run_eval.py`) that
flips retrieval modes — rare and commendable: **retrieval quality is measured, not vibes.**
*Steal verdict:* steal the eval-harness idea for v2's knowledge skill (a fixed question set
re-run on every chunking change).

**14. StarTrail-org/LEANN** — 13,037★ · Python · **MIT → code borrowable**
Covered in Part 2: graph-based selective recomputation (embeddings recomputed during
traversal, never stored), high-degree-preserving pruning, CSR graph storage; per-corpus apps
(email 256/25 chunks, browser history, ChatGPT/Claude exports, code with AST chunking 256/64
fallback); embedding backends: sentence-transformers / OpenAI-compatible / MLX / **Ollama**.
*Steal verdict:* **#1 steal of this scan for the personal-RAG track** (Part 6). A stdlib-
feasible v2 variant: keep FTS5/BM25 as the sparse graph, store raw chunks in SQLite,
embed on demand with the already-present Ollama — index stays megabytes, not gigabytes.

**15. h2oai/h2ogpt** — 11,938★ · Python · **Apache-2.0 → code borrowable** [sparse read]
The maximalist: every loader, many vector DBs (Chroma default), vision/audio/doc pipelines,
512-token chunk default in tests, heavy config surface. *Steal verdict:* borrow loader
*coverage checklists* only; its sprawl is the anti-goal for v2's stdlib discipline.

**16. BruceMacD/chatd** — 1,079★ · JavaScript/Electron · **MIT → code borrowable**
Minimal local doc-chat done right: parse → clean → embed (`src/service/embedding.js`) →
vector store (`vector.js`), Ollama chat, everything on-device, ~50 files total.
*Steal verdict:* proof-of-minimum — v2's knowledge skill should stay nearer chatd's size
than private-gpt's.

**17. shinpr/mcp-local-rag** — 415★ · TypeScript · **MIT → code borrowable**
Local-first RAG **as an MCP server** with the cleanest pipeline decomposition in the scan:
`parser/ chunker/ embedder/ vectordb/ rerank/ ingest/ server/` as separate modules,
content-hash dedup before parsing (tested: ingest skips unchanged files by hash), semantic
chunker (Part 2), PDF-visual support. *Steal verdict:* **steal the module decomposition and
hash-skip ingest** for v2's knowledge skill rework — incremental re-indexing is the difference
between a toy and a daily driver.

**18. curiousily/ragbase** — 131★ · Python · **MIT → code borrowable**
"Completely local RAG" reference mini-app: SemanticChunker primary, RecursiveCharacterTextSplitter
(2048/128) fallback, Chroma, local LLM via Ollama-class backends, streaming chain.
*Steal verdict:* the **semantic-first/fallback-second splitter cascade** in miniature —
~30 lines of design, directly portable to v2's Python.

**19. theaiautomators/insights-lm-local-package** — 227★ · TypeScript/n8n · **MIT**
NotebookLM, re-plumbed for privacy: the hosted backend's workflows are rebuilt in **n8n**
over **Ollama** (LLM + embeddings), local **Whisper ASR**, Coqui TTS, Supabase (pgvector)
storage. Sources → chat → generated audio overviews, all inference local.
*Steal verdict:* steal the **"audio overview of my documents"** feature idea for v2's notes;
the n8n orchestration itself is out of scope (v2 declined n8n).

**20. khoj-ai/khoj** — 37,754★ · Python · **AGPL-3.0 → ideas only**
The fullest "second brain" server. *Content processors* per type: markdown, org-mode, PDF,
docx, images (vision captioning into the index), Notion, GitHub, plaintext. *Retrieval:*
pgvector-backed bi-encoder search with confidence threshold + **CrossEncoder rerank**.
*Beyond RAG:* custom **agents**, **automations** (scheduled jobs with cron semantics —
the closest thing in the scan to v2's proactivity+reminders), memories API, phone API,
clients for web/desktop/Emacs/Obsidian/Android. *Steal verdict:* **steal the processor-zoo
list and the automations model** (scheduled agent jobs as first-class objects); AGPL bars code.

### D. SECOND BRAIN & NOTES

**21. reorproject/reor** — 8,540★ · TypeScript/Electron · **AGPL-3.0 → ideas only**
Local PKM: notes in plain markdown, **LanceDB** vector index over note chunks, semantic
search + chat, automatic related-note linking in the sidebar (the "high-entropy people"
pitch = zero filing, retrieval does the organizing). Local models via Ollama-class backends.
*Steal verdict:* **related-notes-by-embedding** is the one feature v2's notes skill lacks;
idea only (AGPL).

**22. glowingjade/obsidian-smart-composer** — 2,333★ · TypeScript · **MIT → code borrowable**
Obsidian chat with **mention-based context**: the user @-mentions files/folders/URLs and the
plugin assembles context (with a semantic-similarity path for vault retrieval), multi-provider
LLM core (Anthropic incl. Claude-Code provider, Azure, DeepSeek, local), and an apply-view
that diffs AI edits into the note **for approval before writing** — the notes-world twin of
draft-mediated email. *Steal verdict:* **steal @-mention context assembly + diff-apply
approval** for v2's notes/code skills.

**23. eclaire-labs/eclaire** — 926★ · TypeScript · **MIT → code borrowable**
Local-first organizer across **tasks, notes, documents, photos, bookmarks** — one ingestion
and AI layer over all personal artifacts; llama.cpp recommended as the local inference
server; "private by default: all models local, all data local."
*Steal verdict:* steal the **unified artifact model** (one index over unlike types) as the
target shape for v2's memory+knowledge convergence; borrow the entity taxonomy.

**24. huytieu/COG-second-brain** — 1,304★ · Python/markdown · **MIT → code borrowable**
"Cognition + Obsidian + Git": a vault that is its own agent harness — PARA-style folders
(`00-inbox` → `05-knowledge`), **~35 SKILL.md skill packs** (daily-brief, daily-journal,
knowledge-consolidation, memory-hygiene, harvest, meeting-transcript…), surfaces for Claude
Code / Antigravity / Gemini CLI / Codex via per-agent skill dirs with `AGENTS.md` as the
universal fallback, and **git as the memory's version history** (self-evolution = commits).
*Steal verdict:* **steal the skill-pack catalogue and the "vault + git = auditable memory"**
pattern — v2's golden-pairs store is one step from this; COG shows the finished shape.

**25. s2b-dev/smart-second-brain** — 1,324★ · TypeScript · **MIT → code borrowable**
Obsidian plugin: hybrid search (vector + graph), an interactive knowledge graph over the
vault, chat over notes. *Steal verdict:* the **graph-from-links + vector** dual index —
cheap to mimic in v2: wikilinks/headings give the graph for free, FTS5 gives the text half.

**26. henrydaum/second-brain** — 671★ · Python · **MIT → code borrowable**
"Agentic framework as an OS over local files": file-intelligence layer + an agent runtime
with an attachments pipeline, Dockerized. *Steal verdict:* borrow its file-intelligence
inventory (what it watches/indexes) as a checklist for v2's file skill.

**27. software-mansion-labs/react-native-rag** — 348★ · TypeScript · **MIT → borrowable**
On-device mobile RAG: embeddings + vector search executed **on the phone** (no server),
SQLite-backed. *Steal verdict:* the existence proof for v2's phone-side recall — if the
Telegram client ever needs local context, this is the weight class to copy.

**28. sweetrb/apple-notes-mcp** — 160★ · TypeScript · **MIT → code borrowable**
Archetype C for notes: MCP over Apple Notes (read/search/create/edit/export) via the
client's own stores. *Steal verdict:* pattern reference for a future "notes parasite" —
v2's notes are its own files, so low priority; the tool-shape (CRUD + export) is the borrow.

**29. mhss1/MyBrain** — 2,221★ · Kotlin · **GPL → ideas only**
All-in-one Android productivity (tasks, notes, calendar, diary, bookmarks) with an `ai/`
module and Android **AppFunctions** exposure — the OS-level "apps declare actions to the
assistant" model. *Steal verdict:* idea only — AppFunctions is the Android twin of v2's
skill manifests; confirms the manifest-per-capability design travels across platforms.

**30. theexperiencecompany/gaia** — 313★ · Python [DOCS] "Your proactive personal AI
assistant for daily life" — LangGraph-class agent over Gmail/Google Calendar with
proactive briefings. *Steal verdict:* positioning reference for v2's morning digest;
internals unverified (clone failed) [MC].

**31. smixs/iva-agent** — 261★ · TypeScript [DOCS] Telegram-native life assistant:
"remembers everything and helps you run your life", self-hosted in one command.
*Steal verdict:* channel reference — v2's Telegram R0/R1 design is stricter (PIN + action
hash); IVA shows the market expects looser, so v2's confirmation UX must stay *fast*.

**32. blueberrycongee/Lumina-Note** — 918★ · TypeScript [DOCS] Markdown notes with live
preview, bidirectional links, embedded AI assistant. *Steal verdict:* none beyond
confirming the notes+links+AI table stakes.

**33. Zackriya-Solutions/meetily** — see #11 (calendar & meetings).

**34. kaymen99/personal-ai-assistant** — 183★ · Python · **no license → ideas only**
Multi-agent crew (manager + email agent + calendar agent + Notion agent + researcher) over
WhatsApp/Slack/Telegram channels, per-agent prompt files. *Steal verdict:* the
**one-agent-per-domain prompt split** is a clean way to keep v2's brain prompts small —
route to a domain prompt instead of one mega-prompt. (No license = no code.)

---

## PART 6 — TOP 5 MECHANISMS

1. **LEANN's recompute-don't-store vector index** (MIT) — graph + raw text, embeddings
   recomputed during traversal; ~97% smaller indexes make "index *everything* the owner
   has" feasible on a 6 GB-VRAM laptop. The deepest idea in the scan.
2. **inbox-zero's learned-rule engine** (AGPL, design only) — prompt→rule compilation,
   deterministic execution, `ExecutedRule` audit rows, `ReplyMemory` mined from sent mail.
   The only production-proven shape for "the assistant files and drafts by itself, safely."
3. **email-mcp's safety stack** (LGPL, patterns) — keychain secret references, redacted
   append-only audit, per-account send rate-limiter, IDLE watcher with triage and
   OTP-catching. A complete guardrail kit in ~4 small modules.
4. **The client-parasite pattern** (thunderbird-mcp MIT / apple-mail-mcp MIT) — inherit the
   mail client's index, folders, filters and session; localhost + session-token bridge;
   and its failure semantics: **unknown outcomes are reported as unknown**, never as success.
5. **Generated CLI + skill packs** (googleworkspace/cli, Apache) and **zele's agent-first
   CLI** (ISC) — one auth-holding tool surface, skills that teach the agent, SQLite sync
   cache with provider cursors. The fastest honest path from "no integration" to "working
   Gmail + Calendar" without hand-rolling OAuth per provider.

## PART 7 — DESIGN BRIEF: v2 EMAIL + CALENDAR SKILLS (the deliverable)

### Email skill (`skills/email/`, new)
- **Transport order:** (1) **IMAP/SMTP via stdlib** (`imaplib`, `smtplib`, `email`) —
  zero new dependencies, works with Gmail app-passwords, Outlook, Fastmail, self-hosted;
  XOAUTH2 as a later adapter. (2) Gmail API adapter later for labels/push/history cursors
  (zele pattern). JMAP adapter if a Fastmail-class account appears (fastmail-mcp pattern).
- **Tools & tiers:** `email_search`, `email_read`, `email_list` (tier-1, DCL-wrapped —
  mail bodies are untrusted input, evidence-wrap always); `email_draft_create`,
  `email_draft_send_later` (tier-2); `email_send` (**tier-2 + approval token bound to
  the exact message hash**, v2 gate already supports this); `email_move/archive/label`
  (tier-2); `email_rule_create`, bulk ops (tier-3).
- **Send discipline (from Part 3):** default compose path produces a **draft**; direct
  send requires the approval token; every send/move writes a redacted audit JSONL line
  (email-mcp redaction set: no bodies, no codes); token-bucket limiter 10 sends/min/account;
  timeouts surface as **"unknown — check Sent before retrying"** (thunderbird-mcp).
- **Watcher:** IMAP IDLE (poll fallback 60 s) → proactivity events: OTP/magic-link caught
  (held for the owner, never auto-used, never logged), priority-sender replies, and
  calendar invites — all through the existing call-ringing budget.
- **Secrets:** keyring references only (`email:<account>`), per email-mcp; passwords never
  in config files, never in chat.

### Calendar skill (`skills/calendar/`, new)
- **Transport order:** (1) **CalDAV** (stdlib `http.client` + `xml` — no external lib;
  iCloud/Fastmail/Nextcloud/self-hosted all speak it), (2) Google Calendar via the
  googleworkspace-CLI pattern (archetype D) if the owner connects Google, (3) `.ics`
  file import/export as the universal floor.
- **Tools & tiers:** `cal_list`, `cal_freebusy`, `cal_search` (tier-1);
  `cal_create`, `cal_update` (tier-2, undo snapshot like all v2 writes);
  `cal_delete`, `cal_invite_send` (tier-2 + approval — inviting people is an external send).
- **Sync:** zele-style SQLite cache + provider cursors (CalDAV sync-token / Google
  nextSyncToken), so `cal_list` is instant and offline-tolerant.
- **`cal_brief` tool** (meeting-prep-agent + meetily shape): next event → attendees →
  linked mail threads (email skill) → linked notes (knowledge skill) → local transcript
  notes — one spoken briefing, composed from v2's own stores only.

### Personal-RAG upgrade (`skills/knowledge/`, existing)
- Splitter cascade: structure-aware (sentence-tree, private-gpt) → semantic (ragbase) →
  recursive fallback; **chunk 256–512** for mail/notes, overlap ~10%.
- Retrieval: keep FTS5/BM25 (sparse) + add **on-demand embedding recall** (LEANN pattern):
  chunks stored raw in SQLite; embedding via the existing Ollama provider at query time
  over the BM25 shortlist only — bounded compute, tiny index, no new service.
- Ingest: content-hash skip (mcp-local-rag), per-type processors checklist (Khoj),
  and a fixed eval question set re-run on chunking changes (localGPT).

## PART 8 — CONFIDENCE & GAPS

- Code-level claims rest on the local clones listed in Part 5; [DOCS] entries rest on
  README/search evidence only and are marked. Meetily's internals are [MC] (README +
  privacy policy; backend read was cut). Gaia's internals are [MC/UK].
- The 9 excluded repos (Part "Honest count") remain unscanned — a re-run on a healthy
  network is the only gap; Nexus-JPF/note-companion (Obsidian file organizer) is the
  highest-value miss.
- Agent-owned-identity systems (Caspian) were documented to be *avoided by design*;
  if the owner's rules ever change, that verdict must be revisited explicitly.
