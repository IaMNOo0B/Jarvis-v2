# MEGA-SCAN TEAM 17 — Indic & Hinglish Language Tech

*Mission: reverse-engineer the Hindi/Indic speech + code-mix ecosystem for JARVIS v2's #1 requirement — understand and speak Hinglish. Method: `git clone --depth 1` into `.work17/` (26 clones landed; GitHub's unauth path throttled mid-mission, the rest verified via Hugging Face API + model cards). 2026-10-20.*

**Depth grading (honesty):** DEEP = README + code/config + model card read · READ = README + key files · TRIAGE = metadata/README skim, claims unverified. WER numbers are **[MC] self-reported** unless a paper/benchmark is named — every Indic vendor benchmarks on different data/scripts, so cross-vendor WER comparisons are indicative, never exact.

---

## VERDICT BOX (the two paths v2 should take)

### Best Hinglish STT path — TWO-STAGE, script-split
1. **Conversational Hinglish → Oriserve `Whisper-Hindi2Hinglish` (Apache-2.0).** The only open model family trained *for* roman-script Hinglish output: on Oriserve's eval, Prime WER **32.4 / 28.7 / 60.8** (CommonVoice / FLEURS / IndicVoices) vs stock Whisper-Large-v3's **61.9 / 50.8 / 82.6** on the same roman references. Roman output is the right call for v2 — it's what the owner types, what the LLM reads best, and Sarvam's commercial Saaras v4 independently ships a `translit` mode for the same reason.
   - **Swift (0.29 GB)** — small-class, websocket-streaming server ships in the repo (webrtcvad-3 endpointing). The always-on conversational tier. **REAL-TIME on 6GB: YES, trivially (runs on CPU too).**
   - **Prime (6.17 GB files ≈ whisper-large class)** — the accuracy tier for dictation/long-form; as CT2 int8 ≈ 1.6 GB VRAM. Load-on-demand, not resident beside the 7B brain.
2. **Clean/read Hindi (Devanagari) → AI4Bharat IndicConformer Hindi (MIT, 120M).** Hybrid CTC+RNNT Conformer-L, NeMo + ONNX (sherpa-onnx) exports. Published Vistaar/IndicVoices results put IndicConformer-family Hindi WER in the low-to-mid teens on read speech [HC — AI4Bharat papers/benchmarks; Devanagari basis, not comparable to roman WERs above]. ~240 MB fp16 / ~150 MB int8 — **real-time anywhere, even CPU**. This is the accuracy anchor for pure-Hindi input and the fallback when Whisper hallucinates.
3. **Normalization layer between STT and brain:** IndicXlit (11M, MIT) roman↔Devanagari both directions + spelling-variant canonicalization (the `krdo / kar do / kardo` problem from our own Hinglish study) so downstream intent matching sees one canonical form.

### Best Hindi/Hinglish TTS path
1. **Resident voice → Kokoro-82M Hindi voices `hf_alpha/hf_beta` (F) / `hm_omega/hm_psi` (M), Apache-2.0.** 82M params, 4 real Hindi voices, already in v2's TTS ladder family. CPU-real-time, zero VRAM pressure. Weakness: espeak-ng phonemizer flattens some Hindi phonemes — acceptable for short replies.
2. **Offline floor → Piper `hi_IN` voices (pratham / priyamvada / rohan, medium ONNX ~60 MB).** v2's existing Piper fallback gains Hindi with a voice-file drop, nothing else.
3. **Quality mode → AI4Bharat IndicF5 (MIT, ~335M, 1.41 GB)** — zero-shot voice cloning from a 3–10 s reference clip, 1,417 h training (Rasa/IndicVoices-R/IndicTTS/LIMMITS), 11 languages. This is how JARVIS gets ONE consistent Hindi voice (clone a licensed reference once). Fits 6GB in fp16 (~0.8 GB) — but **not simultaneously with the resident 7B brain**; load-on-demand or CPU.
4. **Expression control → Indic Parler-TTS (Apache-2.0, Parler-Mini ~880M, 1,806 h, 21 langs)** — natural-language voice direction ("calm, slow, warm male voice") is the closest open match to JARVIS's directed-butler persona in Hindi. 3.75 GB files; quality-mode only on 6GB.
5. Watch-list: **Bodhan Indic-Speak** (Llama-3.2-3B-based LLM-TTS, explicitly code-switching-tagged, 22 langs) — but gated + custom license + 7.33 GB. Not adoptable today.

