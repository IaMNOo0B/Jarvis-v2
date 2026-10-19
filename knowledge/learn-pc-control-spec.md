# PC Control Design Specification — JARVIS v2

*PHASE INFINITY, Research Cycle 22. LEARNING ONLY — design document, no implementation.*
*Date: 2026-10-19. Status: spec complete, unvalidated on a real Windows driver build.*

---

## 0. Scope and non-goals

**This spec covers:** how v2 observes and acts on the Windows desktop — the defining "full PC control" capability — safely, verifiably, and cheaply. It is the document the UIA driver port gets built from.

**Non-goals:** voice loop (Cycle 15), browser automation as its own domain (ghost browser already exists — this spec covers desktop GUI, not Chromium), mobile control, remote-desktop control of other machines.

**The one-line thesis:** v2 reads the UI Automation tree first (free, exact), grounds pixels only when the tree is insufficient (ShowUI-2B on the 2060), acts by writing one unified Python program per step (OpenGCUA), verifies every action by re-observation, and never drives a destructive UI flow without a real out-of-band approval. Every clause below traces to a source; every target is PROPOSED until measured.

---

## 1. The observation stack [VC on the order, HC on details]

The observation order is FIXED — never a model decision, always the harness's. Rationale: the cheapest stage that can answer rejects first (the staged-wakeup doctrine, V5 in DECISION-PLAYBOOK; multimodal T4/T6). Each rung is ~10–25× cheaper than the next.

```
OBS-1: UIA tree (filtered to actionable elements)      — 0 tokens, milliseconds
   └─ fail? → OBS-2: OCR on cropped window/region       — ~0.1–0.3s CPU (Tesseract)
   └─ fail? → OBS-3: local screenshot + local VLM        — ~0.5–1s, 0 tokens sent anywhere
   └─ fail? → OBS-4: cloud vision, budgeted and gated    — $0.005–0.007/shot, per-task budget
```

### OBS-1: UIA tree first (always)

- Walk the UI Automation tree of the **target window only**, filtered to actionable elements (buttons, text fields, menu items, list items). Full-desktop tree walks are slow — never do one; scope to the window under control.
- The tree yields names, roles, and pixel bounds straight from the OS: no guessing, no hallucination, DPI-independent. [HC — multimodal T4, 90%]
- **Namespace separation (adopted from OpenGCUA):** UIA element handles and screen coordinates are DIFFERENT TYPES that can never be confused. An element reference is valid ONLY relative to the observation (tree snapshot) that produced it. [HC — opengcua-deep-dive §7.3–7.4]
- **Staleness rule:** a reference to a changed screen is REJECTED, not guessed. Element handles carry the snapshot version; if the window re-rendered since, the handle is invalid and the program must re-observe. This kills the #1 real-world grounding killer (stale screenshots) at the type level. [HC — opengcua-deep-dive §3.5]

### OBS-2: OCR (tree has text gaps)

- Crop to the target window/region, upscale 2× (screenshots are ~96–144 DPI; Tesseract wants ~300 DPI-equivalent), Tesseract for clean UI text (36MB, fastest), PaddleOCR when Tesseract fails on rotated/noisy text. [HC — multimodal T3]
- Never preserve reading order across columns — OCR returns boxes; layout is OBS-3's job. [VC — multimodal T3]

### OBS-3: local screenshot + local VLM

- For: canvas content, visual verification ("is the chart rendered?"), icon-only toolbars with no accessible names. A local 2–3B VLM on the 2060 = $0 marginal cost, ~0.5–1s. [HC — multimodal T1/T6]
- **Screenshots are untrusted content.** A malicious webpage rendered on screen is indirect prompt injection via pixels — REA untrusted-content markers apply to vision inputs exactly as they do to text tool outputs. Pixel-derived facts never become instructions; they enter context tagged as untrusted observation. [HC — multimodal T1/T2→Security cross-connection; REA evidence model]

### OBS-4: cloud vision (gated, budgeted)

- Only after OBS-1..3 fail, against a per-task vision budget, with the user's knowledge per R13 (privacy-safe defaults). Keep images out of rolling conversation history — re-capture fresh when needed; every pasted screenshot is re-billed every turn. [HC — multimodal T6]

