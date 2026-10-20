# MEGA-SCAN TEAM 18 — VISION & UI GROUNDING MODELS

**Mission:** Beyond OCR — how do agents *see* screens? Vision models that locate UI elements,
set-of-mark prompting, screen parsing, visual grounding. JARVIS v2 is UIA-first / vision-last;
this report finds the vision layer's best form.

**Method:** `git clone --depth 1` into `megascan/.work18/` + local reads. The VM's GitHub link is
heavily throttled: 29 clones completed cleanly (git, incl. redo round); 3 more rescued via
codeload tarballs (GroundingPI, DiMo-GUI, SkalskiP/SoM); 8 read via raw README fetch (ShowUI,
UGround, UIED, SAGE, SoM, agent-vision-toolkit); 5 never landed (SeeClick, florence, OSWorld-G,
UI-UG tarball, agent-vision-toolkit tarball) and are marked [TRIAGE] with only well-established
facts, tagged [MC]. **Coverage: 40 repos.** Depth tags: [DEEP] code read · [LIGHT] README+structure ·
[RAW] README via raw fetch · [TRIAGE] not opened.

**Confidence tags:** [VC] verified in the clone · [HC] repo-stated · [MC] memory/secondary — verify
before building on it.

---

## 1. THE YARDSTICK — ScreenSpot-Pro accuracy (professional apps, high-res, small icons)

ScreenSpot-Pro is the benchmark that matters for a Windows PC agent (SS v1 is saturated: every
7B scores 82–94% there and it proves almost nothing). All numbers repo-stated [HC]:

| Model | Size | ScreenSpot-Pro | Notes |
|---|---|---|---|
| **GUI-AIMA-3B** | 3B | **53.8 → 61.5** (2-step zoom) | zoom cascade adds ~8 pts |
| **UI-TARS-1.5-7B** | 7B | **61.6** | best 7B-class single-pass |
| UI-Ins-32B | 32B | 57.0 | cloud-class only |
| SE-GUI-7B | 7B | 47.2 | attention head, only 3K training samples |
| GUI-Actor-7B (Qwen2.5-VL) | 7B | 44.6 | coordinate-free attention + verifier |
| GUI-Actor-3B (Qwen2.5-VL) | 3B | 42.2 | |
| OmniParser v2 + GPT-4o | parser+cloud | 39.5 | the SoM pipeline number |
| UI-TARS-7B (v1) | 7B | 35.7 | |
| SE-GUI-3B | 3B | 35.8 | |
| UGround-V1-72B | 72B | 34.5 | size ≠ accuracy here |
| UGround-V1-7B | 7B | 31.1 | |
| AGUVIS-7B | 7B | 22.9 | |
| OS-Atlas-7B | 7B | 18.9 | 2024-era, now weak |
| OS-Atlas-4B / UGround-2B / ShowUI-2B / ZonUI-3B | 2–4B | not SS-Pro-headline; SS v1 ≈ 75–85 class [MC] | the VRAM-friendly tier |

**Lesson 1:** a 3B with a zoom cascade (61.5) beats a 72B single-pass (34.5). *Procedure > parameters.*
**Lesson 2:** 2024's champions (OS-Atlas 18.9) are 2026's floor. This field moves in months.

---

## 2. THE 6 ARCHITECTURES (how a screenshot becomes a click)

**A. Parse-then-pick (Set-of-Mark pipeline)** — `microsoft/OmniParser` [DEEP]
Screenshot → EasyOCR (text_threshold 0.8, code-verified in `util/omniparser.py`) + a small YOLO
icon detector (`BOX_TRESHOLD`, IoU-0.7 overlap removal, coords emitted as *ratios*) + a Florence-2
caption model (batch 128 crops) → an annotated image + a structured list
`[{id, bbox, ocr_text, caption}]` → the *planner LLM* (GPT-4o / Qwen-VL / local) picks an **ID**,
never raw coordinates. Grounding becomes multiple-choice. Models: detector ~tens of MB,
captioner ~0.77B. Repo **CC-BY-4.0**; `icon_detect_v3` weights **MIT** (YOLOv9 base);
**older Ultralytics-based detectors are AGPL — use v3 only**; caption weights MIT [VC from LICENSE/README].