### 6GB VRAM budget (alongside qwen2.5:7b-Q4_K_M ≈ 5.2 GB with 4K ctx)
| Resident set | VRAM | Verdict |
|---|---|---|
| 7B brain + Oriserve Swift (CT2 int8, GPU) | ≈ 5.6 GB | Squeaks — no headroom for TTS on GPU |
| 7B brain + Swift on CPU + Kokoro on CPU | ≈ 5.2 GB | **Recommended default** — voice costs 0 VRAM |
| 7B brain + IndicConformer int8 (GPU) | ≈ 5.4 GB | Fine for Hindi-read mode |
| IndicF5 or Parler co-resident with 7B | > 6.5 GB | **Impossible** — quality TTS = load-on-demand swap |

---

## 1. ASR — Hinglish-first (the core hunt)

### 1.1 OriserveAI/Whisper-Hindi2Hinglish — DEEP · Apache-2.0 · 30★
- **What:** Whisper finetuned on a proprietary conversational Hindi+Hinglish corpus (noisy, real-world Indian audio — call-center-like), explicitly targeting **roman-script Hinglish output**, noise resistance, and hallucination suppression (their demos show stock Whisper L-v3 emitting English gibberish — "Where did they come from?" — where Prime recovers the actual Hindi sentence).
- **Code read:** `app.py` — asyncio websocket streaming server, `webrtcvad` aggressiveness 3, silence-chunk endpointing (`max_silence_chunks=10`), HF transformers pipeline loader (`utils.load_pipe`), mic + file clients streaming 10 ms chunks. Production-shaped, not a notebook.
- **Data:** proprietary (undisclosed size) — the one closed ingredient; models themselves are open (Apache-2.0 on HF).
- **Code-mix technique:** output-script decision (roman) + training distribution (natural code-switched conversation). No explicit switch-point machinery — the mix is learned.
- **Steal verdict: STEAL (top).** Swift = v2's default Hinglish STT; Prime = dictation tier via faster-whisper/CT2 conversion (CT2 conversions of Oriserve models circulate; verify before shipping). Their VAD/endpointing constants are a sane starting point for v2's energy VAD tuning.

### 1.2 vineetdev/optuna-tuned-hinglish-asr — DEEP · MIT · 3★
- **What:** Whisper-medium + LoRA with an **Optuna (TPE + MedianPruner) hyperparameter search** — the most *reproducible recipe* in the scan.
- **Recipe (code-verified in README/configs):** encoder FROZEN (~307M), LoRA only on decoder `q_proj/v_proj/fc1/fc2`, ~3.19% trainable (25M), lr ≈ 7.37e-5 cosine-restarts, eff. batch 4, 1,000 steps on 10k samples.
- **Data:** HF `ujs-hinglish-compressed` — ~52k train / ~3k test of Hinglish *technical tutorials* (LibreOffice/Linux walkthroughs — Hindi matrix + English tech terms, mixed scripts). Closest public corpus to "owner gives PC commands in Hinglish."
- **Numbers [MC, 100-sample eval]:** WER 70.62 → **36.46** (CER 54.9 → 30.9); beat Gemini-2.5-Flash ASR (60.67) and Sarvam SARA v3 (44.35) *on this domain set*.
- **Steal verdict: STEAL the recipe + dataset pointer.** If v2 ever trains its own adapter on the owner's golden set, this is the template (decoder-only LoRA + Optuna, single GPU, hours not days).