**Open questions:** UIA tree-walk latency on heavy apps (Chrome with 50 tabs) — UNMEASURED, must benchmark on the 2060. [UK]

---

## 2. The action model — one unified Python program per step [HC]

**The action language is code, not clicks.** (OpenGCUA isolated ablation: +6.1 pts, −14.8% steps with identical GUI+shell access — the mechanism is real, not confounded. [HC — opengcua-deep-dive §2/§4])

### 2.1 The program shape

Each step, the brain writes ONE Python program against the PC-control SDK, combining UIA actions + shell + app APIs, with loops, branches, and asserts. A GUI-only agent needs ~60 steps for 29 repetitive edits; one program does it in one step with in-code verification (`assert current==original` catches drift INSIDE the step, where a click-agent discovers it 10 steps later). [HC — opengcua-deep-dive §2]

**Mandatory prologue for every program:**
```python
<intent>...</intent>          # what this program is trying to do, in words
todo.update(...)               # the step joins the running todo list (flight recorder)
obs = observe(window)          # fresh observation; handles bind to THIS snapshot
```

**The intent + todo pattern is not decoration** — it is the audit trail. v2's event bus captures intent+program+outcome as first-class events (session store, Cycle 14). Every PC action is replayable and interrogable. [HC — opengcua-deep-dive §7.6]

### 2.2 The action vocabulary

**Allowed (through the SDK, never raw):**
- `click(element)` / `invoke(element)` — UIA InvokePattern preferred over synthetic mouse when available (works on background windows without touching the cursor)
- `type_text(element, text)` — typed into a named element, not "type at coordinates"
- `hotkey(*keys)`, `scroll(element, delta)`, `drag(element, to_element)` — drag endpoints must BOTH be grounded elements, never raw coordinates
- `run_shell(cmd)` — sandboxed per R5 (no network except allowlist, scratch dir only, secrets scrubbed)

**Forbidden (SDK refuses to compile/run):**
- Raw coordinate clicks with no grounded element behind them. Coordinates must come from a grounding pass (OBS-1 bounds or OBS-3 grounder output) tied to the current observation snapshot.
- Actions on elements not observed this turn — **"only act on what you have been shown" is an SDK-enforced invariant**, not a prompt instruction. The SDK rejects element handles from stale snapshots; it does not guess. [HC — opengcua-deep-dive §3.4/§7.3]
- `type_text` containing shell metacharacters routed to a shell context without escaping — see C-X4 below. The SDK distinguishes "type into a text field" from "execute in a terminal" as different functions; they cannot be confused.

### 2.3 Background operation

Actions go through UIA automation elements, NOT the mouse cursor. Target a window by its UIA identity (RuntimeId = durable identity across time); the user's foreground window, cursor, and focus are untouched. A background window the user opened mid-task cannot be acted on until explicitly observed — the safety rail that makes background operation trustworthy rather than spooky. [HC — opengcua-deep-dive §6]

**Confidence:** [HC] 85% that the code-per-step architecture is right (isolated ablation + 8-model replication); [MC] 70% that the 53% step-reduction replicates on Windows/UIA (unmeasured — UIA has different latency/robustness than macOS AX). [opengcua-deep-dive Calibration]

---

## 3. Grounding — pixels only when the tree is insufficient [HC]

**Grounding is the fallback actuator, not the primary one.** Planner (brain) generates the referring expression; the grounder resolves coordinates; action executes; tree/screenshot verifies. [HC — multimodal T2]

### 3.1 The 2060 pick: ShowUI-2B

- ShowUI-2B (~2GB Q4): fits resident alongside the brain. 77.3% ScreenSpot-v2 avg, 7.7% on ScreenSpot-Pro (honest: weak on dense professional UIs). [HC — multimodal T2]
- 7B-class grounders (OS-Atlas-7B: 84.1% / 18.9% Pro) need ~14–16GB BF16 — do NOT fit. Options if needed: partial CPU offload (~2–4s/click, slow) or cloud fallback (never default — pixels leave the machine). **Recommendation: ShowUI-2B resident; 7B only via gated cloud fallback.** [HC — multimodal T2]
- **License check required:** reported Apache-2.0 for ShowUI/OS-Atlas — VERIFY the `license:` field on the exact pinned checkpoint before vendoring. [per index license posture]

