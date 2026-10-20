# MEGA-SCAN TEAM 26 — SLICE A: Emotional TTS & Prosody Control

Researcher notes, read LOCALLY from clones in `.work26/` unless marked `[WEB]`.
Tags: `[CODE]` = read in source, `[README]` = project claim in its own docs, `[INFERENCE]` = my deduction, `[WEB]` = not in local clone, sourced from web/paper (weaker evidence).

**Coverage warning (read first):** Of the 12 assigned repos, only 8 cloned successfully with content.
`indexteam/IndexTTS` clone FAILED (`clone.log`: `could not read Username for 'https://github.com'`), `suno-ai/bark` and `boson-ai/EmergentTTS-Eval-public` were never cloned, and `keonlee9420_Expressive-FastSpeech2` is an empty `git init` placeholder (no commits, no files). Those 4 sections are `[WEB]`-sourced and explicitly shallower. `canopyai_Orpheus-TTS` was present in the workdir (not in my slice list, but the canonical "Orpheus-class tag system" the brief references) so it gets a full bonus section — 13 sections total, 9 code-read.

Owner hardware yardstick throughout: **RTX 2060 6GB VRAM, Ryzen 5 3600, 16GB RAM.**
JARVIS v2 surface throughout: `jarvis/tts.py` (pluggable backends: voicebox/piper/stub + cloud Fish/ElevenLabs), `jarvis/speech_policy.py` (cleans text for TTS, clause splitting), persona in `TEACHING.md` / `JARVIS-RULES.txt`.

---

## fishaudio/fish-speech (Fish Audio S2-Pro / Drama 3)

### 1. Prosody/emotion mechanism — free-form natural-language tags *inside the text*, plus structured speaker tokens

This is the most important design in the slice, and the code proves a subtle point: **the emotion tags are not tokens, not parsed, and not validated anywhere in the inference path — they are ordinary text the LLM backbone has learned to obey.**

- `[README]` S2-Pro: *"Inline natural-language instructions: tags such as `[pause]`, `[excited]` and `[whisper]` control prosody and emotion anywhere in the text."* Drama 3: *"inline tags such as `[whisper]`, `[angry]` and `[laughing]`"* plus *"laughter, crying, whispers and dramatic emotion are no longer flattened by the reference."*
- `[CODE]` `fish_speech/utils/schema.py:ServeTTSRequest` — the request is just `text: str` + `references` + sampling fields. There is **no** emotion field, no tag enum, no tag parser. The tag string travels verbatim into the model.
- `[CODE]` The only *structured* prosody-adjacent token in code is the speaker token: `fish_speech/models/text2semantic/fish_omni/generate.py:40-41` — `SPEAKER_TAG_PATTERN = re.compile(r"<\|speaker:([0-9]+)\|>")`, *"The tokenizer has one token per speaker, `<|speaker:0|>` to `<|speaker:15|>`"* (16 speakers max). `fish_speech/inference_engine/__init__.py:88-96` `tag_reference_text()` prefixes a reference transcript with `<|speaker:N|>` (Drama 3 gets a space after the tag, S2-Pro does not — a family-specific quirk worth noting). `fish_speech/content_sequence.py:80` shows the interleaved training format: `<|interleave|><|speaker:1|> TEXT AUDIO <|im_end|>…`.
- `[CODE]` Voice/emotion cloning is in-context learning, not an embedding API: `ServeReferenceAudio {audio: bytes, text: str, speaker: int|None (0–15)}` in `schema.py`; 10–30s of reference `[README]` conditions both timbre *and* delivery style — which is why Drama 3's headline fix is that strong emotion is "no longer flattened by the reference" (i.e. in S2 the reference's prosody could override the tags).
- `[README]` Drama 3 adds two mechanisms no other repo here has: **(a) multi-turn director revision** — *"guide the previous take directly ('gentler, and a bit sadder'), and the model regenerates it with that context instead of starting over"*; **(b) infilling/precise editing** — replace one word and keep surrounding timbre/transitions. Both are conversational/contextual control, not parameters.
- **Intensity control:** none explicit. No scalar, no level enum. Intensity is lexical — you write `[whisper]` vs `[shouting]`, "a bit sadder" vs "much sadder" — and the model interprets the adverb. `[INFERENCE]` This is both the strength (open vocabulary, reportedly 15k+ recognised tags in the hosted product) and the weakness (no reproducibility, no clamp, no guarantee a tag exists — an unknown tag is just text that may be *spoken* or ignored).
- Sampling knobs that indirectly affect expressiveness `[CODE]` `fish_speech/models/text2semantic/sampling.py`: defaults `temperature=0.7, top_p=0.7, top_k=30, max_new_tokens=1024/chunk, repetition_penalty=1.2` (declared *ignored* at inference — both families use repetition-aware sampling, `inference_engine/__init__.py:resolve_sampling()`).

### 2. Streaming / latency

- `[CODE]` True segment streaming: `TTSInferenceEngine.inference()` (`fish_speech/inference_engine/__init__.py:98ff`) yields a WAV `header` first when `req.streaming`, then one `segment` per generated chunk, then `final`. Text is chunked by `chunk_length` (`schema.py`: `conint(ge=100, le=1000)`, default **200**) with `iterative_prompt` generation; Drama 3 adds `single_chunk: bool` to do the whole text in one pass instead of ~300-byte chunks.
- `[README]` *"Production streaming: RTF 0.195 on a single H200, about 100 ms to first audio"* (S2-Pro); Drama 3 *"streaming support for long text."* Both figures are H200-class, not consumer-GPU figures.
- `[CODE]` `latency: Literal["normal","balanced"]` field exists in the request schema but is commented "used by api.fish.audio" — the local server does not branch on it.

### 3. Hardware fit

- `[README]` Model table: **S2-Pro = 4B params; Drama 3 = 35B-A3B MoE (3B active/token)**. 
- `[INFERENCE]` S2-Pro at bf16 is ~8GB of weights alone before the DAC decoder + KV cache — **does not fit a 2060 6GB** without aggressive quantisation/offload that this repo does not provide. Drama 3 is datacenter-only. Fish remains a **cloud-API backend** for JARVIS (which is exactly how v2 already uses Fish), not a local backend.

### 4. License — read exactly