### 1.3 modelpath-dev/whisper-finetune — READ · MIT · 0★
Clean, typed, tested LoRA pipeline for whisper-small on Common Voice 17 Hindi (`whisper_hi` package, YAML config as single source of truth, baseline-vs-tuned WER harness, Colab-T4-sized). No published final WER in README. **Steal:** engineering template if §1.2's recipe is productized — this repo's code hygiene is the bar.

### 1.4 11levate-up/Whisper-hinglish-finetune — READ · MIT · 0★
Whisper-small finetune on HF `addyo07/noisy-hinglish-asr` — **28,681 clips / 36.6 h, Apache-2.0, pre-labeled hi / en / hinglish / silence-noise with ready splits**. Results section still empty ("Wait"). **Steal: the dataset** — the label taxonomy (an explicit `hinglish` class + noise class) is exactly what a code-switch-aware VAD/router needs for training data.

### 1.5 Ayushverma135/Whisper-Hindi-ASR-model-IIT-Bombay-Internship — TRIAGE+ · EPL-2.0 · 7★
Student internship build: Whisper evaluated on Kathbath Hindi + Gramvaani eval set (links AI4Bharat/vistaar). Notebook-grade. Value: confirms the Kathbath→Whisper eval path everyone uses. No steal.

### 1.6 Syzygianinfern0/Hindi-ASR-Challenge — READ · IIT Madras Speech Lab
Official challenge repo (Kaldi + PyTorch tracks): 40 h train / 5 h dev / 5 h test of *read newspaper Hindi* (politics/sports/entertainment), MeitY NLTM-funded. Clean read-speech Hindi — the "studio bias" distribution that Vividh-ASR (below) proved fails in the wild. **Steal:** eval data pointer only.

### 1.7 algorithnicmind/multilingual-indic-asr — TRIAGE · MIT · 2★
From-scratch CNN+BiLSTM MFCC ASR for en/hi/or with n-gram LMs. Educational; orders of magnitude below transfer-learned models. No steal — cited as evidence the from-scratch path is dead for v2.

---

## 2. ASR — Indic flagships (HF-verified)

### 2.1 AI4Bharat IndicConformer (Hindi) — DEEP (card) · MIT · NeMo
`ai4bharat/indicconformer_stt_hi_hybrid_ctc_rnnt_large` — Conformer-L encoder, **120M params, 17 blocks, d=512**, hybrid CTC+RNNT decoders (switchable at inference: CTC for speed, RNNT for accuracy), 16 kHz mono in, Devanagari out. 1.57 GB HF storage (both decoders, fp32); ONNX exports run in sherpa-onnx. Trained on Vistaar-ecosystem data (IndicVoices/Shrutilipi/Kathbath lineage — 150 h Kathbath Hindi alone inside IndicSUPERB). The 2026 "Voice of India" real-world benchmark includes Indic Conformer as *the* open reference system. **REAL-TIME on 6GB: YES — it barely notices the GPU; CPU-viable.**
**Steal verdict: STEAL as the Devanagari/Hindi-read engine + hallucination cross-check** (two-engine disagreement = a cheap confidence signal for the gate).

### 2.2 AI4Bharat indic-conformer-600m-multilingual — READ (card) · MIT weights, **GATED**
600M unified conformer, 22 languages, 385k downloads — the current flagship. **Gated on HF (form + agreement)** = adoption friction against v2's zero-friction rule; the ungated per-language models (§2.1) cover Hindi today. Revisit if the owner ever does the one-time HF approval.

### 2.3 IndicWhisper / Vistaar (AI4Bharat) — verified via benchmark literature
Whisper-medium finetuned per-language on the Vistaar benchmark corpora (431+ h Hindi across 59 districts in the IndicVoices lineage). Independent white-paper table: IndicWhisper = best provider for 8 of 12 Indic languages (Bengali ~20.1, Marathi ~18.2, Urdu ~19.4 WER [MC — vendor white paper]). Repo `AI4Bharat/vistaar` (referenced by §1.5). **Steal:** superseded for Hinglish by §1.1 (IndicWhisper outputs native script) — but its *Vistaar benchmark* is the eval v2 should report Hindi numbers against.