### 3.2 The accuracy/latency budget

- **Budget: 800ms per grounding call** (p95), one forward pass ~0.5–1s for 2B on the 2060 (derived, UNMEASURED — benchmark in Cycle 9's Track C). [MC — multimodal T2/T6]
- **The zoom-in trick (highest ROI in the field):** coarse pass on full screen → crop candidate region → fine pass on crop. GUI-AIMA-3B: 49.8% → 59.6% on ScreenSpot-Pro. Always zoom before clicking small targets. [HC — multimodal T2]

### 3.3 Low-confidence grounding = ask, don't click blindly

- The grounder's coordinate output is a guess with no uncertainty signal. Policy: if the tree gave bounds, use them (exact). If grounding was needed and the target is **tier-1** (reversible, e.g. opening a menu), click-then-verify is acceptable. If the target feeds a **tier-2/3** action, grounding confidence must be corroborated — re-ground on the zoomed crop and require agreement, or escalate to the user with the crop shown. **Never click blindly into an irreversible action on a single uncorroborated coordinate.** [MC — synthesis of multimodal T2 limits + fault-tree human-side findings]
- Multiple identical targets ("click OK" with 3 dialogs open): the planner must disambiguate by window/position BEFORE grounding; ambiguous referring expressions are a planner failure, not a grounder failure. [HC — multimodal T2]

**Open questions:** grounding accuracy on real live Windows apps (benchmarks ≠ live sessions) [UK]; Hindi/Hinglish UI text grounding quality [UK]; exact 2060 latency for ShowUI-2B [UK — Cycle 9 Track C].

---

## 4. Safety — GUI actions are never silent [HC]

### 4.1 Tiering

- **Every GUI action is tier-2 minimum**: announced ("Opening Settings → Display") with undo where possible. Reads (observe, OCR, screenshot) are tier-1, auto-allowed. [DECISION-PLAYBOOK S3]
- **Destructive UI flows are tier-3** with the full out-of-band approval dialog: deleting files via Explorer, sending emails, submitting forms, changing system settings, anything crossing the machine boundary. **Never drive a destructive flow unattended.** [HC — fault-tree G4 findings; DECISION-PLAYBOOK S3]
- **Degradation never loosens permissions** (Cycle 12 hard rule): the gate, the jail, and redaction hold at every rung. A degraded JARVIS may lose the ability to SEE the screen — it never gains the ability to click without approval. [HC — learn-reliability-spec §4]

### 4.2 Capability grants (S2)

Every PC-control session declares capabilities (UI control scope: which apps, what actions). Grant per task. This is what makes "full PC control" shippable — the user grants "organize my Downloads folder," not "do anything with the mouse forever." [DECISION-PLAYBOOK S2 — Deno ×3]

### 4.3 Undo (S4)

Snapshot before every mutating GUI program. File operations: recycle-bin / backup copy, not permanent delete. Settings changes: record prior value. "I can undo anything" is the trust unlock that makes PC control acceptable to a non-technical user. [DECISION-PLAYBOOK S4]

### 4.4 The C-X4 rule (typing ≠ executing)

v1's `type_text` had a PowerShell injection hole: quote-stripping that newlines survived, breaking out of single-quoted strings into arbitrary PowerShell. The spec's fix is structural: **the SDK exposes `type_into_field(element, text)` and `run_in_terminal(cmd)` as different functions with different types.** Text is never evaluated; commands are never typed as text. There is no string path from a text field to a shell. [traces to C-X4]

### 4.5 Plan mode

For multi-step PC tasks, the brain states the plan first and takes a "yes" before executing (DECISION-PLAYBOOK S3). The plan names the apps, the actions, and the blast radius in plain language. This is also the rubber-stamping defense: the dialog shows origin proof + visible payload (action + target + blast radius) so a spoofed dialog has nothing convincing to show. [DECISION-PLAYBOOK S3; fault-tree B7 mitigation]

---

## 5. Verification — assert-after-act [HC]

### 5.1 The loop

**After every program, re-observe and confirm the expected state change.** The pattern (from OpenGCUA's measured example): assert the world didn't change since last look BEFORE acting; assert each effect AFTER acting; only then record `claimed_verified`. A GUI agent discovers drift 10 steps later; a program catches it inside the step. [HC — opengcua-deep-dive §2]

```
observe → program (with asserts) → re-observe → diff vs expected → verified / retry / escalate
```

### 5.2 "The click landed but nothing happened"

This is the most common real-world PC-control failure (app busy, focus stolen, animation). The protocol:
1. Re-observe (fresh snapshot — the old one is stale by definition now).
2. Check: did the state change? (element gone, dialog open, text present)
3. If no: **one** retry with a settle-wait (the SDK waits for the interface to settle before observing — OpenGCUA's stabilization rule). [opengcua-deep-dive §3.5]
4. If still no: ESCALATE. **2-attempt rule** — Debugging Decay Index: the 1st fix helps, the 2nd is marginal, the 3rd+ degrades (up to 80% drop by round 5). The 2-attempt rule is the measured optimum, not a guess. [HC — learn-ai-for-se]
5. Never loop clicking. Never assume the click worked.

### 5.3 What verification records

Intent + program + per-assert outcomes go to the session store (Cycle 14). "Clicked Save, dialog closed, file size changed 12KB→14KB" is interrogable evidence — the answer to "what did you do at 3pm Tuesday?" for PC actions. [HC — learn-session-store]

---

## 6. The Windows specifics [MC — mostly derived, key items unmeasured]

### 6.1 Reading the tree in Python

`pywinauto` (BSD, `backend='uia'`), the raw `uiautomation` package, or FlaUI via pythonnet. Explore with `Inspect.exe` (Windows SDK) or Accessibility Insights. **This is the from-scratch port OpenGCUA hasn't built** (v1.0-planned, no date) — the single highest-value PC-control work for v2. [HC on the gap — opengcua-deep-dive §8; MEMORY.md]

### 6.2 Latency budget

- Tree walk of one window: target **<200ms** (PROPOSED — unmeasured; heavy apps unknown). Filter to actionable elements; cache window handles; invalidate on snapshot-version change. [UK — the measurement is Cycle 9-adjacent]
- If a tree walk exceeds budget, fall back down the observation stack is NOT the answer (a slow tree is still exact) — the answer is narrower scope (subtree of the focused pane). [MC]

### 6.3 Elevated/UAC windows — honest boundary

**JARVIS cannot touch elevated windows.** UIA enforces UIPI (User Interface Privilege Isolation): a medium-integrity process cannot automate a high-integrity window. This is not a bug to work around — attempting to bypass UIPI is a security boundary violation. When the target is elevated: say so honestly ("That window is running as administrator — I can't control it; here's what to click"), never silently fail, never attempt a bypass. [HC — Windows platform fact; the honest-UX rule R12]

### 6.4 Multi-monitor and DPI

- Coordinates from the tree are in physical pixels; the grounder emits 0–1000 normalized. The SDK converts with the monitor's actual DPI scale — never assume 96 DPI. Per-monitor DPI mismatch is a known latent bug class (v1's `geo` 1px/DPI notes). [MC — FAILURE-ANALYSIS UI notes]
- Multi-monitor: element handles carry their monitor; a window moved mid-task invalidates the snapshot (staleness rule §1) and the program re-observes. [MC]

### 6.5 What the driver owns (the port checklist)

Durable element identities (UIA RuntimeId), versioned snapshots, filtered actionable elements, native mechanism per action (InvokePattern > synthetic input), background-window execution, stabilization waits, permission preflight (UIA access grants) before every task. [HC — opengcua-deep-dive §3]

---

## 7. The failure table — every v1 corpse gets a clause

*Note: the parent brief cited M-S8/M-S18 as GUI-control corpses; in FAILURE-ANALYSIS.md those are sys.path pollution and IG login handling — not GUI control. The table below covers the actual GUI-control corpses found by reading the file. No orphans.*

| Corpse | What v1 did | Spec clause that prevents it |
|---|---|---|
| **H-S4** — Full unattended GUI control, zero confirmation; could drive destructive UI flows | type_text/hotkey/press/mouse with no gate | §4.1: every GUI action tier-2 minimum; destructive flows tier-3 with out-of-band dialog. §4.2: per-task capability grants. There is no code path from brain to mouse that skips the gate. |
| **C-X4** — PowerShell injection via type_text (newlines survived quote-stripping → arbitrary PowerShell) | text and shell shared one function | §4.4: `type_into_field` and `run_in_terminal` are different functions with different types; no string path from text field to shell. |
| **M-X20** — type_text stripped ALL single quotes ("don't"→"dont"); 4000-char silent truncation | lossy, silent text mangling | §2.2: text goes to a named element verbatim — the SDK never transforms user text. Oversize input is a loud error naming the limit, never a silent truncation (R12 honest UX). |
| **M-X18** — injected page steered LLM into state-changing clicks / credential fills via ghost browser | observation trusted as instruction | §1 OBS-3: screenshots are untrusted content — pixel-derived facts tagged untrusted, never instructions (R2 instruction hierarchy). §3.3: no blind clicks into consequential actions on uncorroborated grounding. |
| **H-U4 / M-U13** — fake click-through; 120ms click-eating window on HUD show | overlay ate clicks meant for the desktop | Driver-level (not model-level): the HUD must never intercept input destined for controlled windows; PC-control programs target UIA elements directly, not screen regions under the HUD. Noted as driver acceptance criterion. |

---

## 8. Build order (when PC control's turn comes)

1. **UIA driver port** — tree walk + element identities + InvokePattern on background windows. No pixels yet. (Highest value; OpenGCUA's missing piece.)
2. **SDK + program runner** — the action vocabulary, snapshot-versioned handles, staleness rejection, stabilization waits, intent/todo capture.
3. **Grounding fallback** — ShowUI-2B resident, zoom-in trick, 800ms budget, low-confidence escalation.
4. **Safety layer** — tiering, capability grants, undo snapshots, plan mode, approval dialogs in trusted chrome.
5. **Verification loop** — assert-after-act, 2-attempt retry, session-store recording.
6. **Measurement** — Cycle 9-style benchmarks for tree latency, grounding accuracy/latency on real apps, step-reduction vs click-baseline on Windows.

Voice stays a plugin (R1); PC control is a *phase*, not a layer — it arrives after the text core is solid.

---

## Open questions (ranked)

1. UIA tree-walk latency on heavy apps (Chrome 50 tabs) — UNMEASURED [UK]
2. ShowUI-2B accuracy/latency on real live Windows apps — UNMEASURED [UK]
3. Whether the 53% step-reduction replicates on Windows/UIA [UK — needs the benchmark in §8.6]
4. Hindi/Hinglish UI text grounding quality [UK]
5. UAC-adjacent UX: how often real tasks hit elevated windows, and the best honest-degradation copy [UK]
6. License verification on the pinned ShowUI checkpoint (reported Apache-2.0 — verify before vendoring)

## Confidence summary

- [VC] (>95%): the observation order (tree → OCR → local vision → gated cloud); screenshots are untrusted content; 2-attempt retry rule (measured).
- [HC] (80–95%): code-per-step beats clicks (isolated ablation); namespace separation and staleness rejection as SDK invariants; ShowUI-2B as the 2060 pick; tier-2-minimum for GUI actions.
- [MC] (60–80%): 800ms grounding budget (derived); step-reduction replicating on Windows; DPI/multi-monitor handling sufficiency.
- [UK]: all latency/accuracy numbers on real hardware — the benchmarking weekend resolves them.

---

## Honest completion (Rule 12)

- **Researched:** opengcua-deep-dive.md (full), learn-multimodal.md (full, esp. T1–T4, T6), FAILURE-ANALYSIS.md (GUI-control findings via targeted grep — corrected two mis-cited finding IDs from the brief), DECISION-PLAYBOOK.md (S2, S3, S4, V5).
- **Validated:** finding IDs cross-checked against the actual FAILURE-ANALYSIS.md text (H-S4 confirmed; M-S8/M-S18 confirmed UNRELATED — reported, not silently swapped).
- **Saved:** 1 file (`~/workspace/jarvis-knowledge/learn-pc-control-spec.md`).
- **Modified / Tested / Measured:** nothing — design only, learning mission.
- **Incomplete:** none — all 7 requested sections written with the failure table closed (no orphans).
- **Blocked:** execution-side measurements (UIA latency, grounding accuracy/latency on the 2060) — recorded as open questions, not assumed.
