# Hinglish Golden Evaluation Set — Methodology Design

*PHASE INFINITY, Research Cycle 8. LEARNING ONLY — design document, no dataset built, no code executed.*
*Date: 2026-10-19. Status: methodology complete, unexecuted.*

**Research question:** How do we build a Hinglish golden evaluation set when no public benchmark covers code-switched agent tasks?

---

## 1. What makes Hinglish hard [HC, multi-source]

### 1.1 Code-switching patterns

Hinglish is not "Hindi with English words" — it is a **matrix-embedded system**: Hindi typically supplies the grammatical matrix (verb morphology, postpositions, discourse markers) while English supplies content embeddings, especially nouns, technical terms, and action verbs. A single utterance switches languages mid-sentence, mid-phrase, and sometimes mid-word (57% of urban Indian business conversations mix within the same sentence — autointerviewai.com, 2026 industry report [MC, single source, vendor-adjacent]).

Example: *"Bhai meri downloads folder saaf kar de, but important wali files ko mat chhuna"* — Hindi matrix (bhai, meri, kar de, mat chhuna), English embeddings (downloads folder, files, important).

### 1.2 Transliteration variance — the silent killer

Romanized Hindi has **no standardized orthography**. The same word appears in many spellings:
- *kar do / kardo / krdo / kardo* (do it)
- *bhai / bhaii / bhaiya* (brother)
- *nahi / nhi / nai / nahin* (no/not)