**B. End-to-end coordinate regression (the VLM *is* the grounder)** — UI-TARS, UGround, AGUVIS,
OS-Atlas, SeeClick, UI-Ins, GUI-R1, ZonUI. Screenshot+instruction → model emits `(x, y)` as text
tokens in 0–1000 relative space. Simplest integration (one call), accuracy scales with size, and
the coordinate-as-text trick is exactly the failure mode GUI-Actor's paper attacks: weak
spatial-semantic alignment, ambiguous supervision, granularity mismatch [HC].

**C. Coordinate-free attention grounding + verifier** — `microsoft/GUI-Actor` (MIT) [DEEP],
`YXB-NKU/SE-GUI` [DEEP]. An action-attention head reads the vision tokens and emits *multiple
candidate regions* in one pass (no coordinate tokens at all); a separate **grounding verifier**
module (standalone `verifier/` dir in GUI-Actor — pluggable into other grounders) scores and
selects. SE-GUI reaches 47.2 (7B) trained on **3K samples** — attention supervision is radically
more data-efficient than coordinate SFT.

**D. Zoom-in cascade (procedure, model-agnostic)** — `sjz5202/GUI-AIMA` (Apache-2.0) [DEEP],
`tiangeluo/RegionFocus` [LIGHT], `KDEGroup/UI-AGILE` (MIT) [DEEP]. Pass 1: coarse point on the
full screenshot. Pass 2: crop ~the region around it, upscale, re-ground inside the crop, project
the point back to full-screen coordinates. GUI-AIMA-3B: 53.8 → **61.5**. UI-AGILE's variant:
decompose → ground → VLM *selection* among candidates; their published timing for the full
SS-Pro set: 30 min baseline vs 35+4 min with decomposition+selection (~1.1 s → ~1.5 s/item) [HC].

**E. Patch/token pruning** — `showlab/ShowUI` (2B) [RAW], `showlab/FocusUI` (3B) [LIGHT].
UI-guided token selection drops background patches *before* the LLM (ShowUI: a 1296-patch
screenshot keeps only UI-relevant patches) → fewer vision tokens, lower latency, and a natural
privacy boundary (background content literally never enters the model).

**F. Classic CV screen parsing (no neural net)** — `MulongXie/UIED` [RAW]. Gradient/contour-based
element detection + OCR (EAST/Google OCR), exports elements as JSON. Zero GPU, zero weights,
works on design mockups and hand-drawn UIs where VLMs have no training distribution. Dated
accuracy, unbeatable cost: 0 MB VRAM.

**Also-rans worth naming:** `Anionex/agent-vision-toolkit` (MIT) [RAW] — pragmatic SoM/grid/crop
tool wrappers so *text-only* LLM agents get eyes; `ReScienceLab/LightGUIAgent` (Apache) [LIGHT] —
**grid-overlay grounding**: draw a labeled grid, let a general VLM name the cell, refine inside
it — zero training, works with any cloud VLM; `TIMBOTGPT/screen-vision-mcp` (MIT) [LIGHT] — the
v2-shaped idea already exists as an MCP server on macOS (screenshot + OCR + find-text→coords +
click); `groundingpi/GroundingPI` [LIGHT] — 4B, robotics-leaning visual-primitives grounder;
`UCSB-AI/Screen-Point-and-Read` (MIT) [LIGHT] — the *reverse* task: point → hierarchical layout
description (screen reading for verification); `GML-MMGroup/SAGE` [RAW] — agent benchmark whose
occlusion finding matters: **pairing a target's unobstructed "identity" crop with the live view
beats any single keyframe** — verify-before-click evidence; `HeimingX/TAG` [LIGHT] —
training-free grounding-assist for web agents (Mind2Web element accuracy).