`LICENSE` = **Fish Audio Community License Agreement v1.0 (last updated Oct 13, 2026)** — NOT an OSI license. Research/non-commercial free; commercial use only while annual revenue < **USD 500,000**, with a 90-day transition after crossing it; **hosted TTS services require a separate written licence regardless of revenue** (with a carve-out: generating speech for your own product's replies, e.g. an assistant speaking, is explicitly *not* a "Hosted Service"); outputs are owned by the user; **using the materials/outputs to train or improve any other speech/foundation model is prohibited**; "Built with Fish Audio" attribution required on distribution. README adds: *"The S2-Pro weights remain under the Fish Audio Research License."*

### 5. Steal verdict

**Steal the interface, not the model: an open-vocabulary inline `[tag]` convention as the *persona→TTS contract* in `speech_policy.py`.** JARVIS's brain should be allowed to emit a small, v2-owned tag vocabulary (`[whisper]`, `[pause]`, `[excited]`, `[softly]`…) that `speech_policy.py` passes through to tag-capable backends (Fish cloud today, CosyVoice/Chatterbox tomorrow) and *strips* for tag-blind backends (Piper) — so persona gains expression without coupling to one engine. Also steal Drama 3's *director-revision* idea at the conversation layer: "say that again, gentler" should be a brain-level retry-with-modified-tags, which costs nothing to implement over any backend.

---

## FunAudioLLM/CosyVoice (CosyVoice 1 / 2 / 3)

### 1. Prosody/emotion mechanism — THREE stacked channels: NL instruction channel + fine-grained in-text tags + zero-shot reference

CosyVoice is the most *complete* control surface in the slice because it separates utterance-level direction from word-level events:

**(a) Natural-language instruction channel (utterance-level).** `[CODE]` `cosyvoice/cli/cosyvoice.py:116` `inference_instruct(tts_text, spk_id, instruct_text, …)` (v1, fixed speaker) and `:177` `inference_instruct2(tts_text, instruct_text, prompt_wav, …)` (v2/v3, instruction + zero-shot voice). `[CODE]` `cosyvoice/cli/frontend.py:200-210`: in instruct mode the instruction *replaces* the prompt text — `frontend_instruct()` deliberately **removes the speaker embedding from the LLM input "due to information leakage"** and sets `model_input['prompt_text'] = instruct_text_token`; v2's `frontend_instruct2()` reuses the zero-shot frontend with the instruction as prompt text. `[CODE]` In CosyVoice3 the instruction is additionally a first-class training input: `cosyvoice/llm/llm.py:302-343` `prepare_lm_input_target(…, instruct_token, instruct_token_emb, …)` concatenates `[sos, instruct_emb, text_emb, task_id, speech…]` with the instruct span masked out of the loss (`IGNORE_ID`).
- The instruction vocabulary is **free natural language**, conventionally framed as a system prompt ending in `<|endofprompt|>` `[CODE]` `cosyvoice/utils/common.py:28` `instruct_list` — 25 canonical examples covering dialect ("请用四川话表达" = speak Sichuan dialect…), volume ("Please say a sentence as loudly as possible" / "in a very soft voice"), speed ("请用尽可能快地语速说一句话" = as fast as possible / 慢 = as slow as possible), and emotion ("请非常开心地说一句话" = very happily / 伤心 = sadly / 生气 = angrily), plus character styles (Peppa Pig, robot). Emotion intensity is therefore **lexical superlatives in the instruction** ("非常" = very), not a number.
- `[CODE]` CosyVoice1's tokenizer also registers discrete emotion special tokens `<|HAPPY|> <|SAD|> <|ANGRY|> <|NEUTRAL|>` (`cosyvoice/tokenizer/tokenizer.py:150-155,184`) — a legacy/ASR-side vocabulary, not the main TTS control path.

**(b) Fine-grained in-text tags (word-level, closed vocabulary).** `[CODE]` `cosyvoice/tokenizer/tokenizer.py` `CosyVoice2Tokenizer` special tokens: `[breath] [quick_breath] [noise] [laughter] [cough] [clucking] [accent] [hissing] [sigh] [vocalized-noise] [lipsmack] [mn]`, plus paired `<laughter>…</laughter>` and `<strong>…</strong>` (emphasis span). `[CODE]` `example.py:30-31` (v1-Instruct): *"support `<laughter></laughter><strong></strong>[laughter][breath]`"*; `example.py` v2 fine-grained example interleaves `[laughter]` mid-sentence; v3 example interleaves `[breath]` between clauses. CosyVoice3's tokenizer adds the full CMU phoneme + pinyin inventory for pronunciation inpainting (e.g. `[j][ǐ]` hotfix in `example.py`) — prosody-adjacent precision control.
- **Intensity:** no scalar for tags either; `<strong>` is binary, laughter is present/absent. Control granularity comes from *placement density*, not magnitude.

**(c) Reference-audio style cloning** — zero-shot prompt (audio + transcript) carries timbre + prosody; cross-lingual mode (`inference_cross_lingual`) keeps the reference's style while dropping its text conditioning.

Also: `speed: float = 1.0` parameter on every inference method `[CODE]` — a real continuous knob, applied in the flow/vocoder stage.

### 2. Streaming / latency

Best-in-slice for a voice loop. `[README]` *"Bi-Streaming: support both text-in streaming and audio-out streaming, and achieves latency as low as 150ms"* — text-in means the LLM's *token stream* can feed TTS before the sentence is finished (demonstrated in `example.py` with a `text_generator()`). `[CODE]` `cosyvoice/cli/model.py:175ff,328ff` `tts(..., stream=True)`: LLM runs on a thread filling a token buffer; the main loop vocodes whenever `token_hop_len + token_overlap_len` tokens are buffered, growing the hop by `stream_scale_factor` up to `token_max_hop_len`, with flow/HiFT caches (`hift_cache_dict`, `flow_cache_dict`, mel overlap) for seam-free chunks. vLLM and TensorRT-LLM paths exist for the LLM stage (README: TRT-LLM ≈ 4× HF).

### 3. Hardware fit

`[README]` **CosyVoice-300M (v1), CosyVoice2-0.5B, Fun-CosyVoice3-0.5B** — all ≤0.5B. `[INFERENCE]` ~1-2GB in fp16 plus flow/HiFT — **comfortably fits the 2060 6GB alongside nothing else heavy**, and is the only full instruct-capable model in this slice that does. Caveat for JARVIS: language coverage is Chinese-first (9 languages in v3, strong Chinese dialects); English is supported, **Hindi/Hinglish is not in the listed 9** — the known v2 gap.

### 4. License — read exactly

`LICENSE` = **Apache License 2.0** (standard text, no riders in the file). Code is clean to steal. (Model weights are distributed via ModelScope/HF under their own cards — not in this clone.)

### 5. Steal verdict

**Steal the two-level split: one utterance-level `instruct` string + a closed set of in-text event tags, as separate fields in v2's TTS request — never mixed.** Concretely: `tts.py` backends should accept `instruct: str|None` (persona/director direction: "calm British butler, unhurried") separately from the tagged text, and `speech_policy.py` should own the tag whitelist above (`[breath] [laughter] <strong>`) because CosyVoice proves a *closed, tokenizer-registered* tag set is what actually renders reliably — unlike Fish's open vocabulary. If v2 ever adds a local neural backend, CosyVoice2/3-0.5B is the fit; its bi-streaming design is also the reference pattern for v2's clause pipeline.

---

## indexteam/IndexTTS (IndexTTS 1.5 / IndexTTS2) — ⚠️ CLONE FAILED, [WEB] only

`[CODE-adjacent]` Clone failed per `clone.log` (`fatal: could not read Username for 'https://github.com'`). Nothing below was read from local source; it is from the IndexTTS2 paper (arXiv 2506.21619) and project pages. Treat as unverified against code.

### 1. Mechanism — disentangled emotion prompt + duration tokens + NL "soft instruction"

- `[WEB]` IndexTTS2's headline is **disentanglement of emotion from timbre**: in zero-shot mode you supply *two* prompts — a timbre prompt (whose voice) and a **separate emotion/style prompt, which may come from a different speaker** — and the model reconstructs the target timbre wearing the prompt's emotion. GPT latent representations are fed in to keep speech intelligible under strong emotion; a three-stage training paradigm stabilises it.
- `[WEB]` **Soft instruction:** a fine-tuned Qwen3 turns a natural-language emotion description into the emotion conditioning ("soft" = continuous embedding, not a label), so users can describe the desired emotional orientation in words instead of hunting for a reference clip. This is the CosyVoice instruct channel, but mediated by a dedicated instruction encoder rather than prompt text.
- `[WEB]` **Duration control** (the paper's other headline): token-count-specified generation — you state how many speech tokens to generate for exact duration (dubbing), or let it free-run and inherit prompt prosody. Note the release notes caveat: duration control was *"not yet enabled in this release"* at IndexTTS2 launch.
- Intensity: `[WEB]` emotion is as strong as the emotion prompt / soft-instruction embedding — continuous in embedding space, no user-facing scalar documented.

### 2–3. Streaming / hardware

`[WEB]` Autoregressive GPT-style backbone; no first-audio latency figure found. Size ~1.5B class (listed as 1.5B in CosyVoice3's comparison table `[README]` in the CosyVoice clone) — `[INFERENCE]` borderline on 6GB (bf16 weights ~3GB + BigVGAN vocoder + GPT KV) but not proven on a 2060.

### 4. License — [WEB], split licence

Code: **Apache 2.0**. Weights: **bilibili Model Use License Agreement / bilibili indextts Model License** — non-commercial/research free; **commercial use requires prior registration + written authorisation from bilibili**; the later bilibili Model ULA (2025-09-09) adds separate-licence triggers at >100M MAU or >RMB 1B annual revenue. Do not treat "IndexTTS is open source" as licence-clean for a shipped product.

### 5. Steal verdict

**Steal the disentanglement *requirement*, not the model: v2's TTS request should carry voice identity and emotion as two independent inputs** (a `voice` ref and an `emotion` ref/description) so "Owais's butler voice, but sounding tired" never requires re-recording the voice — IndexTTS2 is the proof this separation is the right abstraction, even if v2 implements it today as (Fish reference + Fish tags).

---

## resemble-ai/chatterbox (Chatterbox / Turbo / Nano / Multilingual)

### 1. Mechanism — ONE continuous scalar: `exaggeration` (emotion_adv), + CFG, + (Turbo only) paralinguistic tags

Chatterbox is the cleanest *knob* design in the slice:

- `[CODE]` `src/chatterbox/tts.py:215-217` and `mtl_tts.py:285-287`: `generate(text, exaggeration=0.5, cfg_weight=0.5, temperature=0.8, repetition_penalty=1.2, min_p=0.05, top_p=1.0, audio_prompt_path=None)`.
- `[CODE]` The scalar becomes a conditioning tensor, not a prompt edit: `tts.py:182,204` `prepare_conditionals(wav_fpath, exaggeration=0.5)` builds `T3Cond(..., emotion_adv=exaggeration * torch.ones(1,1,1))`; `src/chatterbox/models/t3/modules/cond_enc.py:22,54-57,84-88` — `T3Cond.emotion_adv: Optional[Tensor] = 0.5`, projected by a dedicated `emotion_adv_fc = nn.Linear(1, n_channels, bias=False)` and concatenated into the T3 condition sequence alongside speaker embedding and prompt-speech embeddings. Changing exaggeration mid-session re-builds only that one tensor (`tts.py:224-231`).
- `[CODE]` `t3_config.py:23` `self.emotion_adv = True` for the base/multilingual models; **`tts_turbo.py:159` sets `hp.emotion_adv = False`** — Turbo trades the knob away (see tags below) and `tts_turbo.py:290-291` explicitly warns *"CFG, min_p and exaggeration are not supported by the Turbo version and will be ignored"* (its defaults are `exaggeration=0.0, cfg_weight=0.0`).
- `[README]` Semantics of the knob: default `0.5` = neutral/matched to reference; *"Expressive or dramatic speech: try lower cfg_weight (~0.3) and increase exaggeration to ~0.7 or higher. Higher exaggeration tends to speed up speech; reducing cfg_weight helps compensate."* Effective user range ≈ **0.0–1.0+** (0.25 = flat, 0.5 = default, 0.7–1.0 = dramatic) `[README+CODE]`. Note what it is *not*: it is **not an emotion selector** — it amplifies the expressiveness *already implied by text + reference*. There is no happy/sad input anywhere in the base API.
- `[README+CODE]` **Turbo/Nano paralinguistic tags:** native in-text tags — README example: `"...calling you back [chuckle], have you got one minute..."`; `example_tts_turbo.py:9` uses `[chuckle]`; README lists `[cough] [laugh] [chuckle] "and more"`. These are text tokens in Turbo's vocabulary, rendered as events — same family as Orpheus tags, smaller documented set.
- Reference-audio cloning: 10s reference (`prepare_conditionals` uses 15s encoder / 10s decoder conditioning windows `[CODE]`) supplies timbre + baseline style; exaggeration then scales departure from it.

### 2. Streaming / latency

- `[CODE]` `generate()` is **whole-utterance, non-streaming** in all three classes (returns one waveform). Latency strategy is instead *model shrinkage*: `[README]` Turbo (350M) distils the S3Gen speech-token→mel decoder **from 10 steps to 1 step**; Nano (110M) *"runs 3× faster than realtime on 8 CPU cores"*. Resemble's hosted service claims sub-200ms, but that is not this code.
- `[INFERENCE]` For a clause-at-a-time loop like v2's (speech_policy already clause-splits), non-streaming per-clause generation is acceptable — first-clause latency is the metric, and Turbo/Nano are built for exactly that.

### 3. Hardware fit

`[README]` **Original/Multilingual 500M, Turbo 350M, Nano 110M.** The best fit in the slice after CosyVoice: Turbo/Nano run in ~1-2GB, Nano even on CPU. **Multilingual V3 supports Hindi (hi)** `[README]` language list — directly relevant to Hinglish, unlike CosyVoice. Every output carries Resemble's Perth neural watermark `[README+CODE: import perth]`.

### 4. License — read exactly

`LICENSE` = **MIT License, Copyright (c) 2025 Resemble AI** — clean, including for code *and* the mechanism. (Weights are HF-distributed; the repo licence is MIT.)

### 5. Steal verdict

**Steal `exaggeration` as a named, bounded scalar in v2's persona config: one `expressiveness: 0.0–1.0, default 0.5` dial in JARVIS-RULES/persona, mapped per-backend** (Chatterbox natively; Fish → tag-strength wording; Piper → ignored). It is the only mechanism in this slice a *user* can understand, a *test* can assert, and a persona file can store in one line — and Turbo's `[chuckle]`-style tags validate the closed-tag approach for the local path.

---

## SparkAudio/Spark-TTS (Spark-TTS-0.5B)

### 1. Mechanism — factorised discrete attribute tokens (BiCodec global tokens): the most *algebraic* control in the slice

Spark splits voice into **global tokens** (everything about *how* it sounds, from BiCodec) vs **semantic tokens** (what is said), and its controllable mode exposes the globals as a token grammar:

- `[CODE]` `sparktts/utils/token_parser.py` `TokenParser` — every attribute is a special token:
  - `emotion(emotion)` → `<|emotion_{id}|>` with **`EMO_MAP` of 25 emotions** (`token_parser.py:37-63`): UNKNOWN, NEUTRAL, ANGRY, HAPPY, SAD, FEARFUL, DISGUSTED, SURPRISED, SARCASTIC, EXCITED, SLEEPY, CONFUSED, EMPHASIS, LAUGHING, SINGING, WORRIED, WHISPER, ANXIOUS, NO-AGREEMENT, APOLOGETIC, CONCERNED, ENUNCIATED, ASSERTIVE, ENCOURAGING, CONTEMPT (ids 0–24). Note the list mixes emotions, speech acts (APOLOGETIC, NO-AGREEMENT), and manners (ENUNCIATED, WHISPER) — a pragmatic, not psychological, taxonomy.
  - `mel_value(mel: 0–1000)` → `<|pitch_value_{mel}|>` **and** `mel_level(very_low|low|moderate|high|very_high)` → `<|pitch_label_{0..4}|>` — pitch as *both* a fine numeric token and a coarse level token.
  - `pitch_var_value(0–10)` / `pitch_var_level(...)` — **pitch variance** (how *animated* the contour is) as its own control, separate from mean pitch. This is the closest thing in the slice to Chatterbox's exaggeration, but factorised.
  - `loudness_value(0–30)` / `loudness_level(...)`; `speed_value(0–10)` / `speed_level(...)`.
  - `gender( female|male)` → `<|gender_{0|1}|>`, `age(Child|Teenager|Youth-Adult|Middle-aged|Elderly)` → `<|age_{0..4}|>`.
- `[CODE]` **But the shipped inference path exposes only a subset:** `cli/SparkTTS.py:process_prompt_control(gender, pitch, speed, text)` builds `[<|task_controllable_tts|>, <|start_content|>, text, <|end_content|>, <|start_style_label|>, <|gender_X|><|pitch_label_Y|><|speed_label_Z|>, <|end_style_label|>]` — i.e. virtual-speaker creation by gender × pitch-level × speed-level. **Emotion, loudness, pitch-variance and the fine numeric values exist in the token grammar (and in training/`TokenParser` test code, which composes `[task, age, gender, mel, mel_level, loudness, loudness_level, emotion]`) but have no public inference entry point** — emotion is effectively prompt-cloning-only in the released CLI. An honest gap between the paper's control surface and the shipped one.
- `[CODE]` Cloning path `process_prompt()`: reference audio → BiCodec `global_token_ids` + `semantic_token_ids` serialised as `<|bicodec_global_{i}|>` / `<|bicodec_semantic_{i}|>` strings inside the LLM prompt — style transfer by token transplant, so a reference's emotion rides inside its global tokens.
- Sampling: `inference(temperature=0.8, top_k=50, top_p=0.95)` `[CODE]`.

### 2. Streaming / latency

`[CODE]` No streaming generation (single `model.generate(max_new_tokens=3000)` then detokenize). Serving story is batch/throughput: `[README]` Triton + TensorRT-LLM runtime, Spark-TTS-0.5B on one L20: **876ms avg latency, RTF 0.136** at concurrency 1. `[INFERENCE]` Per-clause use is feasible; token-streaming is not available.

### 3. Hardware fit

`[README]` **0.5B** Qwen2.5-based LLM + BiCodec. `[INFERENCE]` ~1-1.5GB fp16 — fits the 2060 easily; English + Chinese only in practice, no Hindi.

### 4. License — read exactly

`LICENSE` = **Apache License 2.0** (standard text). Clean.

### 5. Steal verdict

**Steal the factorised attribute schema for v2's *eval and persona spec*, not its tokens: define voice delivery as independent axes — `pitch_level, pitch_variance, loudness, speed, emotion` each in {very_low…very_high} — in `speech_policy.py`/persona docs.** Spark proves these axes are independently controllable and independently *nameable*; even when the actual backend is Fish or Piper, having the axes lets JARVIS log, test, and translate intent ("raise pitch variance, not pitch") instead of vibes. Also steal its 25-label pragmatic emotion taxonomy (speech acts included) as v2's emotion label set — it's better suited to an assistant than Ekman basics.

---

## nari-labs/dia (Dia-1.6B)

### 1. Mechanism — dialogue-native: speaker tags + parenthetical nonverbals + audio-prompt conditioning; NO emotion parameter at all

- `[README]` Text format is a *script*: turns prefixed `[S1]` / `[S2]`, strictly alternating, always starting `[S1]`. `[CODE]` `dia/model.py:243-257` `_tokenize_text()` is byte-level text with exactly two special replacements: `[S1]`→`\x01`, `[S2]`→`\x02`. Everything else — including emotion — is plain bytes to the encoder.
- `[README]` Nonverbals are **parenthetical stage directions in the text**: `(laughs) (clears throat) (sighs) (gasps) (coughs) (singing) (sings) (mumbles) (beep) (groans) (sniffs) (claps) (screams) (inhales) (exhales) (applause) (burps) (humming) (sneezes) (chuckle) (whistles)` — *"Use non-verbal tags sparingly… Overusing or using unlisted non-verbals may cause weird artifacts."* Emotion per se is never labelled: it must be *acted* via wording, punctuation, and the audio prompt — Dia is a dialogue *generator*, and affect is emergent from the script.
- `[CODE]` The real style channel is the **audio prompt**: `model.py:_prepare_audio_prompt()` prefills the decoder with DAC codes from a 5–10s reference (its transcript, with `[S1]/[S2]` tags, must precede the script in the text input `[README]`); *"You can condition the output on audio, enabling emotion and tone control"* `[README]`. Without a prompt, *"you will get different voices every time"* — fix the seed for consistency.
- `[CODE]` Generation knobs (`dia/model.py:_decoder_step()`, `hf.py` example): **classifier-free guidance** — conditional/unconditional logits are both computed and combined as `cond + cfg_scale·(cond − uncond)` (HF example: `guidance_scale=3.0, temperature=1.8, top_p=0.90, top_k=45`). Note a code quirk worth recording: after computing the CFG-combined logits, the top-k mask is applied but the subsequent `masked_fill` writes into **`cond_logits`** (not the combined tensor) before sampling — as read, the CFG combination's effect on the final distribution is partially undercut by that mask/fill sequence. Flagged as-read, not re-verified by running it.
- Intensity: none. A `(laughs)` is binary; emphasis is whatever the model infers.

### 2. Streaming / latency

`[CODE]` **No streaming API** — `generate()` runs the full decoder loop then `_generate_output()` DAC-decodes the whole utterance. `[README]` Speed on an **RTX 4090**: RTF ×2.1 with `torch.compile` (bf16), ×1.5 without. Input-length window is narrow: <5s of text sounds unnatural, >20s makes speech unnaturally fast `[README]` — hostile to a clause-loop unless clauses are padded/merged into that window.

### 3. Hardware fit

`[README]` **1.6B params; VRAM ~4.4GB at bf16/fp16, ~7.9GB at fp32** (4090 benchmarks). `[INFERENCE]` 4.4GB *just* fits a 6GB card with nothing else resident — but expect well under 4090 speed on a 2060; realistically ~real-time or slower per clause. English only `[README]`.

### 4. License — read exactly

`LICENSE` = **Apache License 2.0**. README adds forbidden-use disclaimers (identity misuse, deceptive content) as project policy, not licence terms.

### 5. Steal verdict

**Steal one formatting idea: parenthetical stage directions `(sighs)`, `(laughs)` as the *human-readable* spelling of v2's event tags in persona/teaching docs** — they read naturally in a script the brain writes, and a 5-line `speech_policy.py` translator can map them to whatever bracket syntax the active backend wants (`[laughter]`, `[chuckle]`, Fish `[laughing]`). Do not steal Dia itself for v2: dialogue-only, English-only, no streaming, and it eats the whole GPU.

---

## SWivid/F5-TTS (F5-TTS / E2-TTS)

### 1. Mechanism — NO emotion control. Emotion = whatever the reference clip is doing. (The control case for this slice.)

- `[CODE]` `src/f5_tts/api.py:87-101` `F5TTS.infer(ref_file, ref_text, gen_text, target_rms=0.1, cross_fade_duration=0.15, sway_sampling_coef=-1, cfg_strength=2, nfe_step=32, speed=1.0, fix_duration=None, seed=None)`. The complete knob list is acoustic plumbing: flow-matching steps (`nfe_step`), CFG strength, sway-sampling coefficient, cross-fade, target RMS, `speed`, `fix_duration`. **There is no emotion, style, pitch, or energy parameter anywhere in the API.**
- `[CODE]` Prosody is *cloned, wholesale*: `preprocess_ref_audio_text()` + `infer_process()` condition the DiT on the reference mel + reference text; the generated utterance inherits the reference's emotion, pace and intonation as an inseparable bundle. You cannot take the reference's timbre and leave its mood.
- `[CODE]` The closest thing to per-emotion control is a UI convention in `infer_gradio.py:350-412`: multi-style generation parses `{"name": "Speaker1_Happy", "seed": -1, "speed": 1}` prefixes in the text, where each named "speech type" is bound to **its own reference audio** (e.g. `Speaker1_Happy`, `Speaker1_Sad`, `Speaker2_Whisper` are three different reference clips) with its own speed slider (0.3–2.0). Emotion switching = reference switching, pre-recorded per emotion. That is a *workflow*, not a mechanism — and it is exactly the workflow a JARVIS persona would need (record/select a calm ref, an urgent ref, an amused ref) if it ever ran F5.
- `[INFERENCE]` `cfg_strength` and `seed` do shift delivery randomness/stability, but calling them emotion control would be marketing.

### 2. Streaming / latency

- `[CODE]` `infer/utils_infer.py:63ff` `chunk_text(text, max_chars=135)` splits long text; chunks are generated and cross-faded (0.15s). `infer_process(..., streaming=False, chunk_size=2048)` at `utils_infer.py:449ff` has a **pseudo-streaming mode**: `infer_single_process_streaming()` generates a *whole chunk's* waveform first, then yields it in 2048-sample slices — it reduces player buffering, not time-to-first-audio. No token-level streaming; first-audio latency = one full chunk's flow-matching (32 NFE by default).

### 3. Hardware fit

~0.3B-class DiT + Vocos/BigVGAN vocoder (CosyVoice's table lists F5-TTS at 0.3B `[README]`). `[INFERENCE]` ~1-2GB — fits the 2060 easily and is fast; the constraint is capability, not size. English/Chinese (Emilia ZH-EN training).

### 4. License — read exactly, with a trap

`LICENSE` = **MIT License, Copyright (c) 2024 Yushen CHEN** for the *code*. ⚠️ The README/model ecosystem is explicit elsewhere that the **pretrained weights were trained on Emilia, which is CC-BY-NC** — the MIT file in this clone covers code only. `[INFERENCE]` Treat F5 weights as non-commercial-tainted until verified per-checkpoint; do not ship them in a commercial JARVIS installer on the strength of this LICENSE file.

### 5. Steal verdict

**Steal the negative lesson + one workflow: F5 proves reference-cloning alone gives a companion exactly one mood — the mood of its reference clip — so v2 must never rely on cloning for emotion; and if v2 uses any clone-only backend, steal the Gradio "named speech-type = separate reference + speed" pattern** as a persona asset convention (`calm.wav / urgent.wav / amused.wav` reference library per voice). One line, honestly: as an *emotion* system, F5 has nothing to steal.

---

## myshell-ai/OpenVoice (OpenVoice V1 / V2)

### 1. Mechanism — pre-baked style embeddings: emotion is a *speaker slot* in a VITS base TTS, then tone-colour is swapped on top

OpenVoice's architecture splits the problem in two, and emotion lives entirely in stage 1:

- `[CODE]` `openvoice/api.py:73` `BaseSpeakerTTS.tts(text, output_path, speaker, language='English', speed=1.0)` — `speaker` is a **lookup ID** (`self.hps.speakers[speaker]`) in a VITS `SynthesizerTrn`, inferred with fixed `noise_scale=0.667, noise_scale_w=0.6, length_scale=1.0/speed`. The "speakers" of the English base model *are* the styles.
- `[CODE]` `openvoice/openvoice_app.py:86-88` enumerates the English style set exactly: `['default', 'whispering', 'shouting', 'excited', 'cheerful', 'terrified', 'angry', 'sad', 'friendly']` (Chinese: only `'default'`). Each style is a **pre-extracted style embedding file** (e.g. `en_style_se.pth`, `openvoice_app.py:31`) loaded and passed as the source style; `predict()` does `tts_model.tts(prompt, src_path, speaker=style, …)` then stage 2.
- `[CODE]` Stage 2 `ToneColorConverter.convert(audio_src_path, src_se, tgt_se, tau=0.3)` (`api.py:101ff`): extracts the target speaker's embedding from a short reference (`extract_se()` → `ref_enc` over the spectrogram, averaged over clips, saved as `.pth`) and voice-converts the styled base speech onto that timbre (`model.voice_conversion(spec, …, sid_src=src_se, sid_tgt=tgt_se, tau=tau)`). **This decoupling is the mechanism**: emotion/style is chosen from the base model's baked styles, identity is pasted on afterwards — an early, cruder IndexTTS2-style disentanglement.
- **Intensity:** none. Styles are categorical and baked; there is no interpolation exposed (`tau=0.3` in `convert()` is a conversion-strength constant, not a user emotion dial). `speed` is the only continuous knob.
- `[README]` claims *"granular control over voice styles, such as emotion and accent, as well as rhythm, pauses, and intonation"* — `[CODE]` contradicts "granular": in the released code those are the 9 fixed slots above. Marketing > mechanism here.

### 2. Streaming / latency

`[CODE]` None — sentence-split (`split_sentences_into_pieces`), synthesise each, concatenate with 0.05s/speed gaps (`audio_numpy_concat`). VITS is non-autoregressive and fast per sentence, so per-clause latency is low in practice, but there is no streaming API.

### 3. Hardware fit

VITS-scale models (tens of millions of params ×2 stages). `[INFERENCE]` Well under 1GB — trivially fits the 2060, even CPU-plausible. V2 supports EN/ES/FR/ZH/JA/KO `[README]`; no Hindi. Dated (2023/2024) quality vs the rest of the slice.

### 4. License — read exactly

`LICENSE` = **MIT-style permissive text, Copyright 2024 MyShell.ai** ("Permission is hereby granted… deal in the Software without restriction…"); README states *"Starting from April 2024, both V2 and V1 are released under MIT License. Free for commercial use."* Clean.

### 5. Steal verdict

**Steal the asset pattern, not the model: a small library of named style embeddings/references per persona voice (`friendly / whispering / excited / sad`…) selected by the brain like tools.** OpenVoice proves a companion doesn't need continuous emotion to *feel* expressive — 6–9 well-chosen categorical moods, switched deliberately by `speech_policy.py`, cover most assistant moments; v2 can implement the same pattern today over Fish (per-mood reference IDs) with zero new models.

---

## Choddeok/EmoSphere-TTS (Interspeech 2024)

### 1. Mechanism — spherical VAD: emotion as (intensity = radius, style = azimuth/elevation) — the most *principled* intensity model in the slice

- `[README]` Abstract: *"synthesizes expressive emotional speech by using a spherical emotion vector… Without any human annotation, we use the arousal, valence, and dominance pseudo-labels to model the complex nature of emotion via a Cartesian-spherical transformation."* Trained on ESD (5 emotions × speakers).
- `[CODE]` `data_gen/tts/base_binarizer.py:234-273`: a pretrained emotion model predicts a VAD vector per utterance; vectors are centred on the neutral centroid `VAD_Neu_center = [0.4135, 0.5169, 0.3620]`, then `convert_tensor_to_polar_coordinates(re_emo_VAD, max_distance)` produces the **spherical emotion vector** — radius = distance from neutral (normalised by the dataset's max distance), angles = direction in VAD space.
- `[CODE]` `tasks/tts/dataset_utils.py:65-67` splits it for the model: `emo_VAD_inten = spherical[:, :1]` (the radius), `emo_VAD_style = spherical[:, 1:]` (azimuth + elevation).
- `[CODE]` `modules/tts/EmoSphere.py:35-99` (FastSpeech2 backbone): 
  - categorical `emo_id` → `emo_id_proj` embedding (`hidden//4`), projected by `emo_proj`;
  - intensity scalar → `emo_VAD_inten_proj = nn.Linear(1, hidden//2)`, with the inference override `if hparams['emo_inten'] != None: emo_VAD_inten[0,0] = hparams['emo_inten']`, **clamped to [0, 1]** (`EmoSphere.py:71-73`) — so at inference you dial **intensity ∈ [0,1]** directly as a config value;
  - style angles are *discretised*: azimuth bucketed into 4 bins over `[-π/2, π]` (`azimuth_bins`, `azimuth_emb = Embedding(4, hidden//8)`), elevation into 2 bins over `[π/2, π]` (`elevation_emb = Embedding(2, …)`), concatenated → `sty_proj`;
  - emotion embedding = `softplus(concat(emos_proj, style_proj))` → LayerNorm, then `emo_all_emb = intens_embed + emosty_embed`, concatenated with the speaker embedding and added at the variance adaptor (duration/pitch/energy predictors all conditioned on it).
- So the user-facing control algebra is: **pick an emotion direction (label or VAD point) × scale radius 0→1 for intensity**, including *blends* — any VAD point is a valid style, not just the 5 training labels. No other repo in the slice separates "which emotion" from "how much" this cleanly in a continuous space (Chatterbox's exaggeration is direction-less; Spark's axes are discrete tokens).

### 2. Streaming / latency

None — offline FastSpeech2 + BigVGAN pipeline, research code (NATSpeech harness, MFA alignment required for training). Non-autoregressive, so inference itself is fast, but there is no serving/streaming layer whatsoever.

### 3. Hardware fit

FastSpeech2-scale (tens of M params) + BigVGAN. `[INFERENCE]` Fits any GPU trivially — irrelevant, because quality/scope (single ESD dataset, 5 emotions, dated vocoder, research-grade robustness, no zero-shot voice) make it unusable as JARVIS's voice. This is a *paper with code*, not a product.

### 4. License — read exactly

`LICENSE` = **MIT License, Copyright (c) 2026 Deok-Hyeon Cho**. Clean for the idea and the code.

### 5. Steal verdict

**Steal the coordinate system for v2's *internal* emotion representation: store persona delivery state as `(emotion_direction, intensity_0_to_1)` — e.g. TEACHING.md/JARVIS-RULES entries and `speech_policy.py` variables as `calm:0.3`, `urgent:0.8` — and let each backend translate radius into its own language** (Fish: adverb choice "slightly/very"; Chatterbox: exaggeration scalar; Spark-style: level tokens). EmoSphere is the theoretical justification that intensity-as-radius is separable from emotion-as-direction; v2 should adopt the algebra even though it will never run this model.

---

## keonlee9420/Expressive-FastSpeech2 — ⚠️ CLONE EMPTY, [WEB] only

`[CODE-adjacent]` Local directory is an empty git placeholder (no commits/files) — nothing was code-read. The repo is a FastSpeech2 fork in the ming024 lineage adding expressive/multi-speaker conditioning. What follows is the well-documented FastSpeech2 mechanism `[WEB]`, flagged as not verified against this fork's diffs:

- `[WEB]` FastSpeech2's **variance adaptor** predicts per-phoneme **duration, pitch (via CWT pitch spectrogram) and energy**, each added as embeddings between encoder and decoder — prosody is *predicted from text*, and at inference the predictions can be scaled: `p_control` (pitch), `e_control` (energy), `d_control` (duration) multipliers (default 1.0; >1 = higher pitch / louder / slower).
- `[WEB]` Expressive forks of this lineage typically add a speaker embedding + a reference/style or emotion embedding into the variance adaptor so pitch/energy predictions become emotion-conditional; the exact conditioning in *this* fork is unverified.
- Streaming: none (non-AR, fast offline synthesis). Hardware: FastSpeech2-scale, trivially fits 2060. License: the upstream ming024/FastSpeech2 lineage is MIT, but **this fork's LICENSE was not read (no local file)** — do not cite a licence for it.
- **Steal verdict (one line):** Nothing repo-specific is verifiable; the generic FastSpeech2 lesson — *predicted pitch/energy/duration are themselves controllable by simple scalar multipliers at inference* — is already captured better by Spark's token algebra and EmoSphere's radius, so steal nothing here.

---

## suno-ai/bark (Bark) — ⚠️ NOT CLONED, [WEB] only

Nothing read from local source. From the project's own README/docs via web:

### 1. Mechanism — the original emergent tag system: text-to-*audio*, where tags are discoveries, not a spec

- `[WEB]` Bark is a GPT-style text→semantic→coarse→fine EnCodec-token generator that *"does not make a difference between speech and music."* Known non-speech tokens written inline: `[laughter] [laughs] [sighs] [music] [gasps] [clears throat]`, plus typography as prosody: `—` / `...` for hesitation, `♪` for sung lyrics, **CAPITALIZATION for emphasis**, `[MAN]` / `[WOMAN]` to bias speaker gender.
- `[WEB]` Emotion is otherwise **prompt-inherited**: `history_prompt` — a preset (`v2/en_speaker_6` etc.) or a custom `.npz` from real audio via `save_as_prompt()` — carries voice *and* its emotion/tone/pitch; the project itself warns it can "fully clone voices, including tone, pitch, emotion" and therefore restricts shipped prompts to synthetic speakers.
- Intensity: none — no scalar, no levels; repetition/placement of tags and caps are the only dials, and output is famously non-deterministic/deviant ("may deviate from a given prompt in unexpected ways" `[WEB]`).

### 2–3. Streaming / hardware

`[WEB]` No streaming; ~13s optimal generation window, long form by segment concatenation. **~12GB VRAM full model; ~8GB with `SUNO_USE_SMALL_MODELS=True`** — **does not fit the 2060 6GB** in either configuration. Roughly real-time only on enterprise GPUs.

### 4. License — [WEB]

MIT (project README) for code; research/demo positioning. Not verified from a local LICENSE file.

### 5. Steal verdict

**Steal nothing as a system; cite Bark as the historical proof that inline tags + typography (caps = emphasis, `...` = hesitation) are a viable prosody surface** — v2's `speech_policy.py` should *preserve* meaningful punctuation/capitalisation from the brain instead of normalising it away, because every tag-family model since Bark reads it. Bark itself is too big, too slow, and too unruly for a butler.

---

## boson-ai/EmergentTTS-Eval-public (EmergentTTS-Eval) — ⚠️ NOT CLONED, [WEB] only — EVAL, not a TTS model

This repo contains **no synthesis mechanism at all** — it is the benchmark Fish S2 brags about winning (81.88% `[README]` in the Fish clone). Its value to this slice is as the *measurement* layer.

### 1. What it actually is

- `[WEB]` (paper, arXiv 2505.23009) 1,645 test cases across **six categories: Emotions, Paralinguistics, Foreign Words, Syntactic Complexity, Complex Pronunciation, Questions** — built by iterative LLM expansion from human seed prompts, each round targeting harder structural/phonetic/prosodic cases.
- `[WEB]` **Model-as-a-judge:** a Large Audio Language Model scores pairwise/system outputs per category (judge prompts define per-category criteria, e.g. Emotions = quoted dialogue vs narrative emotional expressiveness; Paralinguistics = interjections, onomatopoeia, capitalisation, vowel elongation; Questions = interrogative vs declarative intonation), with a 0–3 rubric and explicit bias-mitigation instructions ("focus only on the specified dimension"); reported high correlation with human preference, plus a human-survey harness (`human_alignment/run_survey.py`) for calibration.

### 2–4. Streaming / hardware / license

N/A (no model). Judge cost = LALM API calls. `[WEB]` **Apache License 2.0** per the repo's LICENSE as indexed — not verified from a local file.

### 5. Steal verdict

**Steal the category taxonomy as v2's TTS regression-test set: a fixed `tests/voice/` script list covering exactly its six categories in JARVIS's own register (emotion contrasts, paralinguistic tags, Hinglish/foreign words, nested-clause sentences, URLs/numbers/dates, question intonation), scored by ear or audio-LLM judge on every backend/persona change.** Without this, every "more expressive" change in v2 is unfalsifiable — this repo is how you prove a steal worked.

---

## BONUS: canopyai/Orpheus-TTS (Orpheus-3B) — present in workdir, code-read

Included because the brief names "Orpheus-class tag systems" — this is the class definer, and it was on disk.

### 1. Mechanism — LLM-native emotive tags as ordinary tokens in a Llama-3B TTS

- `[README]` *"Guided Emotion and Intonation: control speech and emotion characteristics with simple tags."* Prompting guide: text is formatted `{voice}: {text}` (voices: tara, leah, jess, leo, dan, mia, zac, zoe) and you insert **emotive tags inline: `<laugh> <chuckle> <sigh> <cough> <sniffle> <groan> <yawn> <gasp>`** — a closed set of 8, all *events*, not emotion states; sustained emotion is again acted via wording.
- `[CODE]` `orpheus_tts_pypi/orpheus_tts/engine_class.py:75-77, _format_prompt()`: the package wraps the prompt as `<custom_token_3>{prompt}[{voice}]<custom_token_4><custom_token_5>` (small-model path) or tokenises `"{voice}: {prompt}"` bracketed by fixed Llama token ids (128009/128260/128261/128257) — the tags are **not** special-cased in code; like Fish, they are text the finetune learned. `emotions.txt` in the repo root is a stray word-list (happy/sad/angry/excited/whisper/crying/sleepy/panicky/curious/frustrated/fast/slow/deep/high/shout + typos) — apparently a finetuning-style vocabulary, unused by the inference package `[CODE+INFERENCE]`.
- `[CODE]` Sampling is plain LLM sampling: `generate_tokens_sync(prompt, voice, temperature=0.6, top_p=0.8, repetition_penalty=1.3, max_tokens=1200)` via vLLM `SamplingParams`; README warns `repetition_penalty >= 1.1` is *required* for stability and that raising temperature/repetition_penalty makes it speak faster — i.e. prosody leaks into sampling params, a design smell.
- Zero-shot cloning exists on the *pretrained* model via in-context text–speech pairs (more pairs = more reliable voice) `[README]`; the finetuned-prod model uses the fixed named voices.

### 2. Streaming / latency

`[README]` *"~200ms streaming latency for realtime applications, reducible to ~100ms with input streaming"* — `[CODE]` `generate_speech()` → `tokens_decoder_sync()` streams SNAC codec frames as vLLM yields tokens (`decoder.py` reassembles 7-token frames); a `realtime_streaming_example/` is included. Genuinely streaming-by-construction (LLM token stream → codec), the pattern CosyVoice also implements.

### 3. Hardware fit

3B Llama backbone, bf16, vLLM. `[INFERENCE]` ~6GB+ for weights alone at bf16 + KV cache + SNAC — **does not fit the 2060 6GB** in this implementation (llama.cpp/GGUF community paths exist per README's "no GPU inference" pointer, at unknown quality/speed). English-first; multilingual family is a research release.

### 4. License — read exactly

`LICENSE` = **Apache License 2.0**. Clean code licence.

### 5. Steal verdict

**Steal the tag *set design*: Orpheus's 8 tags are all short, bodily, unambiguous events — the right granularity for a butler who should sigh or chuckle rarely and never emote continuously.** Adopt exactly this restraint as v2 policy in JARVIS-RULES (tags are seasoning, default = no tag), whatever backend renders them.

---

# Cross-repo synthesis

## The five mechanism families (all 13 repos reduce to these)

| # | Family | Repos | User-facing form | Intensity |
|---|--------|-------|------------------|-----------|
| 1 | **Free-form NL tags / instructions in text** | Fish, CosyVoice (instruct), IndexTTS2 (soft instruct), Orpheus, Bark, Dia | `[whisper]`, "say it sadly", `<laugh>` | Lexical only ("a bit…", "very…") |
| 2 | **Closed in-text event tags** | CosyVoice (fine-grained), Chatterbox Turbo, Dia, Orpheus | `[breath]`, `[chuckle]`, `(sighs)` | None (binary events) |
| 3 | **Continuous scalar dial** | Chatterbox (`exaggeration`), EmoSphere (radius) | one float | **Native, bounded** |
| 4 | **Factorised discrete attributes** | Spark-TTS, EmoSphere (VAD angles), FastSpeech2 (p/e/d scales) | level tokens / VAD point | Discrete levels or continuous VAD |
| 5 | **Reference/style cloning (bundled)** | F5, Dia, OpenVoice, Spark (BiCodec), Fish, CosyVoice zero-shot | a wav file / preset | Whatever the clip contains |

## Ranked: top 5 prosody mechanisms to steal for JARVIS v2

1. **Fish's open-vocabulary inline `[tag]` + CosyVoice's closed-tag discipline, combined** — tags in the text stream, owned and whitelisted by `speech_policy.py`, passed through or stripped per backend. Zero new models, works with v2's existing Fish cloud backend today and every local candidate tomorrow.
2. **Chatterbox's single `exaggeration` scalar (0–1, default 0.5)** — the only mechanism that fits in a persona file, a settings slider, and a unit test simultaneously; the model for how v2 should expose *all* delivery intensity.
3. **EmoSphere's (direction × radius) algebra** — the internal representation that makes #2 principled: persona state = emotion direction + intensity 0–1, translated per-backend (adverb for Fish, scalar for Chatterbox, level for Spark-style).
4. **CosyVoice's two-level split (utterance `instruct` ≠ in-text tags) + bi-streaming pattern** — the architecture for v2's TTS request object and its clause pipeline if/when a local neural backend lands (and CosyVoice3-0.5B is the only instruct model that fits the 2060 — with the Hindi caveat; Chatterbox Multilingual is the Hindi-capable fallback).
5. **EmergentTTS-Eval's six-category test taxonomy** — the eval harness that makes 1–4 falsifiable; steal the categories as v2's fixed voice regression scripts.

## Single best steal

**Make `speech_policy.py` the owner of a two-part delivery contract — an utterance-level direction (persona instruction + emotion-direction × intensity-0-to-1) plus a closed whitelist of in-text event tags (`[pause] [breath] [laugh] [chuckle] (sighs) <strong>`) — emitted by the brain, translated or stripped per TTS backend.** Every repo in this slice that users actually love (Fish, CosyVoice, Chatterbox, Orpheus) converges on "direction in language, events in tags, intensity as one number"; every repo that skipped one of the three (F5: no direction, Dia: no intensity, Bark: no discipline) feels broken as a companion voice. This steal is pure policy code — it ships in v2 without a single new model, and it is backend-portable for whichever local model (CosyVoice3 / Chatterbox) eventually runs on the 2060.

## Hardware-fit summary (RTX 2060 6GB)

| Repo | Size | Fits 6GB? |
|------|------|-----------|
| CosyVoice 2/3 | 0.5B | ✅ comfortably |
| Chatterbox Turbo/Nano/MTL | 350M/110M/500M | ✅ comfortably (Nano even CPU) |
| Spark-TTS | 0.5B | ✅ |
| F5-TTS | ~0.3B | ✅ (weights licence caveat) |
| OpenVoice | VITS ×2 | ✅ trivially |
| EmoSphere / Expressive-FS2 | FS2-scale | ✅ (but research-grade, unusable as product voice) |
| Dia | 1.6B / 4.4GB bf16 | ⚠️ borderline, alone on GPU |
| IndexTTS2 | ~1.5B | ⚠️ borderline, unverified locally |
| Orpheus | 3B | ❌ (this impl.; GGUF paths unproven) |
| Fish S2-Pro / Drama 3 | 4B / 35B-A3B | ❌ local — cloud API only |
| Bark | ~12GB / 8GB small | ❌ |
| EmergentTTS-Eval | — (eval) | N/A |

## Licence summary (as read)

MIT: Chatterbox, F5-TTS (**code only** — Emilia-trained weights carry NC taint), OpenVoice, EmoSphere-TTS. Apache-2.0: CosyVoice, Spark-TTS, Dia, Orpheus, IndexTTS **code**, EmergentTTS-Eval `[WEB]`. Custom/restrictive: **Fish Audio Community License** (revenue-capped commercial, hosted-service carve-out, no-training-others clause; S2 weights under Fish Audio Research License), **IndexTTS weights** (bilibili model licence — commercial needs written authorisation). Expressive-FastSpeech2 licence **not read** (clone empty) — unverified.