### 2.4 Adalat AI — Vividh-ASR Hindi Whisper finetunes — READ (HF listing + HF blog)
Finetunes of Whisper small (244M) + medium (769M) for Hindi/Malayalam explicitly fixing **studio bias** (multi-stage training ending in a clean+spontaneous consolidation stage; tiered benchmark — clean read / spontaneous / noisy — instead of one global WER). Ships **CT2 (faster-whisper) conversions** (`ct2-whisper-medium-ml-rmft`, small-hi curated variants) = drop-in for v2's existing faster-whisper loader. Blog's deployment advice (tier your eval, consolidate at the end) is directly reusable for the owner's golden-set training. **Steal verdict: STEAL as the Devanagari-Whisper candidate** — benchmark Swift-vs-Vividh-small on the golden set; keep the winner.

### 2.5 vasista22/whisper-hindi-small — verified (HF) · Apache-2.0
The famous early Hindi Whisper-small finetune (Common Voice hi). Historically important, now outclassed by §1.1/§2.4. No steal.

### 2.6 Meta MMS-1B (`facebook/mms-1b-all`) + MMS-TTS — ecosystem note
1B params, 1,107 languages ASR / TTS for 1,107 (`mms-tts-hin` exists). Hindi quality is coverage-grade, not accuracy-grade (MMS optimizes breadth). **No steal for Hindi** — Indic specialists beat it on their home turf; noted so the "one giant multilingual model" hypothesis is on record as *tested and rejected*.

### 2.7 Sarvam Saaras v4 / Bulbul — API-only note
Commercial API (₹30/h ASR). Two design validations worth stealing as *ideas*: (a) first-class **`translit` output mode** (roman) beside native + translate — mirrors §1.1's verdict; (b) Vistaar + LLM-WER evaluation (semantic error vs formatting variant). Cloud-only + owner key signup → possible future cloud-fallback tier, never the local default.

---

## 3. Engines & serving (how the models actually run)

### 3.1 k2-fsa/sherpa-onnx — READ · Apache-2.0
Offline ONNX runtime (C++ core, every platform) whose model zoo carries the IndicConformer family + VITS Indic TTS + zipformer streaming ASR. For v2 this is the **no-Python-heavy-runtime path**: a single ONNX dependency serving STT (conformer) with streaming partials. **Steal: runtime candidate for §2.1** if NeMo proves too heavy on the owner's PC.