---

## 3. VRAM REALITY — RTX 2060 6 GB (owner's card; brain + whisper already live there)

Derived = params × bytes (fp16≈2 B, INT8≈1 B, INT4≈0.5 B) + ~0.5–1 GB runtime [derived].
**The hard constraint:** v2's Ollama brain (Qwen2.5-7B Q4 ≈ 5.2 GB with 4K ctx, per Team 12)
plus faster-whisper already fill the card. A local grounder must **share via load-on-demand
swap** (grounding model loads for the PC-control turn, brain falls back to cloud keys or
reloads) — nothing below "coexists" fits *alongside* the brain.

| Candidate | VRAM | Verdict on 6 GB |
|---|---|---|
| OmniParser stack (YOLO + Florence caption) | ~2 GB | ✅ FITS, coexists best; CPU-viable too |
| UIED (classic CV) | 0 GB | ✅ FITS (CPU only) |
| ShowUI-2B / UGround-V1-2B (INT8) | ~2.5 GB | ✅ swap-in |
| GUI-AIMA-3B / SE-GUI-3B / GUI-Actor-3B / ZonUI-3B / FocusUI-3B (INT8) | ~3.5 GB | ✅ swap-in — **best accuracy-per-GB (GUI-AIMA)** |
| NVIDIA LocateAnything-3B | ~6 GB fp16 / ~3.5 GB INT8 | ⚠️ INT8 only; **weights non-commercial** |
| UI-TARS-1.5-7B / GUI-Actor-7B / UI-Ins-7B / AGUVIS-7B / OS-Atlas-4B | INT4 only ~4–4.5 GB | ⚠️ borderline swap-in |
| CogAgent-9B | INT4 ~5.5 GB | ⚠️ dated, skip |
| Aria-UI (25B MoE total, 3.9B active) | ~13 GB INT4 | ❌ weights don't fit, MoE saves compute not memory |
| 32B / 72B anything | — | ❌ cloud only |

---

## 4. COORDINATE EMISSION & VALIDATION — what the code actually does

- **Emission:** 0–1000 relative ints (Qwen-VL lineage: UI-TARS, UGround, GUI-AIMA, SE-GUI),
  0–1 ratios (OmniParser lists), or candidate *regions* + point sampling (GUI-Actor/SE-GUI
  attention). Nobody emits raw pixels — resolution independence is universal [VC across clones].
- **Validation in the wild is thin:** most repos clamp/normalize and trust the point. The
  exceptions are the pattern to steal: GUI-Actor's **verifier re-rank**, UI-AGILE's
  **VLM selection among candidates**, ShowUI's **iterative refinement**, GUI-AIMA's **second
  zoomed look**. I.e., the field's answer to "how do you know the point is right?" is
  *look again, closer, and ask a judge* — never a formula.
- **Failure honesty:** SS-Pro's best is ~62%. On professional high-res screens, **~4 in 10
  first-look groundings are still wrong** — any v2 vision path without a verify step will
  mis-click at that rate. This is the single most important number in this report.

---

## 5. TOP 5 MECHANISMS (steal-ranked for v2)

1. **Zoom-in cascade** (GUI-AIMA / RegionFocus / UI-AGILE) — coarse → crop → re-ground → project
   back. Model-agnostic, ~40 lines of orchestration, +8 pts on a 3B. Works today with v2's
   existing cloud Qwen-VL keys; works tomorrow with a local 3B.
2. **Parse-then-pick element list** (OmniParser) — detector+OCR+captioner turn pixels into a
   UIA-tree-shaped list; the brain picks an ID. Same doctrine as v2's UIA-first design, for the
   screens UIA can't see (games, canvas, remote desktop).
