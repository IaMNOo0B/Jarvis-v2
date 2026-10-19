# Domain T — Multimodal Intelligence: Learning Notes

*JARVIS master curriculum. Researched 2026-10-19. LEARNING ONLY — no implementation.*
*Skip-if-learned applied: UIA-tree-first north star and OpenGCUA AX-tree patterns already live in DECISION-PLAYBOOK.md / opengcua-deep-dive.md — not re-studied, only connected. Genuine gaps researched below.*

---

## T1. Screenshot Understanding — what VLMs can/can't reliably do

**Purpose:** Let JARVIS "see" the screen when the accessibility tree is insufficient — verify state, read unlabeled regions, answer "is this the right page?"

**How it works internally:** A vision-language model encodes the screenshot into patch embeddings (ViT-style encoder, e.g. 28×28 or 32×32 px patches) concatenated with text tokens; the LLM attends over them jointly. Coordinates are emitted as text tokens in a normalized range (0–1000).

**What they CAN do reliably (measured):**
- Describe screen state and UI layout in natural language
- Read visible text (OCR-quality reading, especially large UI text)
- Answer questions about what's on screen (VQA)
- Classify UI type / identify the active application

**What they CAN'T do reliably (measured):**
- **Output precise click coordinates.** GPT-4o: 18.8% avg on ScreenSpot-v2, **0.9%** on ScreenSpot-Pro (high-res professional apps). Even specialist grounding models top out at 18.9% on ScreenSpot-Pro. General-purpose VLMs are not pointing devices — this is the single most important fact in this file.
- Small icon/toolbars without text labels (icons consistently ~20–30 pts worse than text across all models)
- Dense professional UIs (CAD, IDEs, spreadsheets): target regions are ~0.07% of the screen; models drown

**JARVIS application:** Screenshots are a *verification and fallback* sensor, never the primary control channel. Use for: post-action verification ("did the dialog open?"), canvas regions the tree can't see, and the proactive screen-watcher's "does he look stuck?" judgment (semantic, not coordinate).

**Best models:** Qwen2.5-VL-7B (best open general VLM on grounding: 85.4–86.5% ScreenSpot-v2 — general VLMs caught up to specialists); local 2–3B variants for the 2060.

**Sources:** ScreenSpot-Pro paper (arXiv 2504.07981); OS-Atlas paper (arXiv 2410.23218); UGround ICLR 2025 (proceedings.iclr.cc).

**Limitations/trade-offs:** Coordinate hallucination is the failure mode — the model confidently emits a wrong point. Mitigation: never trust a single coordinate; use tree bounds when available, crop-then-verify, or click-then-verify-loop.

**Privacy:** A screenshot is the most information-dense, most sensitive artifact JARVIS can capture — passwords, messages, banking, medical. Local-only processing; RAM-only, never disk (Phase 6 precedent); explicit opt-in.

**Common failure modes:** Resolution mismatch (model trained at 1280px, screen is 4K); DPI scaling shifting apparent positions; animated/transient UI (tooltips, hover states) captured mid-frame; dark mode vs light mode distribution shift.

**Confidence:** [HC] 85–90% on the "VLMs can't point reliably" claim — replicated across 4+ independent benchmarks.