### 3.2 Vaibhavsahkk/Optimized-Speech-Recognition-System — DEEP · no license file (ideas only)
Vakyansh Wav2Vec2-Hindi (`Harveenchadha/vakyansh-wav2vec2-hindi-him-4200`, MIT, EkStep — 4,200 h Hindi training lineage) pushed through **PyTorch → ONNX → ONNX-Runtime graph opt → TensorRT FP16 → Triton**, with *numerical verification at every step* against the PyTorch baseline — all measured on an **RTX 3050 Ti 4 GB laptop**. **Steal: the optimization playbook + verification discipline** (this is exactly v2's evidence-wrapping ethos applied to inference); the EkStep model itself is legacy (Wav2Vec2 CTC, greedy decode) next to §2.1.

### 3.3 alphacep/vosk-api — TRIAGE+ · Apache-2.0
Kaldi-based; its small Hindi model (~42 MB) runs real-time on a phone-class CPU. Accuracy is a generation behind (Kaldi GMM/DNN lineage) but it is the **zero-GPU floor**: if the 2060 is busy/absent, Vosk-hi still hears Hindi. **Steal: emergency-tier only.**

### 3.4 huggingface/parler-tts — TRIAGE+ · Apache-2.0
Engine behind §4.3: decoder-only LM over Descript audio tokens, voice = natural-language description embedding. INFERENCE.md documents the streaming/chunking knobs. Read as the integration manual for Indic Parler.

### 3.5 SWivid/F5-TTS — READ · code MIT / base weights CC-BY-NC ⚠️
Flow-matching TTS, zero-shot cloning; base trained EN/ZH — Hindi arrives via finetunes (AI4Bharat's IndicF5, §4.2, is the one that matters and is MIT). **License trap flagged:** upstream F5 weights are non-commercial; IndicF5's MIT card is the adoptable artifact — verify weight provenance before any commercial use.

---

## 4. TTS — Hindi/Hinglish voices

### 4.1 hexgrad/Kokoro-82M — verified (HF files) · Apache-2.0
StyleTTS2-derived 82M; voice inventory confirmed from the repo itself: **`hf_alpha`, `hf_beta` (Hindi F), `hm_omega`, `hm_psi` (Hindi M)** among 54 voices. Misaki/espeak phonemization covers Devanagari. **Steal: DEFAULT resident Hindi voice** (see Verdict Box) — zero new architecture for v2, just voice selection by detected language (the per-utterance language-ratio voice pick our Team-1 scan already flagged).

### 4.2 AI4Bharat IndicF5 — DEEP (card) · MIT
F5 finetune: **1,417 h** (Rasa + IndicVoices-R + IndicTTS + LIMMITS), 11 languages, zero-shot cloning (ref audio + its transcript), 1.41 GB. Near-human claims are the authors' [MC]; the corpus pedigree (IndicVoices-R is a NeurIPS'24 dataset) is real. **Steal: quality-mode Hindi voice + the one-consistent-voice cloning trick.**

### 4.3 AI4Bharat Indic Parler-TTS — DEEP (card) · Apache-2.0
Parler-Mini finetune on **1,806 h**, 21 languages + English, prompt-tokenizer with byte fallback (handles script mixing gracefully), natural-language style descriptions. **Steal: persona-directed Hindi speech** ("speak slowly, warm, confident") — the only open Hindi TTS with director-style control.

### 4.4 Piper hi_IN voices — verified (HF repo files) · engine GPL-3.0 ⚠️ / voices MIT-ish (check per-voice card)
`rhasspy/piper-voices`: **hi_IN-pratham, hi_IN-priyamvada, hi_IN-rohan** (medium, VITS ONNX ~60 MB each). v2 already wraps Piper — Hindi is a file drop. Engine is GPL-3.0 (v2's posture: wrap the binary, never link code — consistent with existing practice).

### 4.5 Bodhan-AI Indic-Speak — READ (card) · custom license, GATED, 7.33 GB
Llama-3.2-3B-backbone TTS, 22 languages, **explicit code-switching/code-mixing tags** — architecturally the future (LLM-native TTS handles mid-sentence switches as tokens, not phoneme exceptions). Blocked today by gate + license + size. **Watch-list #1.**

### 4.6 gokulkarthik/text2speech — READ · ICASSP 2023 (AI4Bharat lineage)
Systematic bake-off for Indic TTS (acoustic model × vocoder × losses × schedules): winner = **monolingual FastPitch + HiFi-GAN V1, joint M/F training**; models for 13 languages shipped via Bhashini. **Steal: the recipe verdict** if v2 ever trains a house voice — don't ensemble languages into one acoustic model.

### 4.7 vivek-541/vani-tts — DEEP (honest failure study) · Apache-2.0
287.5 GPU-hours of documented failure so v2 doesn't repeat it: StyleTTS2 GAN decoder needs >12 GB VRAM (dead on 6 GB), conv-only mel predictors can't learn consonants, FastPitch learned spectra but **no temporal phoneme structure** (L1 mel loss learns frequency, not time) — HiFi-GAN vocoder was perfect throughout; pivoting to VITS. **Steal: the negative results** (kill StyleTTS2/FastPitch fine-tune ideas for the 2060 on sight).

### 4.8 ahmedHanzala/urdu-tts — TRIAGE+ · MIT
Tortoise-TTS finetuned on South-Asian accents; spoken Urdu ≈ spoken Hindi register (Hindustani) — relevant because a large share of "Hindi" speech is register-identical. Niche; no steal beyond the accent-finetune observation.

### 4.9 Raj2503/Python-Text-To-Speech-Hindi — TRIAGE · coursework
Concatenative (unit-selection) Hindi TTS, 44-phoneme stitching. Pre-neural; cited as the floor of the field. No steal.

### 4.10 myshell-ai/OpenVoice — READ · MIT (v1) 
Zero-shot tone-color cloning; official checkpoint languages do **not** include Hindi (v2: EN/ES/FR/ZH/JA/KO) — cross-lingual transfer to Hindi is demo-grade. Rejected for the Hindi path; the *cloning UX* (one ref clip) is what IndicF5 already productizes properly.

---

## 5. Code-mix text layer (between STT and brain)

### 5.1 praatibhsurana/Hinglish_Hindi_WSD (`hindiwsd`) — READ · MIT · 36★, unmaintained (py≤3.8)
Pipeline: Hinglish → Devanagari transliteration → spell correction (spello) → POS (indic_tagger) → WSD (IndoWordNet, enhanced Lesk). Dated, but its **stage order is the canonical normalization chain**: transliterate → normalize spelling → then do NLP. **Steal: the chain design** (rebuild the first two stages on §6.1; skip WSD).

### 5.2 ashishgupta1350/Hindi-English-Code-Mixed-Stemmer — TRIAGE (clone throttled; metadata only)
Unsupervised stemmer for code-mixed text. Normalization-adjacent; IndicXlit canonicalization (§6.1) covers the need better. No steal.

### 5.3 singhnivedita/SemEval2020-Task9 (SentiMix) — TRIAGE · 7★
SemEval-2020 SentiMix submission (Hinglish sentiment, token-level LID + sentiment). Value: SentiMix data + the token-level language-ID task framing — LID per token is the switch-point signal a future code-switch router needs. No code steal.

### 5.4 Datasets that matter (pointers, verified in-repo)
- `ujs-hinglish-compressed` (HF) — 52k Hinglish tech-tutorial utterances (§1.2).
- `addyo07/noisy-hinglish-asr` (HF, Apache-2.0) — 36.6 h, hi/en/hinglish/noise labels (§1.4).
- **GLUECoS / LinCE** (from our own prior study) — code-switch NLP benchmarks; still no agentic coverage — our golden set remains the only agent-task eval, reinforcing that v2 must self-benchmark.

---

## 6. Transliteration & normalization

### 6.1 AI4Bharat/IndicXlit — DEEP · MIT · 145★
Transformer (~11M params) for **21 Indic languages, both directions** (roman↔native), trained on **Aksharantar — 26M word pairs / 20 languages**. Tiny enough to run per-token on CPU inside the chat loop. **Steal verdict: STEAL (top-3).** Uses in v2: (a) canonicalize ASR roman output for intent matching, (b) convert brain's Devanagari replies for roman-preferring display, (c) normalize the owner's typed Hinglish spelling variants before memory storage (fixes the embedding-fragmentation problem our Hinglish study documented).

### 6.2 indic-transliteration/indic_transliteration_py — READ · MIT · 213★
Deterministic scheme-based transliterator (Devanagari↔ITRANS/HK/SLP1/IAST etc.) — script conversion, *not* roman-Hindi phonetic transliteration. **Steal: utility only** (script plumbing for Sanskrit/legacy schemes); IndicXlit owns the phonetic job.

### 6.3 libindic/indic-trans — TRIAGE · AGPL-3.0 ⚠️
ML transliteration from the libindic project. **Ideas only** (AGPL) and superseded by IndicXlit. No steal.

### 6.4 varnamproject/govarnam — TRIAGE · Go
Input-method engine (type roman → native script as you type, learns from usage). Desktop-IME territory, not assistant-core. No steal.

### 6.5 google-research-datasets/dakshina — TRIAGE · CC-BY-SA dataset
Dakshina: 92k Devanagari⇄Latin word pairs for Hindi within a 12-language South-Asian transliteration corpus. **Steal: eval data** for §6.1's accuracy on Hindi specifically.

---

## 7. Translation & understanding (supporting layer)

### 7.1 AI4Bharat/IndicTrans2 — READ · code MIT / data CC-BY-4.0
1B + distilled-200M seq2seq MT for 22 Indic languages (BPCC corpus), fairseq + HF artifacts, CT2 conversions exist (Adalat's `ct2-rotary-indictrans2-*`). Relevance: a *local* en⇄hi translator lets v2 normalize a Hindi turn to English for a weak local brain, or render replies in Hindi — the "translate-as-scaffold" pattern. The dist-200M (~800 MB fp16, CT2-int8 ~250 MB) is the only tier that fits beside the brain. **Steal: optional scaffold module, dist-200M CT2 only.**

### 7.2 pvanand07/BhashiniClient — READ · MIT · 6★
Thin Python client for India's **Bhashini/ULCA** government pipeline (ASR + NMT + TTS, 13–22 languages, free API key from bhashini.gov.in). Cloud-dependent and key-gated (owner signup — he has declined signups before, so this stays an *option*, not a default). **Steal: the client pattern** if a cloud Indic tier is ever added — one integration buys ASR+MT+TTS together.

### 7.3 AI4Bharat/IndicSUPERB + Kathbath — READ · benchmark
6 SLU tasks × 12 languages; Kathbath = 1,684 h labeled speech (150.2 h Hindi, 121 speakers). **Steal: benchmark + training-data provenance** — this is the yardstick family behind §2.1's credibility.

---

## 8. Blocked / failed (honest ledger)
- `coqui-ai/TTS` (XTTS-v2 has a Hindi voice) and `rhasspy/piper` engine repos — clones killed by GitHub unauth throttling mid-mission; XTTS Hindi support verified from Coqui docs knowledge + Piper voices verified on HF (§4.4). XTTS license is CPML (non-commercial) — would be ideas-only regardless.
- `AI4Bharat/Airavata` (Hindi instruction LLM) — repo not publicly clonable at that path; brain-side, out of this team's STT/TTS scope.
- `KunalDhawan/ASR-System-for-Hindi-Language`, `ashishgupta1350/...Stemmer`, `libindic/indic-trans` — clone failures (throttle); stemmer/libindic covered at TRIAGE from metadata.
- NeMo itself not cloned (multi-GB); IndicConformer read via its model card + sherpa-onnx exports instead.

---

## TOP 5 MECHANISMS (what the ecosystem actually teaches)
1. **Output-script is an architecture decision.** Roman-Hinglish ASR output (Oriserve, Sarvam's translit mode) halves effective WER for real users and feeds LLMs better than Devanagari — pick the script the *pipeline* speaks, transliterate for display.
2. **Decoder-only LoRA + frozen encoder + hyperparameter search** turns a generic Whisper into a domain Hinglish engine on one consumer GPU (70.6 → 36.5 WER) — small adapters beat big retrains.
3. **Hybrid CTC+RNNT conformer** = one model, two gears (fast CTC draft / accurate RNNT final) — the pattern for wake-tier vs dictation-tier without two models.
4. **Studio bias is the silent killer:** read-speech training data collapses on spontaneous/noisy speech; the fix is multi-stage training ending in a clean+spontaneous consolidation + *tiered* evaluation (Vividh-ASR).
5. **Normalization is a pipeline stage, not an afterthought:** transliterate → canonicalize spelling → then intent/memory. Every serious Hinglish system has this layer; v2 currently has none.

## TOP 3 STEALS FOR v2
1. **Oriserve Whisper-Hindi2Hinglish-Swift as stt.py's Hinglish engine** (Apache-2.0, 0.29 GB, streaming server code included) — with Prime (CT2-int8) as the load-on-demand dictation tier.
2. **IndicXlit (11M, MIT) as the normalization layer** between STT and brain — canonicalizes roman-Hindi spelling chaos for intent matching, memory, and display-script conversion, for ~zero runtime cost.
3. **Kokoro Hindi voices now + IndicF5 later** in tts.py: hf/hm Kokoro voices as the zero-VRAM resident Hindi voice (Piper hi_IN as the offline floor), IndicF5 cloning as quality mode for one consistent JARVIS Hindi voice.
