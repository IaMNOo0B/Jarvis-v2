# MEGA-SCAN TEAM 15 — Phone & Remote Control for Assistants

**Mission:** How do others build phone↔PC assistant control? JARVIS v2's baseline: Telegram, R0 read-only / R1 write-with-confirmation (action hash + 4-digit PIN, PBKDF2-hashed) / R2 never-remote, 6-digit single-use 5-minute pairing, voice notes local-STT-only. Verdict up front: **v2 is ahead of ~90% of this field.** Most repos ship "allowlist + raw shell" and stop there. The useful steals are concentrated in ~6 repos.

**Method:** 6 GitHub searches (~1,100 total hits), 90+30 repos triaged, then `git clone --depth 1` code reads (API hit 429 mid-mission; switched to clones per owner order). Depth honestly marked per repo.

---

## The field in one paragraph

The universal pattern is: **BotFather token + hardcoded allowlist of Telegram user IDs + polling loop + command handlers.** Everything else is rare. Tiered permissions exist in exactly **one** product-class repo (PDAgent's read/write/AI-action split) besides v2. Pairing ceremonies exist in **two** (openditto, phone-assistant). Typed confirmations exist in **two** (remotepc-pro's `/shutdown confirm`, AgentRQ's `allow_always`). Offline queuing is nearly absent — almost every bot silently drops commands while the PC is off; the only real answers are Telegram's own store-and-forward (webhook/polling backlog), Lucarne's `/latest` digest, and persistent schedulers (PDAgent). Voice notes are almost never transcribed by PC-control bots — they're either saved as files (tg-cli-control) or handled by chat-first bots. And the same code with a different README is a consumer remote **or a RAT** — intent is the only difference (see §F).

---

## A. Full PC remote-control bots (Telegram → Windows/PC)

### 1. techgniouss/pdagent — "Pocket Desk Agent" (15★, Python, MIT) — DEEP READ
The most product-complete Windows remote in the scan; the only one besides v2 with layered thinking.
- **HOW IT ACTUALLY WORKS (inside):** `handlers/_shared.py:safe_command` — a single decorator wraps EVERY handler (replaced 60+ per-handler checks): (1) fail-closed auth — an update with no identifiable sender (anon admin, channel post) never reaches a handler; unauthorized users get **silence** (debug log only, no reply — doesn't confirm the bot exists); (2) private-chat-only enforcement — outputs go to the originating chat, so group chats are rejected (config override exists); (3) per-user token-bucket rate limit per command; (4) exceptions caught and sanitized, never crash the process.
- **Sandbox:** `APPROVED_DIRECTORIES` enforced with `Path.relative_to()` (not string prefix — kills `../` tricks). **The AI gets NO shell at all** — all automation is typed UI interactions.
- **Confirmation:** `gemini_actions.py:_queue_confirmation` — AI-proposed destructive actions are parked in a dict keyed by random 10-hex `action_id` with user/chat binding, expiry purge, and its own rate limit on confirmation *requests*; the user taps Approve/Cancel inline buttons; the callback re-validates the stored action. Fixed (non-AI) destructive commands (shutdown, stop bot, reset dirs) use the same two-button pattern.
- **Offline/persistence:** scheduler tasks in `scheduled_tasks.json` via atomic writes + corrupt-file quarantine → **scheduled work survives restarts and PC-off periods**; on boot, tasks re-arm. Macros record/replay.
- **Weaknesses:** confirmation store is in-memory (a restart kills pending approvals — safe but lossy); no PIN/second factor — a stolen unlocked phone session is game over, same as most of the field; Gemini path optional but cloud-dependent.
- **Steal verdict:** HIGH — see Steals #2/#3. Ideas *and* code patterns (MIT).

### 2. Ahmed-Z/Telegram-Remote-Desktop (53★, Python, no LICENSE → ideas only) — FULL SOURCE READ
The archetype small remote; widely copied.
- **Flow:** `telegram-remote-desktop.py:TelegramBot` — PTB `Updater.start_polling()`, messages routed by exact-match text against emoji reply-keyboard buttons ("🔒 Lock screen", "📸 Take screenshot", …), slash-less free text grammar for power commands: `cmd <shell>`, `cd <dir>`, `download <file>`, `kill <proc>`, `url <link>`.
- **Auth:** two weak layers — `auth.json` holds the expected `CHAT_ID`, and `send_response` checks `update.message.chat["username"] != "YOUR_USERNAME"` (a placeholder string the user must edit in source!). **Username-based auth is spoofable-adjacent** (usernames are public and changeable; the correct key is the immutable numeric user/chat ID). One positive: intruders get a decoy reply ("Nothing to see here").
- **Mechanism worth noting:** screen-lock detection via `psutil` — if `LogonUI.exe` is running, the screen is locked. Cheap, no API needed.
- **Holes:** `cmd` runs `subprocess.Popen(usr_msg[1:], shell=True)` — full shell for whoever passes the username check; `download` exfiltrates arbitrary paths; token committed in `auth.json` pattern encourages secrets in repo; no confirmation for anything, no rate limit, no logging of intruder attempts beyond stdout.
- **Steal verdict:** the LogonUI lock-state trick (1 line) + reply-keyboard-as-menu pattern for low-literacy control. Nothing else — v2 is stricter everywhere.

### 3. lazuardyk/Remote-PC-Telegram (51★, Python, MIT license file present) — FULL SOURCE READ
Raw-HTTP long-polling bot with a tkinter setup GUI.
- **Flow:** `main.py:main()` hand-rolls `getUpdates` with a `last_update` watermark (only processes `update_id > last_update`), dispatches on prefix: `/youtube <query>` (scrapes YouTube results HTML with regex for the first `watch?v=` id), `/ytfull` → `keyboard.send('f')`, `/ytnext` → `shift+n`, `/close` → `alt+f4`, `/url`, `/status`, `/restart`, `/shutdown`.
- **Auth:** single check `update['message']['from']['username'] == owner`.
- **Positive pattern:** `/status` is a genuinely good read-only bundle — hostname, user, OS, CPU%, RAM%, battery% + charging state via `psutil.sensors_battery()` (structure = steal for a v2 `pc.status` reply).
- **Holes:** **the bot token is embedded in the request URL and passed as GET params** (URLs get logged by proxies); no `offset` parameter → the same updates are refetched and only the watermark dedups (fragile across restarts); YouTube scraping regex breaks whenever markup shifts; zero confirmations on shutdown/restart; replies leak full system info to anyone passing the username check.
- **Steal verdict:** `/status` bundle composition only.

### 4. baska-pro/remotepc-pro (3★, Python, custom PERSONAL-USE license → ideas only) — CODE READ
Owner-only Windows monitor + limited power control + web dashboard. The OTP implementation is the best in the scan.
- **Auth (inside):** dashboard login = Chat ID + OTP **delivered through Telegram itself** (out-of-band to the chat channel). `issue_otp()`: 6-digit `secrets.randbelow` code, stored only as a **hash** (`ohash`), 300s TTL, try-counter, issuance rate-limited (4 per 600s), and an anti-enumeration uniform response — *"Jika Chat ID terdaftar, OTP telah dikirim"* ("if the Chat ID is registered, an OTP has been sent") is returned either way. Sessions last 8h.
- **Confirmation pattern:** `/restart confirm` / `/shutdown confirm` — the literal word `confirm` must be appended; the dashboard asks a browser confirm. Type-to-confirm, zero UI machinery.
- **Steal verdict:** HIGH on the OTP issue/verify shape (hash-at-rest + TTL + tries + rate limit + uniform reply) if v2 ever adds a web surface; the `confirm`-suffix is a decent *fallback* grammar where inline buttons don't exist. v2's action-hash+PIN is stronger for in-Telegram use.

### 5. Demorein/RuFa-Shutdown-bot (8★, Python) — STRUCTURE READ (honest: main-source read failed twice, not forced)
Single-purpose shutdown bot with a GUI installer, `Core.py` monolith. Field-representative of the "one dangerous verb, no confirmation" class. No steal.

### 6. xbitoi/terminal-telegram-control (2★, JS) — TRIAGE
Notable design *constraint* as a feature: **exactly 3 fixed actions** (restart, shutdown, +1). The fixed-menu extreme of go_ctl_bot's model.

---

## B. Shell tunnels (Telegram as a remote shell)

### 7. AndreaBonn/remote-terminal-bot (3★, Python, MIT) — SECURITY DOC + STRUCTURE
The most security-engineered shell bot in the scan.
- **Layers (SECURITY.md, verified against src layout):** single authorized chat ID, others **silently rejected + logged with chat ID for audit**; private-chat-only; 30 cmd/min rate limit; 2048-char command cap; 512 KB output cap; command timeout SIGTERM→SIGKILL (30s default/300s max); **shell session auto-resets after 30 min idle** (limits exposure window); systemd sandbox (512 MB RAM, 50% CPU, 64 tasks); persistent shell session with cwd (`shell_session.py`), state manager, dedicated `audit_log.py`.
- **Steal verdict:** HIGH for the *limits table* — idle-session-reset + output cap + audit log of rejected attempts are all absent-or-thinner in v2's phone path (v2's gate has action caps, but the phone surface should log rejected strangers too — currently it just refuses).

### 8. htlin222/telegram-tunnel (3★, Python, MIT) — CODE READ
Markets itself as shell "via encrypted" tunnel; in code the only encryption is Telegram's own transport.
- **Auth:** `ALLOWED_USERS` env set; **fail-open hole:** `is_authorized()` returns `True` when the set is EMPTY — an unconfigured deploy is open to the entire internet. The single most common hole pattern in this whole scan (variants in clibot's "whitelist disabled = allow all with a warning", Botix's env-parsing edge, tg-cli-control's empty-set path).
- **Defense that does exist:** command + directory **blacklists** loaded from files (`blacklist_cmd.txt`, e.g. `rm`) with path normalization before compare (`Path.resolve`-based prefix logic, `normalized.startswith(blocked + os.sep)`) — a blocklist, i.e. default-allow, which loses to v2's default-deny gate by design.
- **Steal verdict:** none for v2 (v2's model is strictly better); valuable as a catalogue entry — *blacklist + fail-open* is what the hobbyist field ships.

### 9. Kroks4502/go_ctl_bot (1★, Go, MIT) — CONFIG + CODE
**Declared-menu model:** `config.yml` defines `admins:` (user IDs) and a nested button menu where every leaf is a **fixed argv command** (`name: sudo, args: [systemctl, start, X.service]`). No free text is ever interpreted; execution is exec-with-argv, not a shell string. Users can only press what the owner pre-declared.
- **Steal verdict:** MEDIUM-HIGH as a UX shape for v2's R1: a **pre-declared "owner's remote menu"** (owner authors fixed actions on desktop; phone just taps them) complements free-text R1 for the most sensitive verbs. Zero injection surface by construction.

### 10. fnzv/trsh-go (16★, Go, MIT), 11. fnzv/trash (4★, Go), 12. FuukaSyafiq/wowshell (2★, Go), 13. Blue-B/Botix (0★, Python, "securely execute shell commands" — shell=True present in code), 14. marioperator/shell-bot, 15. zenaleksey/tgdrive, 16. Al-Muhandis/ShellRemoteBot (54★, Pascal) — BATCH TRIAGE + AUTH GREPS
One archetype: env allowlist → `shell=True`/exec free text. Botix's `ALLOWED_USERS = list(map(int, os.getenv("U_Number","").split(",")))` throws on empty env (crash = accidental fail-closed, the only safe failure in the batch). Nothing individually stealable; together they prove the field's center of gravity: **identity check, then unlimited shell, no tiers, no confirmations, no audit.**

### 17. taraknath341/telegram-shell (0★, JS, "A secure Telegram bot… using Telegraf and node-pty") — TRIAGE
True PTY (interactive prompts work — `sudo`, REPLs) vs the field's one-shot exec. Noted: v2's phone shell is intentionally one-shot; PTY is an R2-class feature, correctly excluded.

---

## C. Bridges to desktop AI agents (phone drives a coding/agent CLI)

### 18. keepmind9/clibot (30★, Go, MIT) — CONFIG CODE READ
ACP-compatible bridge: phone IM (Telegram/Discord/etc.) ↔ Claude Code/Codex/Gemini CLIs on the PC.
- **Auth (inside):** `internal/core/config.go` — `security.allowed_users` + whitelist toggle; **config validation refuses to start if whitelist is enabled with an empty user list** (`"security.allowed_users cannot be empty when whitelist is enabled"`). That is the correct answer to the field's fail-open disease: make the dangerous config **unrepresentable at startup**.
- Multi-platform (one core, many IM adapters), watchdog + proxy modules (process supervision — restarts dead agent CLIs).
- **Steal verdict:** HIGH, one line of doctrine: v2 setup should **refuse to enable phone remote with an empty allowlist**, enforced in config validation, not in docs.

### 19. DlaregY/claude-assistant-bridge (1★, Python, license present) — CODE GREPS + README
Webhook-based (not polling): Telegram → FastAPI `webhook_server.py` → Claude; ~1s latency claim.
- **Auth:** single `ALLOWED_USER_ID`; **per-chat asyncio locks serialize messages** (two rapid phone messages can't interleave into one agent session); sessions keyed by chat_id with explicit reset; test suite includes **16 routing/auth/dedup tests** — dedup matters because Telegram retries webhook deliveries (same `update_id` twice = command executed twice unless deduped).
- **Steal verdict:** MEDIUM — (a) webhook mode as a latency option when a public endpoint exists (v2 polls; polling is the right default for NAT'd home PCs, webhooks need exposure); (b) **update_id dedup as an explicit, tested invariant**; (c) per-chat turn lock — v2's phone handler should serialize per chat the same way.

### 20. regreenjr/openditto (1★, Shell, license in repo) — DOCS/DESIGN READ
An installer + hardening wrapper around Claude Code's official Telegram plugin. The **pairing ceremony is the cleanest in the scan**:
1. Daemon starts with policy = `pairing`, allowlist **empty**.
2. Owner messages the bot → bot issues a **pairing code**.
3. Owner approves the code **on the Mac** (local action) → Telegram user ID is written to the allowlist.
4. Installer then **flips policy from pairing → allowlist-only** and verifies the lock; its troubleshooting notes treat "lockdown skipped" as a known failure mode.
- Honest threat doc (README): *"The Telegram sender allowlist is the single gate… If your Telegram account is compromised, an attacker has effectively full control of your machine via text message."*
- **Steal verdict:** HIGH on ceremony *sequencing* — v2 already has 6-digit single-use 5-min pairing; openditto adds **"pairing mode is a distinct, self-closing state"** (after first successful pair, pairing closes until owner re-opens it from the desktop). Check v2: if `issue_pairing_code` can be re-triggered remotely, close that.

### 21. hamvex/Claude-Code-Telegram-Remote-Agent (3★, TypeScript) — STRUCTURE READ
Windows-native (pm2 `ecosystem.config.cjs`, `start.bat`) Claude Code driver with browser/profile tools. Farsi+English READMEs. No visible pairing innovation in structure. No steal.

### 22. tuchg/Lucarne (339★, Rust, MIT) — README/ARCH READ (code: crates layout)
Daemon supervising multiple local agent CLIs (Claude/Codex/Gemini/Copilot/Pi/Grok), pushing **actionable** mobile events to Telegram/WeChat: permission approvals, clarifying questions, failure notices, with `[Approve]/[Deny]` taps routed back into the right session.
- **Routing:** Telegram **Forum Topics = workspaces** — one topic ↔ one live agent session (Bot API topics in a private chat, no supergroup needed). WeChat uses *quote-to-route*: quote a notification, reply, and the reply lands in the originating session (`message_id` preferred, quoted-text hash fallback).
- **Offline/backpressure:** channel adapters own **queues + retries**; `/latest` (or `/l`) **drops the backlog and delivers only the newest notification round per workspace** — a designed answer to "phone was off / PC kept working."
- **Auth:** `TELEGRAM_CHAT_ID` + `LUCARNE_AUTHORIZED_USER_IDS` env; structured approval support varies per agent (matrix in README).
- **Steal verdict:** HIGH for the *notification* direction (PC→phone): topic-per-session routing + **digest-on-reconnect (`/latest` semantics)** is exactly what v2's proactivity/phone channel lacks today. v2's urgent enum could ride this: while phone unreachable, queue; on reconnect, send latest-state digest, not a replay flood.

### 23. Ozymandes/TENDRIL (35★, Python/shell, MIT) — README READ (code not deep-read)
Different philosophy: **no bot at all** — phone (Termux) → Tailscale → Mosh/SSH → the real session, with ntfy for push nudges. "Leave the laptop. Keep the machine." Security = WireGuard mesh + SSH keys; there is no application-layer auth to get wrong. Noted as the *transport alternative*: for a single technical owner it beats bots on safety; for JARVIS's owner (zero-terminal rule) a bot is the right UX — but **Tailscale as the transport under the bot** removes dependence on Telegram's servers ever seeing command content.
- **Steal verdict:** strategic note only (already known: Tailscale connector exists in this workspace).

### 24. SergioCc13/jarvis (0★, Python) — README/CLAUDE.md READ
Namesake: Claude Code + voicemode (local Whisper STT + Kokoro TTS), HUD, phone access via **Tailscale Serve**: phone opens `https://<node>.ts.net/hud/?token=<bridge token>` once; token persists in browser; a **Face ID/fingerprint gate** sits in front (author honestly labels it a UX guard, not a security boundary — the token is). Voice from the phone mic over HTTPS (mobile browsers require HTTPS for mic — hence Serve).
- **Steal verdict:** MEDIUM — if v2 ever ships a phone *web* surface: Tailscale Serve + one-time token URL + platform biometric unlock prompt is the proven shape; and "HTTPS is required for phone mic" is a real constraint for any browser-voice plan.

---

## D. Structured approval systems (the confirmation-flow specialists)

### 25. agentrq/agentrq (1,162★, Go, dual-license AGPL/commercial → ideas only) — ARCHITECTURE READ
Human-in-the-loop task manager for agent fleets; the most formal permission model in the scan.
- **Flow (ARCHITECTURE.md, code-mapped):** agent tool call → MCP `notifications/claude/channel/permission_request` → **auto-allow check** (`workspace.AutoAllowedTools` or task-level `AllowAllCommands`) → else a `permission_request` message is pushed to the human UI over SSE → human answers `allow` / `deny` / **`allow_always`** → verdict returns via MCP notification; `allow_always` **promotes the tool into the workspace auto-allow list**. Every step lands in a telemetry/audit stream (approvals, denials, tool calls) feeding a dashboard.
- **Steal verdict:** HIGH — the **three-way verdict (`allow once / deny / allow always`) with promotion into a scoped allowlist** is the one confirmation idea v2 doesn't have: v2's R1 asks every time (PIN fatigue) or never (R2). A v2 version: "allow always" must stay *per-tool + per-args-shape* and never apply to R2 classes. Note v2's ApprovalBudget (5/day) already guards the fatigue failure mode from the other side.

### 26. PDAgent AI-action confirmations — counted at #1 (pending store + expiry + callback re-validation). 
### 27. remotepc-pro typed `confirm` — counted at #4.
### 28. remote-terminal-bot rate/idle limits — counted at #7.

---

## E. Phone-side control (AI operates the phone itself)

### 29. SammoMichael/phone-bridge (0★, Java) — DOCS READ
Reverse direction: PC-hosted agent drives an Android phone via an Accessibility-service app + HTTPS command queue.
- **Auth:** one shared secret token, **constant-time compared on every request**, stored in a `600`-permission file, never in the repo; app stores only server URL + token; explicit doctrine: *"never pass [banking] credentials through the queue."*
- **Steal verdict:** MEDIUM — constant-time token compare + file-permission discipline are one-liners v2 should mirror for any token compare in phone.py (PIN path already uses PBKDF2; check any raw token comparisons).

### 30. kengerlwl/phone-assistant (0★, Kotlin, license in repo) — DOCS READ (very detailed)
Attended, self-hosted Android assistant: app + WSS bridge + Docker.
- **Pairing protocol (the best-specified in the scan):** `manage.py pair` prints an **8-digit code + `phoneassistant://pair?...` deep link**; link is a short-lived credential — **10-min expiry, single consumption, max 20 attempts**; **re-pairing is impossible while a phone is online**; replacing a phone requires disconnecting the old one first, and the new pairing **replaces the old device credentials**; `.env` generated with `0600`, control API bound to `127.0.0.1` only, public surface is just `POST /pair` + the WSS device socket.
- **Command safety:** RPC **method whitelist** (`state, capture, screenshot, tap, swipe, …`); the bridge allows **one in-flight command**; doctrine worth quoting: *failure/timeout/disconnect may mean the RESULT IS UNKNOWN — observe first; never auto-replay write operations.*
- **Steal verdict:** HIGH — two transfers to v2: (a) **re-pair lockout while paired device is active + credential replacement semantics**; (b) the **unknown-outcome rule** for R1: if a confirmed write's result channel dies mid-flight, v2 must report "unknown — check the PC" and never silently retry. That closes a real double-execution hole (e.g. message sent twice).

### 31. inoahaipro/phoneclaw (0★) — TRIAGE: Android automation agent, accessibility-driven; same family as 29/30, no new mechanism found at triage depth.

---

## F. The RAT mirror (why the gate exists)

### 32. BYPASS-CODEE/TELEGRAM-RAT (1★), 33. OhmnicDev/JerryRAT (3★), 34. DsMans0021/Telegrojan, 35. yeeter727/RATshell — README TRIAGE
Feature lists identical to §A remotes **plus** webcam/mic capture and background keylogging. Same Bot API, same polling loop, same allowlist (theirs points at the attacker). Two lessons for v2: (1) any "remote bot" UX is dual-use — v2's R2 list (never-remote: shell, camera/mic surveillance-class tools) is the correct product answer; (2) these repos are what AV flags — v2 should keep phone.py's vocabulary clean (no keylog/webcam-adjacent capabilities reachable from the phone surface, even read-only).

---

## G. Chat-first phone assistants (WhatsApp/Telegram AI, no PC control)

### 36. AstrBotDevs/AstrBot (42,316★, Python) — STRUCTURE/TRIAGE
Multi-platform IM agent framework (Telegram/QQ/WeChat/Discord…), plugin marketplace. Relevant as the ecosystem benchmark: session-per-conversation contexts, platform adapters isolated from agent core (same split as Lucarne). No PC control; no steal for phone.py beyond adapter isolation (v2 already isolates).

### 37. LlmKira/Openaibot (1,965★), 38. countbot-ai/CountBot (784★) — TRIAGE
Tool-calling chat bots across IM platforms (CountBot: WeChat/Feishu/DingTalk adapters). Pattern: chat_id-bound sessions, no device control. No steal.

### 39. guru-prasath-j/whatsapp-personal-bot (0★, JS) — AUTH GREP
WhatsApp via whatsapp-web.js (unofficial, QR pairing to the *owner's own number*), RAG + local Ollama. **Auth:** `ALLOWED_NUMBERS` env, checked as `if (ALLOWED_NUMS.length > 0 && !ALLOWED_NUMS.includes(sender)) return;` — **fail-open when unset**, the field's signature bug, on WhatsApp too. Note the platform risk: unofficial WhatsApp bridges (Baileys/whatsapp-web.js) regularly get numbers banned — Telegram's official Bot API is why v2's Telegram choice is right.

### 40. Zvimarmor/WhatsApp_Bot (0★, TypeScript) — STRUCTURE READ
"AI secretary in WhatsApp" (calendar/tasks/habits/persistent memory, SQLite via dist). Represents the secretary-class: memory + reminders over chat, zero device control. The reminder/habit loop is v2-notes territory, not phone.py.

Also triaged (no new mechanism, counted in the 90+30 triage pool, not the 40): AyraHikari/EmiliaHikari, LEGENDXOP userbots, m4mallu/PMChatbot (pm-permit approve/deny for strangers — a pairing-adjacent pattern for *people*, not devices), leox255/loopsy, inercia/mitto, chadingTV/claudecode-discord, loppo-llc/kojo, eggbrid2/mobileClaw, xjyzs/Operator-on-Android (phone-side agent runtimes — wrong direction for v2), msgbyte/tianji-class dashboards.

---

## Cross-cutting findings

**Pairing/auth models, ranked by strength (as implemented, not as documented):**
1. **Pairing ceremony + self-closing pairing state** (openditto; phone-assistant's code+expiry+attempt-cap+replacement) — strongest.
2. **OTP over the chat channel, hash-at-rest** (remotepc-pro) — for web surfaces.
3. **Fail-closed allowlist, validated at startup** (PDAgent, clibot) — the field's sane baseline; v2 sits here, plus PIN.
4. **Chat-ID bind in a config file** (Ahmed-Z, lazuardyk) — works until the username-vs-ID confusion bites.
5. **Fail-open allowlist** (telegram-tunnel, WhatsApp bots, Botix-class) — an empty env var silently makes the bot public. The scan's most common real-world hole.

**Command grammars:** four families — (a) slash commands (cleanest, discoverable); (b) exact-match button text/emoji keyboards (Ahmed-Z — friendly, brittle to rename/localization); (c) prefix-free-text (`cmd …`, `cd …` — shells in disguise); (d) **declared menus of fixed argv** (go_ctl_bot — zero injection surface); (e) natural language → LLM → typed tools with confirmation (PDAgent/AstrBot-class; v2's R1). v2 spans (a)+(e) today; (d) is the missing cheap win.

**Voice notes:** PC-control bots essentially **never** transcribe them — files are downloaded as attachments (tg-cli-control saves `.ogg` into the session cwd; 20 MB Bot API cap surfaced to the user). Transcription lives in chat-first bots and in SergioCc13's *local* Whisper (audio never leaves the machine). v2's design (voice note → download → **local STT only**, never confirm by voice) matches the best practice found anywhere in the scan. Nobody beats it; several would leak audio to cloud STT by default.

**PC-offline behavior:** the scan's weakest dimension field-wide. Taxonomy of what actually happens: (1) Telegram queues updates server-side; **polling bots drain the backlog on reconnect** — several codebases (lazuardyk) rely on a volatile `last_update` watermark, so a restart + backlog = replays or drops; webhook bots need Telegram-side retry + own dedup (DlaregY tests it); (2) *agent-state* notifications pile up → Lucarne's `/latest` digest is the only designed answer; (3) *intended-future work* survives via persistent schedulers (PDAgent) — the only repos whose "commands" execute after an offline gap are the ones that stored them on disk themselves.

**Security holes catalogue (all seen in code):** fail-open empty allowlist · username-based auth · token in URL/GET params (logged) · `shell=True` on free text · arbitrary-path file download (exfil) · no rate limit anywhere (brute-forceable PIN-less bots) · secrets committed via config-file patterns · group-chat output leakage (screenshots/clipboard posted where the command was typed) · no dedup → double execution on webhook retry · pending-confirmation stores without expiry (PDAgent purges; most don't have confirmations at all).

---

## Top 5 mechanisms (ranked for v2)

1. **Pairing as a self-closing state with replacement semantics** (openditto + phone-assistant): pairing open only until first pair; re-pair requires local action + active-device lockout; new pairing revokes old credentials.
2. **Pending-action store with expiry + callback re-validation** (PDAgent `_queue_confirmation`): random action_id, user/chat binding, TTL purge, rate-limited requests — the industrial form of v2's hash-bound confirmation.
3. **The `allow / deny / allow-always` verdict with scoped promotion** (AgentRQ): kills per-action fatigue without opening R2; promotion recorded in audit.
4. **Reconnect digest, not replay** (Lucarne `/latest` + queues/retries in channel adapters): PC→phone notifications collapse to latest-state per session after any gap.
5. **Declared fixed-action menu** (go_ctl_bot): owner-authored argv actions, tapped from the phone, zero free-text parsing — the safest possible R1 surface for power verbs.

## Top 3 steals for v2's `phone.py`

1. **Self-closing pairing + re-pair lockout** (from #20/#30): after a successful pair, `issue_pairing_code` should refuse until unpaired/revoked **on the desktop**; a new pairing must revoke the previous device's binding. Add phone-assistant's **unknown-outcome rule**: if an R1 write's confirmation/result path dies mid-flight, report `unknown — verify on PC`, never auto-retry the write.
2. **Two additions to the R1 confirmation**: (a) PDAgent-style **expiring pending store keyed by action_id with chat/user re-validation on callback** (v2's hash binds the action; add explicit TTL + purge + "this confirmation expired" reply), and (b) AgentRQ's **`allow always` for exact (tool, args-shape) pairs**, persisted, revocable from desktop, and hard-blocked for R2-adjacent tools — directly attacks PIN fatigue without weakening the gate.
3. **Offline/reconnect discipline** (from #7/#19/#22): persist a **monotonic `last_update_id` watermark** (survives restarts; dedup as a tested invariant), **log rejected stranger attempts** (user_id + timestamp, silent to the sender — PDAgent/R-T-B pattern), and on reconnect after a gap, send **one latest-state digest** instead of processing a stale command backlog — stale *commands* older than the pairing session's freshness window should be refused, not executed.

**Honorable mentions:** remote-terminal-bot's limits table (30/min, output cap, 30-min idle session reset, audit log) as a checklist for phone-surface hardening; clibot's startup validation (phone remote + empty allowlist = refuse to start); LogonUI.exe lock-state check for a `pc.status` phone reply; SergioCc13's Tailscale Serve shape if a phone-web surface is ever built.

**Where v2 already beats the field (verified against its source):** tiered R0/R1/R2 (only PDAgent is comparable), action-hash-bound confirmations (nobody else binds the *content*), PIN with PBKDF2 hash + never-store (nobody else has a second factor in-chat), voice notes local-STT-only + never-confirm (best-in-scan), DCL/redaction on the reply path (unseen elsewhere in this category).