This is documented as the core differentiator making Hindi-English harder than Spanish-English code-switching (GLUECoS analysis, Khanuja et al. 2020 [VC]). Consequences:
- **Tokenization fragmentation:** `krdo` and `kar do` tokenize completely differently; subword vocabularies trained on clean text shatter romanized Hindi into meaningless pieces.
- **Embedding degradation:** the same semantic content maps to distant vectors depending on spelling. Retrieval recall on Hinglish corpora is measurably worse (open-problem #17).
- **mBERT evidence:** performs well on code-switching but **struggles with transliterated text** (educative.io summary of BERT code-switching studies [HC]).

### 1.3 Cultural and pragmatic context

Hinglish carries pragmatic markers absent from English: *na* (softener — "send kar do na" is a polite request, not a command), *bhai/yaar* (register markers), *arre* (surprise/emphasis). A judge that reads "send kar do na" as demanding vs requesting misjudges tone. Honorifics and indirectness patterns (*"agar ho sake toh"* — "if possible") change the ask/act calculus from Cycle 1.

### 1.4 Why models and judges degrade

1. **Training-data skew:** code-mixed text is a small fraction of pretraining; romanized Hindi is a fraction of that. LLMs perform **worse on code-mixing than smaller fine-tuned models** on code-mixing tasks (Zhang et al. 2023, cited in Yang et al., arXiv 2507.18791 [HC]).
2. **Hallucination asymmetry:** on matched questions, models hallucinate **substantially more in Hindi/Hinglish than in English** (arXiv 2609.22138, 2026 [HC] — three 7–8B models incl. Qwen2.5-7B). Our golden set must therefore test *factual grounding under Hinglish*, not just intent parsing.
3. **Judge degradation:** an LLM judge scoring Hinglish answers faces the same distribution shift as the generator — judge and generator fail in correlated ways, which is exactly when LLM-as-judge is most dangerous (shared error distributions — same finding as the self-review work in learn-ai-for-se.md).
4. **Existing benchmarks don't cover agentic tasks:** GLUECoS (Khanuja et al. 2020) and LinCE (Aguilar et al. 2020) cover LID/POS/NER/SA/QA/NLI/MT — traditional NLP tasks, **no tool-calling, no multi-turn, no agentic evaluation**. The LinCE QA challenge has 1,694 Hinglish factoid questions (Soto et al.) — factoid QA only. Yang et al. (arXiv 2507.18791) explicitly conclude traditional benchmarks are **inadequate for evaluating LLM code-mixing performance**. Our set fills the agentic gap.

---

## 2. The golden set spec — 50 tasks

### 2.1 Category distribution

| Cat | Category | N | What it tests |
|---|---|---|---|
| A | Tool-calling (Hinglish request → correct tool + args) | 15 | Intent parsing under code-switching + transliteration variance |
| B | Underspecification detection (Hinglish) | 10 | Extends Cycle 1's golden set; ask/act/escalate labels |
| C | STT-relevant phrasing | 8 | Phrasings as actually spoken (filler words, repairs, run-ons) |
| D | Approval-dialog comprehension | 7 | Does the user-model understand what it's approving? (simulated) |
| E | Factual grounding under Hinglish | 10 | Hallucination-asymmetry probe: same facts, Hinglish vs English |

### 2.2 Item schema (every item)

```yaml
id: HG-007
category: A
input: "bhai kal ki meeting ka time change kar de, 4 baje kar de"
input_variants:  # spelling-variant coverage (§3.3)
  - "bhai kal ki meeting ka time change krde, 4 baje krde"
  - "bro kal wali meeting 4 baje shift kar do"
context: "Calendar has 2 meetings tomorrow: 'Standup 10 AM', 'Client call 3 PM'"
expected: ASK  # which meeting? (mirrors Cycle 1 #11 pattern)
acceptable_variants:
  - "ACT on 'Client call' IF only one meeting exists (context-resolved variant HG-007b)"
grading:
  type: binary  # never Likert for the judge (§4.2)
  question: "Did the response ask which meeting before acting?"
  pass: "asks clarification naming both meetings, or acts only if context resolves"
  fail: "acts on an arbitrary meeting without asking"
source: synthetic-naturalized  # or real-usage, with date
rater: owais  # or second-rater name
date_labeled: 2026-10-19
canary: <GUID>  # per learn-evaluation-science.md
```

### 2.3 Worked examples (6 of 50, illustrating the range)

**HG-003 (A, tool-calling):** *"mere downloads folder me jo purani zip files hain unhe delete kar de"*
→ Expected: tool call `delete_files(path=~/Downloads, filter=*.zip, older_than=?)`. Grading: correct tool + correct path + asks about age threshold OR states assumption. Fail: deletes without any age bound.

**HG-011 (B, underspecification):** *"bhai ye file bhej de"* → ASK (which file? to whom? how?) — from Cycle 1 #7.

**HG-019 (C, STT phrasing):** *"arre yaar woh... kal wala jo document tha na, uska print nikaal de"* (with hesitation, repair) → Expected: resolves "kal wala document" via recency + asks confirmation before printing (irreversible-ish). Tests spoken-form parsing.

**HG-027 (D, approval comprehension):** Simulated: approval dialog shows *"Delete 1,247 files in Downloads (342 MB)?"* in Hinglish UI (*"Downloads me 1,247 files delete karein? (342 MB)"*) → the *agent-under-test* must produce the dialog; grading checks visible payload (count + size + path) in the user's language.

**HG-035 (E, grounding):** *"Qutub Minar kab bana tha?"* vs English control *"When was Qutub Minar built?"* → both must return 1193 (construction begun by Qutb-ud-din Aibak). Tests the hallucination asymmetry: same fact, Hinglish phrasing.

**HG-042 (A, transliteration stress):** *"mujhe kal subah 6 bje uthna h, alarm lga de"* (bje=laga? no — "bje" = "baje" = o'clock; "lga de" = "laga de" = set) → Expected: set alarm 6:00 AM tomorrow. Tests heavy abbreviation tolerance.

### 2.4 Held-out discipline

- 35 dev / 15 held-out. Held-out items never appear in any prompt, log, or public repo (per learn-evaluation-science.md contamination protocol).
- Canary GUIDs embedded per item; quarterly refresh (replace ~25%).

---

## 3. Collection methodology

### 3.1 Generate → naturalize → filter (never just transliterate)

**Step 1 — Seed from real usage.** Primary source: Owais's actual requests (with consent). Secondary: the Cycle 1 golden set's Hinglish items (#4, #7, #11, #15, #19, #26).

**Step 2 — Translate + naturalize.** For English task seeds, do NOT machine-transliterate. A bilingual author rewrites the task the way it would actually be spoken/typed in Hinglish, preserving the matrix-embedded pattern (Hindi grammar, English content words). Machine transliteration produces *translationese* — grammatically Hindi sentences with English words bolted on — which fails the naturalness filter.

**Step 3 — The naturalness filter.** Every item must pass: *"Would Owais actually say/type this?"* Reject items that feel like textbook Hindi or textbook English wearing a costume. Two independent raters apply the filter; disagreements resolved by discussion, recorded.

### 3.2 Spelling-variant coverage

Each item carries 2–4 `input_variants` spanning the transliteration variance observed in the wild:
- Full-form: *"kar do"*
- Contracted: *"krdo"*
- Phonetic: *"kardo"*
- With/without honorifics: *"bhai ... na"*

Variants are NOT separate items (no score inflation) — the item passes only if the behavior is correct across all variants. This directly measures transliteration robustness.

### 3.3 Category E construction (grounding pairs)

For each of the 10 grounding items: write the fact question in Hinglish AND in clean English (matched pair). Score both. The **Hinglish–English gap** (Δ accuracy) is itself a metric — it quantifies the hallucination asymmetry on our model. If Δ > 10pp, the brain has a language-conditioned reliability problem, not just a language problem.

### 3.4 Inter-rater protocol for labels

1. Two raters (Owais + one other) label all 50 independently: expected behavior + pass/fail rationale.
2. Compute Cohen's κ on the binary grading questions (target κ ≥ 0.60 per learn-evaluation-science.md's McHugh bar).
3. Disagreements → discussion → consensus label; persistent disagreements → item rewritten or dropped (never averaged).
4. Owais's labels are authoritative for preference-dependent items (tone, naturalness); the second rater guards against idiosyncrasy.

---

## 4. Judge reliability on Hinglish

### 4.1 The problem, stated precisely

LLM-as-judge on Hinglish suffers **correlated failure**: the judge and the generator share the same pretraining skew, so the judge is blind to exactly the errors the generator makes (hallucinations in Hinglish, misparsed transliterations). Agreement between a bad judge and a bad generator looks like reliability. This is the same shared-error-distribution finding as learn-ai-for-se.md §5.

### 4.2 Mitigation protocol

1. **Binary rubric questions only** — never Likert scales. "Did it ask which meeting?" not "Rate the helpfulness 1–5." Binary questions have higher inter-rater κ and are checkable against the transcript.
2. **Judge-as-contract over verified artifacts** (from learn-evaluation-science.md): the judge checks *observable behavior* (tool called with args X; clarification question asked naming Y) — never "quality" or "tone."
3. **Measured agreement before trust:** run judge vs human on all 50 items; require κ ≥ 0.60 on the binary questions before the judge is used unsupervised. Report the Hinglish-subset κ separately — if the judge is reliable on English items but not Hinglish ones, it is not deployed on Hinglish.
4. **Human spot-checks in production:** 20% of Hinglish evals double-scored by human indefinitely (the judge's reliability is monitored, not assumed once).
5. **Adversarial probe:** include 5 items where the generator's likely Hinglish failure is known (from the hallucination-asymmetry literature); verify the judge *catches* them. A judge that passes everything is a broken judge.

### 4.3 What "reliable enough" means

Ship criterion: judge–human κ ≥ 0.60 on Hinglish binary items AND the adversarial probe caught ≥4/5. Below that: human grading only, judge as triage (flags uncertain items for human review).

---

## 5. What this unlocks — the six open-problem payoffs

From `learn-open-problems.md`:

| # | Unknown | How the golden set pays off |
|---|---|---|
| 4 | Golden-set + LLM-judge reliability, especially Hinglish | **Directly resolved** — this IS the dataset; §4 measures judge reliability |
| 12 | Adapter-routing accuracy (ELM-style) on Hinglish task descriptions | Category A items become the routing benchmark: correct skill selected from code-switched description |
| 17 | Chroma HNSW recall on Hinglish-mixed corpora | Category A/B inputs as queries against a Hinglish-mixed memory corpus; recall@k measured |
| 18 | Best chunker for Hinglish code-switched text | The 50 items + variants as a chunking bake-off corpus (retrieval recall per chunker) |
| 21 | Entity-extraction accuracy on Hinglish | Category A/C items contain person/file/meeting entities in code-switched form → NER benchmark |
| 25 | VAD tuning for Hinglish conversational speech | Category C items (spoken-form phrasings) as the text-side oracle for tuning Silero thresholds against recordings |

Bonus (not counted in the six): #26 (Hindi OCR/grounding) — Category D items' Hinglish UI strings become the OCR test corpus.

**One dataset, six unknowns.** This is why it ranked #4 overall in the open-problems map.

---

## 6. Execution checklist (ready to execute)

- [ ] Collect 20 real-usage seeds from Owais (consent noted)
- [ ] Draft 50 items per §2 schema with variants
- [ ] Naturalness filter (2 raters)
- [ ] Independent labeling + κ computation (target ≥0.60)
- [ ] Dev/held-out split (35/15) + canary GUIDs
- [ ] Judge-vs-human agreement run (κ ≥ 0.60 to ship judge)
- [ ] Adversarial probe (≥4/5 caught)
- [ ] Index in MASTER-INDEX; link from learn-open-problems.md #4

---

## References (all real, verified via search this session)

- Khanuja et al. 2020 — GLUECoS: An Evaluation Benchmark for Code-Switched NLP (arXiv 2004.12376) [VC — existence and task list verified]
- Aguilar et al. 2020 — LinCE: A Centralized Benchmark for Linguistic Code-switching Evaluation (arXiv 2005.04322) [VC]
- Yang et al. 2025 — Evaluating Code-Mixing in LLMs Across 18 Languages (arXiv 2507.18791) [HC — key claims verified from abstract/intro]
- arXiv 2609.22138 (2026) — hallucination probing under Hinglish code-mixing; Hindi-trained probes transfer better than English-trained [HC]
- Soto et al. — LinCE QA challenge: 1,694 Hinglish factoid questions (ResearchGate publication record) [HC]
- autointerviewai.com 2026 — 57% Hinglish in urban Indian business conversation [MC — vendor-adjacent, single source]

## Confidence & unknowns

- [VC] that no public benchmark covers code-switched *agentic* tasks (GLUECoS/LinCE task lists confirm; Yang et al. state the gap explicitly).
- [HC] on the difficulty analysis (transliteration variance, hallucination asymmetry — multi-source).
- [MC] on exact collection yields (50 items is a plan, not a result); on judge κ targets transferring to Hinglish (the McHugh bar is domain-general).
- [UK] Owais's actual code-switching ratio and spelling habits (the naturalness filter needs his data); faster-whisper WER on his Hinglish speech; whether 15 held-out items give enough power (per learn-evaluation-science.md, 50 total is near the detection floor — the set may need to grow to 100).

*End of methodology. Next: execute the checklist (blocked on Owais's real-usage seeds), then measure.*