**Unknown:** Whether coordinate-free grounding (Microsoft's GUI-Actor, patch-attention, MIT) beats text-coordinate models in production; untested by us.

---

## T2. Visual Grounding — "click the blue button" → (x, y)

**Purpose:** The last-resort actuator: when the UIA tree has no element for what JARVIS needs, a grounding model maps a referring expression to screen coordinates.

**How it works internally:** Screenshot in → vision encoder → LLM head emits `<point>[[x, y]]</point>` or `<box>` in 0–1000 normalized space (OS-Atlas uses special tokens). Trained on millions of (screenshot, expression, coordinate) triples, much of it synthetically generated from web DOMs (render page → harvest element bounds → generate referring expressions).

**The models (ScreenSpot-v2 avg / ScreenSpot-Pro avg):**

| Model | Size | SS-v2 avg | SS-Pro avg | Notes |
|---|---|---|---|---|
| Aguvis-7B | 7B | 87.3 | — | best SS-v2 |
| Qwen2.5-VL-7B | 7B | 85.4–86.5 | — | general VLM, no specialist training |
| OS-Atlas-7B | 7B | 84.1 (desktop text 90.7, icon 63.6) | **18.9** (best) | 13M-element corpus, InternVL-2 base |
| ShowUI-2B | 2B | 77.3 | 7.7 | tiny, edge-deployable |
| UGround-7B | 7B | 76.3 | 16.5 | 10M elements / 1.3M screenshots; zero desktop training yet generalizes to desktop |
| GPT-4o (planner+grounder) | — | 18.8–20.1 | 0.9 | do not use for pointing |

**Key technique — 2-step zoom-in:** crop a candidate region, re-ground inside it. GUI-AIMA-3B: 49.8% → 59.6% on ScreenSpot-Pro. This is the highest-ROI trick in the field: coarse pass on full screen, fine pass on crop.

**JARVIS application:** Grounding is the fallback actuator in the tree→OCR→screenshot ladder (T4). Planner (local 7–9B or cloud) generates the referring expression; the grounder resolves coordinates; action executes; tree/screenshot verifies. Never ground from a stale screenshot — re-capture after every action.

**Best libraries:** OS-Atlas weights (HuggingFace `OS-Copilot/OS-Atlas-Base-7B`), ShowUI-2B for the 2060, FiftyOne's OS-Atlas plugin for experimentation. **Licenses: reported Apache-2.0 for OS-Atlas/ShowUI and open for UGround — VERIFY the `license:` field on the exact pinned checkpoint before vendoring** (per index license posture).

**Hardware math (RTX 2060, 6GB):** 7B BF16 needs ~14–16GB VRAM — does NOT fit alongside the brain. Options: (a) ShowUI-2B Q4 (~1.5–2GB, fits), (b) 7B Q4 with partial CPU offload (~5GB, slow ~2–5s/click), (c) swap brain out during grounding (complex). **Recommendation: ShowUI-2B-class grounder resident, 7B only via cloud fallback.** Latency: one forward pass, ~0.5–1s for 2B on 2060, ~2–4s for offloaded 7B.

**Limitations/trade-offs:** Icons ≪ text (30-pt gap persists everywhere); professional high-res apps defeat all current models (<20%); coordinate output is a guess with no uncertainty signal (except GUI-Actor's multi-candidate regions — promising, untested).

**Privacy:** Same as T1 — grounding requires a full screenshot. Local model = pixels never leave the machine. Cloud grounding (never the default) would exfiltrate the screen per click.

**Common failure modes:** Stale screenshots (UI changed between capture and click — the #1 real-world killer); multiple identical buttons ("click OK" with 3 dialogs open); resolution/DPI mismatch vs training; referring-expression ambiguity the planner didn't resolve.

**Confidence:** [HC] 85% on benchmark numbers (multiple independent papers agree); [MC] 70% on local latency estimates (derived from VRAM math, not measured on the 2060).

**Unknown:** Real-world task success rate (benchmarks ≠ clicking through a live Windows session); whether 2B models hold up on Hindi/Hinglish UI text.

---

## T3. OCR — Tesseract vs EasyOCR vs PaddleOCR vs vision-LLM

**Purpose:** Extract text from screen regions where the UIA tree has no labels — the middle rung of the tree→OCR→screenshot ladder.

**How it works internally:** (1) Text detection (find boxes), (2) recognition (read characters in each box), (3) ordering. Tesseract: LSTM line recognizer, 1990s architecture modernized. EasyOCR/PaddleOCR: CNN/RNN detectors + attention recognizers, GPU-friendly.

**Measured trade-offs (2025 benchmarks, anyformat.ai + pdf.ai survey):**

| Engine | Accuracy (survey) | Receipt CER (lower=better) | Speed | Size | Rotation 15° | 50 DPI |
|---|---|---|---|---|---|---|
| PaddleOCR | best on receipts (67.3%) | **0.2045** | 1–5s | ~800MB | **1.000** | 0.957 |
| EasyOCR | 92.8% | 0.2833 | 1–5s | ~800MB | 0.223 | 0.245 |
| Tesseract | 78.9% | 0.3347 | **0.1–0.3s** | **36MB** | 0.000 | 0.505 |
| GPT-4o-mini (vision) | char-acc 0.6994 | — | API latency | cloud | n/a | n/a |

All three score **0.489 on two-column layout** — none preserves reading order across columns, and **none returns table structure** (that's T5's job).

**JARVIS application:** OCR the *cropped window/region*, not the full screen (speed + accuracy). Ladder: Tesseract for clean UI text (fast, tiny — good default for 2060 CPU); PaddleOCR when Tesseract fails (rotated/scaled/noisy); vision-LLM only when layout semantics matter ("which label is next to this checkbox?"). New option: **Qwen2-VL-OCR-2B-Instruct in GGUF** — runs in llama.cpp on the 2060, no cloud, OCR-specialized (Oct 2026 release).

**Licenses:** Tesseract Apache-2.0, EasyOCR Apache-2.0, PaddleOCR Apache-2.0 — all borrowable.

**Limitations/trade-offs:** Tesseract needs ~300 DPI-equivalent and upright text (screenshots are ~96–144 DPI — upscale 2× before feeding it); EasyOCR scrambles reading order on noisy lines; PaddleOCR is the most robust but heaviest; vision-LLM OCR is the most "understanding" but worst raw accuracy per dollar.

**Privacy:** All three run locally — OCR is the privacy-safe text extraction path. Prefer it over sending regions to a cloud VLM.

**Common failure modes:** Small UI fonts (upscale first); text over busy backgrounds; ligatures in Hindi/Devanagari (test EasyOCR's Hindi model specifically); assuming OCR output order = reading order.

**Confidence:** [HC] 85% on the ranking (convergent across independent benchmarks); [MC] 65% on Hindi-screenshot OCR quality (no benchmark found — must test on real Hinglish UI).

**Unknown:** Whether the GGUF OCR-2B model matches PaddleOCR accuracy on real screenshots; untested.

---

## T4. The UIA-Tree-First Strategy (north star — connected, not re-studied)

Already decided in DECISION-PLAYBOOK.md (V5 staged wakeups) and validated by OpenGCUA (opengcua-deep-dive.md). This section records the *why* and the *when-pixels* boundary, which were gaps.

**Why the tree beats screenshots:**
1. **Exactness:** the tree gives names, roles, and pixel bounds straight from the OS — no guessing, no hallucination, DPI-independent.
2. **Cost:** a tree walk is ~0 tokens and milliseconds; a screenshot is ~1,500–2,700 tokens and dollars (T6).
3. **Actionability:** tree elements are directly clickable/invocable (InvokePattern); screenshot coordinates need a grounding model (T2) with <90% reliability.
4. **Stability:** names persist across theme/resolution changes; pixels don't.

**The order that works** (Auten/dev.to, field-validated): **1. Tree first** → 2. OCR text (T3) when the tree has no labels → 3. Screenshot (T1/T2) for canvases/icons/"right page?" checks → **4. Verify after acting** (re-read tree/text; never assume the click worked).

**When pixels are TRULY needed:** canvas-rendered content (games, CAD viewports, video); custom-drawn UIs exposing empty trees (legacy Win32/Delphi/SAP/Citrix — the tree shows one opaque pane); icon-only toolbars with no accessible names; visual verification of state the tree doesn't expose (is the chart rendered? is the video playing?).

**How to read the tree in Python:** `pywinauto` (BSD, `backend='uia'`), raw `uiautomation` package, or .NET's FlaUI via pythonnet. Explore with `Inspect.exe` (Windows SDK) or Accessibility Insights. Filter to actionable elements only — full desktop tree walks are slow.

**OpenGCUA's design rules (adopt):** AX-tree and visual observation are **separate namespaces** that can never be confused; element indices are valid **only relative to the last delivered observation** (kills stale-reference bugs); reject references to changed screens, don't guess.

**Windows adapter gap:** OpenGCUA v0.1 has no Windows driver (roadmap v1.0). The UIA driver port is the highest-value PC-control work for v2 — flagged in MEMORY.md, unchanged.

**Confidence:** [HC] 90% — tree-first is the field consensus (UFO, OpenGCUA, Auten, all RPA vendors).

**Unknown:** Latency of full-tree walks on Owais's machine for heavy apps (Chrome with 50 tabs); needs measurement.

---

## T5. Document Understanding — table extraction, layout-aware parsing

**Purpose:** When Owais says "read this PDF/report," JARVIS must reconstruct paragraphs, tables, and reading order — a PDF stores ink positions, not structure.

**How it works internally:** Every pipeline = **layout analysis** (what's a heading/table/figure) + **table structure recognition** (rows/columns/cells, colspan/rowspan) + **OCR** (T3) + **reading-order stitching**. Two architectures: *pipeline tools* (separate models per stage) and *expert VLMs* (one model end-to-end, e.g. MinerU2.5-1.2B, dots.ocr).

**OmniDocBench 2025 (the authoritative benchmark) — English:**
- **MinerU**: best pipeline tool — TableTEDS 78.6, overall edit distance 0.15 (lower=better)
- **PPStruct-V3** (PaddleOCR's): overall 0.145 — edges out MinerU
- **Docling** (IBM, MIT): TableTEDS 61.3 — collapses nested table headers; strong docs/ecosystem, weaker tables
- **Marker** (Surya-based): TableTEDS 67.6
- **Mistral OCR** (API): TableTEDS 75.8 — best API option
- **Kreuzberg** (Rust): ~2.8× faster than Docling at equal F1 — the speed pick

**JARVIS application:** "Read this report and summarize table 3" → MinerU or Docling → markdown with real tables → brain. For scanned/image PDFs, the OCR stage is mandatory (pymupdf4llm returns ~nothing on image-only PDFs). Table-heavy docs → MinerU; general docs where ecosystem matters → Docling.

**Licenses:** Docling MIT (borrowable); MinerU reported open-source — VERIFY before vendoring; Kreuzberg check license.

**Limitations/trade-offs:** No pipeline fully succeeds — the question is what its failures look like (Brosse). Nested headers, multi-page tables, and footnotes break all of them to varying degrees. Scanned PDFs need the full OCR path (slower).

**Privacy:** Local parsing (MinerU/Docling) keeps documents on-machine. API options (Mistral OCR, LlamaParse) exfiltrate document contents — default to local; API only with explicit consent per document.

**Common failure modes:** Assuming text order = reading order (two-column papers); tables returned as text soup (Tesseract-class tools); image-only PDFs with no OCR stage returning empty.

**Confidence:** [HC] 85% on the ranking (OmniDocBench is multi-paper convergent).

**Unknown:** Hindi/Devanagari document parsing quality; untested.

---

## T6. Cost/Latency Math — vision tokens are expensive

**Purpose:** Every screenshot sent to a cloud model costs real money, every turn. This section is the budget.

**Token counts for one 1920×1080 screenshot (measured/formula, Oct 2026):**
- Anthropic (high tier): ~2,691 tokens · (standard): ~1,560
- OpenAI (current patch models): ~2,448 · (gpt-4o tile formula): 85 + 170/tile
- Gemini: ~1,548 (6 tiles × 258)
- Qwen: ~2,040 (+2)

**Money math (gpt-4o @ $2.50/1M input):** one 1080p screenshot ≈ **$0.005–0.007**. A computer-use agent taking a screenshot per step, 30 steps/task, 10 tasks/day = **$15–20/day**. The proactive screen-watcher at 1 shot/min × 16h = 960/day ≈ **$5/day for eyes alone** — financially insane on cloud vision.

**The 25× markup:** the same document-as-image (~765 tokens) vs as extracted text (~30 tokens). **Text-first isn't just accuracy — it's the cost strategy.** Every rung down the tree→OCR→screenshot ladder (T4) is ~10–25× cheaper.

**Minimization strategies (in priority order):**
1. **Tree-first gating (T4):** no vision call at all when the tree answers — infinite savings.
2. **Region crops:** send the dialog (400×300), not the desktop (1920×1080) — token count scales with area.
3. **Downscale to tile boundaries:** 1280×720 → 4 tiles (765 tok); 1024×768 → 2 tiles (425 tok) — 44% off, zero quality loss for UI purposes.
4. **Low-detail mode:** flat 85 tokens when only a rough sense is needed ("is an error dialog open?").
5. **Staged:** low-res first, high-res only if the cheap pass is inconclusive.
6. **Local VLM:** Qwen2.5-VL-2B/3B on the 2060 = $0 marginal cost; the screen-watcher and grounding loop should be local-first by default.
7. **Don't re-send:** "every screenshot you paste is billed again on every turn" — keep images out of the rolling conversation history; re-capture fresh when needed.

**Latency:** cloud vision round-trip ~1–3s per screenshot (network-bound); local 2B VLM ~0.5–1s on 2060; tree walk milliseconds; Tesseract ~0.1–0.3s CPU. A tree-first step is ~100× faster than a cloud-vision step.

**JARVIS policy (proposed):** cloud vision is a **budgeted, gated resource** — per-task vision budget, tree/OCR must fail first, all screen pixels stay local by default (R13 privacy-safe defaults).

**Confidence:** [HC] 90% on token formulas (provider docs + independent verification); [HC] on the 25× text-vs-image markup.

**Unknown:** Exact 2060 inference latency for Qwen2.5-VL-3B / ShowUI-2B — must benchmark on the card, not derive.

---

## Cross-topic connections

- **T4 → T6:** tree-first is simultaneously the accuracy strategy AND the cost strategy — one decision, two wins.
- **T2 → T1:** grounding models are specialists because general VLMs can't point (0.9% on ScreenSpot-Pro); don't ask the brain to do the grounder's job.
- **T3 → T5:** document parsing reuses the OCR ladder; a better OCR stage lifts every pipeline.
- **T1/T2 → Security (SEC4):** screenshots are untrusted content — a malicious webpage rendered on screen is indirect prompt injection via pixels. REA markers apply to vision inputs too.
- **T6 → Voice pipeline:** the same "cheap stages reject cheaply" doctrine (V7 staged wakeups) applies to vision: tree (free) → OCR (cheap) → local VLM (moderate) → cloud (expensive).

## Remaining gaps (for future missions)

1. Measured 2060 latencies for ShowUI-2B, Qwen2.5-VL-3B, Tesseract, PaddleOCR on real screenshots
2. Hindi/Devanagari OCR + grounding quality on Hinglish UI
3. GUI-Actor (Microsoft, MIT) coordinate-free grounding — evaluate when mature
4. Windows UIA tree-walk latency on heavy apps (Chrome 50 tabs)
5. License verification on pinned checkpoints: OS-Atlas, UGround, MinerU, Kreuzberg

*End of notes.*