3. **Verifier gate** (GUI-Actor) — crop the grounded region, ask "is this `<target>`?",
   re-ground once on "no", fail honestly on second "no". Deletes the mis-click class.
4. **Patch pruning before the model** (ShowUI/FocusUI) — send UI regions, not wallpaper:
   latency, cost, and privacy win in one move; also the right pre-step before any *cloud*
   vision call (DCL-friendly: fewer pixels leave the machine).
5. **Paired-evidence anchoring** (SAGE) — keep an unobstructed reference crop of the target
   (from before it was covered/scrolled) and ground against the pair. Occlusion is the silent
   killer of screen agents; this is the only mechanism in the scan that addresses it directly.
   (Honorable mention: LightGUIAgent's labeled-grid overlay — the zero-weights fallback when
   only a general VLM is available.)

## 6. TOP 3 STEALS FOR JARVIS v2

1. **`pc.ground` zoom cascade in `pc_control.py`** — wrap whatever grounder is configured
   (cloud Qwen2.5-VL today; local GUI-AIMA-3B INT8 later) in: full-screen ground → 3–4× crop
   around the point → re-ground → project back → **verifier crop check** before the click is
   even proposed to the gate. Pure stdlib orchestration around the existing RAM-only
   screenshot path. Expected effect (from GUI-AIMA's published delta): the difference between
   a coin-flip clicker and a usable one.
2. **OmniParser as the vision fallback's front-end (MIT-clean config only)** — `icon_detect_v3`
   (MIT YOLOv9) + Florence caption (MIT), ~2 GB, load-on-demand. Its output *is* a tree-like
   element list, so `pc_control` can present vision results in the same shape as UIA results —
   one downstream path, two eyes. **License discipline: v3 weights only; the older AGPL
   detectors must never ship.**
3. **Load-on-demand grounder slot with an INT8 3B** — formalize what Team 12 found for the
   brain: one 6 GB card = a *schedule*, not a zoo. GUI-AIMA-3B INT8 (~3.5 GB) as the local
   grounder, loaded only for vision-fallback turns; brain stays on cloud keys during those
   turns (or reloads after). Pairs with steal #1's cascade for the 61.5%-class result.

## 7. LICENSE LEDGER (code ≠ weights — checked per repo)

- **Clean (MIT/Apache code):** GUI-Actor MIT · GUI-AIMA Apache · OS-Atlas Apache · UI-AGILE MIT ·
  ScreenSpot-Pro MIT · Screen-Point-and-Read MIT · LightGUIAgent Apache · screen-vision-mcp MIT ·
  agent-vision-toolkit MIT · CogAgent code Apache (weights: GLM terms) · UI-RFT Apache.
- **OmniParser:** repo CC-BY-4.0; v3 detector MIT; **v1/v1.5 detectors AGPL**; captions MIT.
- **No LICENSE file found → ideas only:** SE-GUI, ZonUI-3B, Aria-UI (code), UIED, FocusUI, AGUVIS,
  RegionFocus, DiMo-GUI.
- **Weights traps:** LocateAnything-3B = NVIDIA **non-commercial**; Aria-UI weights ~25B under
  their model terms; Qwen-derived grounders inherit Qwen license terms per model card — verify
  the exact card before shipping any weights in the v2 repo.

## 8. HONEST GAPS

- SeeClick, microsoft/florence, OSWorld-G never cloned (repo size vs throttled link, 3 methods
  tried). SeeClick facts (Qwen-VL-9.6B, points-only, 2024-era) are [MC]; Florence-2's role is
  verified from inside OmniParser's code instead [VC].
- Latency: only UI-AGILE publishes end-to-end timing (~1.1 s/item baseline). All other latency
  figures would be inventions; the honest summary is *detector pipelines ≈ 1–3 s/shot,
  single VLM call ≈ one LLM round-trip* [MC].
- Every accuracy number above is the *repo's own claim* on SS-Pro; cross-paper tables
  (GUI-Actor's) corroborate the ordering but not every digit.
