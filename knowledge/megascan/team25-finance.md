# MEGA-SCAN TEAM 25 — Personal Finance & Tracking Assistants

**Mission:** expense trackers, budget assistants, portfolio trackers, subscription managers, price watchers — PhD-level, code-first.
**Boundary (owner's standing rule, respected throughout):** JARVIS has **no wallet and no money-move powers**. Everything below is evaluated as **READ-ONLY tracking patterns only** — ingestion, categorization, detection, alerting. Any repo whose core value is executing payments/trades gets a verdict of *pattern-only / rejected for v2*.
**Method:** `git clone --depth 1` into `.work25/`, read locally. Slow network killed several full clones mid-checkout (git removes partial dirs); giants were recovered via `--filter=blob:none --sparse` (Actual) and `--no-checkout` + `git show` (Paperless, Receipt Wrangler, OpenBB, Wealthfolio). License tags: **[V]** = read from the repo's own LICENSE file this pass; **[UK]** = not verified this pass, do not reuse code until checked.

## Count

| Depth | Count | Repos |
|---|---|---|
| Deep (core code read) | 12 | firefly-iii, data-importer, maybe, actual (sparse), ghostfolio, changedetection.io, ezbookkeeping, paperless-ngx, huginn, beancount-import, beancount, hledger |
| Medium (structure + key files/trees) | 9 | receipt-wrangler, OpenBB, wealthfolio, TradingAgents, ai-hedge-fund, paisa, hledger-flow, nordigen-python, ofxparse |
| Triage (structure/license only) | 12 | akaunting, invoiceninja, InvoicePlane, MoneyFox, ivy-wallet, moneymanagerex, portfolio-performance, fava, budgetzero, DumbBudget, DumbAssets, ticker |
| Clone-blocked / not found (honest) | 7 | wallos (3 attempts, never landed — address unverified), rotki, FinGPT, kapital, SolidInvoice, financier, full-actual (sparse substitute used) |
| **Total touched** | **40** | 33 with code or trees in hand |

---

## DEEP READS

### 1. firefly-iii/firefly-iii — the rules-engine king [V: AGPL-3.0 → ideas only]
- **Ingestion:** thin core; all importing lives in the separate data-importer (below). Webhooks are outbound events (WebhookTrigger/Response enums), not ingest.
- **Categorization logic — the pattern that matters:** `app/TransactionRules/Engine/SearchRuleEngine.php` (618 lines). Rules are **not** evaluated row-by-row in PHP; they are *compiled into search queries* against the transaction store. Each `RuleTrigger` (typed, with `needs_context` flag from `config/search.operators`) becomes a search operator; **strict rules** AND all triggers, **non-strict rules** OR them. `RuleGroup`s fire in order; a rule can `stop_processing`. Actions are a closed class zoo (`TransactionRules/Actions/*`: SetCategory, AddTag, ConvertToDeposit, AppendDescription…) — small, typed, composable. Failed actions emit `RuleActionFailed` user notifications instead of dying silently.
- **Alert design:** `app/Jobs/WarnAboutBills.php` — daily job over active *Bills* (recurring charges): computes expected dates, then two distinct alert classes: **overdue** (expected date passed, no matching transaction) and **end-date warnings** (subscription ending soon). Notification types are separate classes: `BillReminder`, and notably `SubscriptionsOverdueReminder` — Firefly treats subscriptions as first-class tracked objects with their own overdue semantics.
- **Steal verdict:** the *compile-rules-to-queries* trick and the bill/overdue two-class alert model. Code: AGPL → patterns only.

### 2. firefly-iii/data-importer — ingestion engineering at its best [V: AGPL-3.0 → ideas only]
- **Ingestion:** one service tree per source — `Services/{CSV, Camt, Nordigen, EnableBanking, Akahu, SimpleFIN, Sophtron, LunchFlow}` — each with `Conversion/Routine/GenerateTransactions` normalizing into one canonical transaction shape before submit. CSV path adds a **Roles** service: it *guesses column roles* (amount/date/description/IBAN) from content, user confirms.
- **Dedup (two layers):** (a) **identifier-based**: a configured ID field (e.g. bank's transaction id) compared against existing entries before submit (`ApiSubmitter` logs "Identifier-based duplicate detection found no value…" and degrades gracefully); (b) a local **"cell" duplicate check** pre-submit; duplicates from the API are classified (`isDuplicationError`) and skippable via `ignore_duplicate_errors`.
- **Safety catches:** `Support/Internal/DuplicateSafetyCatch` — importer *repairs* pathological rows instead of importing garbage: a "transfer" whose source == destination is rewritten to a withdrawal, and the original values are appended to the transaction notes with a paper trail. Ingestion that explains its own corrections.
- **Steal verdict:** per-source converter → canonical model; ID-first dedup with graceful degradation; repair-with-paper-trail. Patterns only (AGPL).

### 3. maybe-finance/maybe — LLM categorization done right [V: AGPL-3.0 → ideas only; **project archived by its authors, code still instructive**]
- **Categorization (the single best LLM pattern in this scan):** `app/models/provider/openai/auto_categorizer.rb` calls the LLM with a **strict JSON schema whose enums are built from the user's own data**: `transaction_id` must be one of the batch's real IDs; `category_name` must be one of the user's real category names **or the literal string "null"**. The model *cannot invent* a category. Instructions demand: most-specific category, classification must match (expense↔expense), **"favor null over false positives… only match if 60%+ confident."** Batch-processed via `AutoCategorizeJob`.
- **Provenance & locking (the part everyone else misses):** `Family::AutoCategorizer` writes results with `enrich_attribute(:category_id, …, source: "ai")`, then calls `transaction.lock_attr!(:category_id)` — the attribute is **locked** so automation never overwrites it again (and never fights a human correction). Same design in `AutoMerchantDetector`.
- **Assistant boundary (directly v2-shaped):** `app/models/assistant/` exposes exactly **four** functions to the LLM — `get_accounts`, `get_balance_sheet`, `get_income_statement`, `get_transactions`. All read-only. There is no write function to abuse. The chat can answer "what did I spend on food in March?" but can never move a rupee.
- **Steal verdict:** steal all three designs (schema-enum categorization, source-tag + lock, closed read-only function set). Patterns only (AGPL).

### 4. actualbudget/actual — deterministic subscription detection [license UK this pass — sparse checkout excluded it; code read via sparse clone of `packages/loot-core`]
- **Rules:** `server/rules/{condition,action,rule}.ts` — typed `Condition` (operator table `CONDITION_TYPES`, ~460 lines incl. formula support via `balanceOfFormula` + handlebars custom functions) and `Action` classes; rules execute in stages over a transaction and are indexed (`rule-indexer.ts`) so large journals stay fast. More conventional than Firefly's query-compilation, but the formula actions (compute a field from others) are a nice extension.
- **THE steal — `server/schedules/find-schedules.ts` (391 lines):** finds recurring charges *from raw transaction history with zero ML*: for each candidate pattern (`weekly`, `every2weeks`, `monthly`, `monthlyLastDay`, `monthly1stor3rd`, `monthly2ndor4th`…), it generates expected occurrence dates, matches real transactions by **payee**, **ranks** matches by date-distance (`getRank` — exact date = rank 1, degrading with drift), requires amount consistency (exact-amount matches boost the score), and **excludes transfers** ("Don't match transfers") so rent-to-self noise never becomes a fake subscription. Output = proposed schedules for the user to confirm.
- **Steal verdict:** this algorithm, ported to stdlib Python over v2's transaction store, *is* the v2 `finance_subscriptions` detector. Deterministic, explainable ("matched 6 of last 6, ±1 day, exact amount"), no LLM.

### 5. ghostfolio/ghostfolio — portfolio data plumbing [V: AGPL-3.0 → ideas only]
- **Ingestion:** `apps/api/src/services/data-provider/` — **ten providers behind one interface** (Yahoo, CoinGecko, Alpha Vantage, EODHD, FMP, RapidAPI, Google Sheets, a `manual` provider, Ghostfolio's own) plus a `data-enhancer` (stock splits etc.). `DataProviderService` (1,000 lines) groups requested symbols **by dataSource**, fans out with `Promise.all`, and wraps each provider call in per-symbol try/catch — one dead provider degrades one symbol, never the portfolio.
- **Computation:** `portfolio/calculator/` (2,430-line core) with TWR / MWR / ROI / ROAI variants as separate strategy classes chosen by a factory — performance math is pluggable, not hardcoded. Exchange-rate service treats FX as just another provider-fed time series (with derived cross-rates).
- **Alert design:** weak (benchmark comparisons, no real alerting engine) — noted honestly.
- **Steal verdict:** provider-interface + per-symbol fail-soft fan-out for any v2 market-data reads; strategy-class performance math. Patterns only (AGPL).

### 6. dgtlmoon/changedetection.io — price watching, production-grade [V: Apache-2.0 → code borrowable with attribution]
- **Watch mechanics:** pluggable `processors/` (text/JSON diff, image SSIM diff, **restock_diff**). Price discipline is explicit in `processors/restock_diff/__init__.py`: there is **one** place where price text becomes a number ("keep it that way"), fed by three extractors tried in order — JSON-LD/itemprop structured data → microdata → (optional) LLM plugin that returns availability/price as strings, normalized through the same single parse point.
- **Alert design (the anti-fatigue lesson):** a detected price change does **not** automatically notify. `restock` state keeps `price` + `last_price`; if `price_change_threshold_percent` is set and the % move is below it, the processor **overrides change-detected to FALSE**. On top sits a general **conditions engine** (`changedetectionio/conditions/`) compiling user rules to **JSON Logic** (>, <, in, == over named fields), and notifications go through a multi-channel notification service (Apprise-style) with per-watch overrides.
- **Steal verdict:** **directly implementable in v2** — single-parse-point price extraction, last-price state, %-threshold suppression, JSON-Logic alert conditions. Apache-2.0: the *design* is the steal (v2 is Python — this is Python; still write our own, borrow structure).

### 7. mayswind/ezbookkeeping — the converter zoo, MIT [V: MIT → code + patterns borrowable]
- **Ingestion:** `pkg/converters/` holds **20+ importers** (csv, excel, camt, mt, ofx, qif, iif, beancount, gnucash, fireflyIII, alipay, jdcom, feidee…) — **every one** normalizes into the same `ImportedTransactionSlice` via a shared data-table intermediate and the same `ParseImportedData(ctx, user, fileData, …, accountMap, expenseCategoryMap, incomeCategoryMap, transferCategoryMap, tagMap)` signature: the user's **own accounts/categories/tags are passed in as the mapping vocabulary** for every format.
- **AI importers (second convergence):** `pkg/converters/ai/` — `AIRecognizedTextTransactionDataImporter` and `…Image…Importer` (photo/screenshot of a statement → LLM → `RecognizedTransactionResult[]` → fed through the *same* SimpleImporter as CSV). The AI is just another converter; downstream dedup/validation is shared, and the category maps it receives are the user's existing ones.
- **Steal verdict:** the highest-value *borrowable* codebase here (MIT, Go — port the architecture, not the language): one canonical transaction model, format converters as plugins, AI as a converter among equals.

### 8. paperless-ngx/paperless-ngx — dual-path classification [license UK this pass — read via `git show` from a no-checkout clone]
- **Path 1 — classic ML that knows when to shut up:** `src/documents/classifier.py` trains an sklearn `MLPClassifier` over tantivy-vectorized text on documents carrying AUTO-match tags/correspondents. `_predict_with_threshold()` returns **None** when the winning class probability is below the configured threshold — abstention is a first-class outcome. The trained model file is **HMAC-signed** (`_SignedFileWriter`, `ClassifierModelCorruptError`) — a tampered/swapped model is detected, not silently trusted.
- **Path 2 — LLM with an allowlist:** `src/paperless_ai/ai_classifier.py` builds prompts (with or without RAG over similar documents) and validates the reply through `_candidate_id_allowlist()` — the LLM's choice must be one of the **real taxonomy IDs**; anything else is discarded. `parse_ai_response` → `ClassificationSuggestions`, i.e. the LLM *suggests*, the system disposes.
- **Steal verdict:** third independent convergence on the same doctrine as Maybe + ezbookkeeping: **closed vocabulary + abstain-below-threshold + human/system final say**. For v2, documents≈transactions; the pattern ports 1:1. (Also: sign your learned artifacts.)

### 9. huginn/huginn — the watcher-agent pattern library [V: MIT → borrowable]
- Not a finance app — a general **agent/event** system whose agent zoo reads like an alerting syllabus: `change_detector_agent`, `attribute_difference_agent`, `de_duplication_agent` (suppress repeat events inside a window), `gap_detector_agent` (alert when expected events *stop*), `peak_detector_agent`, `digest_agent` / `email_digest_agent` (batch events into scheduled digests), plus `csv_agent`, `local_file_agent`, `mqtt_agent`. Agents wire into *Scenarios* (event graphs): watch → transform → dedup → digest → notify.
- **Steal verdict:** for v2's price/subscription alerts, copy the *composition*: detector → dedup window → digest batching, instead of naive per-event ringing. This is the same anti-fatigue conclusion Team 14 reached from the proactivity scan — independent cross-confirmation. MIT.

### 10. jbms/beancount-import — dedup as a matching problem [license UK this pass]
- `beancount_import/matching.py`: merges freshly-imported transactions against existing journal entries using **explicit tolerances** — `fuzzy_match_days` (default window) and `fuzzy_match_amount` (Decimal tolerance) — matching on amount sign conventions (a −66.88 posting matches a +66.88 transaction) inside the date window. Sources are pluggable (`api_proxies`, per-institution importers) and matching produces *merge candidates for review*, not silent overwrites.
- **Steal verdict:** tolerance-based fuzzy dedup (exact-ID first per data-importer, fuzzy window second) with review-not-overwrite. Ports cleanly to stdlib (`datetime`, `decimal`).

### 11. beancount/beancount [V: GPL-2.0 → ideas only] & 12. simonmichael/hledger [V: GPL-3.0 → ideas only]
- The plain-text accounting elders. Beancount's `ingest/` importer framework + `plugins/noduplicates.py` (a *validation plugin* that fails the ledger if duplicate transactions exist — dedup as an invariant check, not just an import step) and hledger's **CSV rules files** (declarative per-bank mapping: `fields`, `if`-block conditional assignments — categorization as versionable text config the owner can read and edit) are the two durable ideas. For v2: per-source mapping rules as plain config files, and a post-import invariant check.

---

## MEDIUM READS (structure + key files verified)

- **Receipt-Wrangler/receipt-wrangler** [UK]: receipt photos → AI extraction. `api/internal/ai/` has **one client interface, three backends (OpenAI / Gemini / Ollama)** — local-model option matters for private financial data. Prompts are **first-class, user-editable objects** (`internal/constants/prompt.go`, `upsert_prompt_command.go`) per group ("magic fill" prompts) — the owner tunes extraction without code. Steal: provider-pluggable extraction + editable prompts.
- **OpenBB-finance/OpenBB** [UK]: ~20 provider packages (`fred`, `sec`, `ecb`, `imf`, `nasdaq`…) under `openbb_platform/providers/`, each implementing a standard fetcher interface with common query/data models. The standard itself is the lesson: if v2 ever reads market/economic data, adopt a provider-standard shape from day one. (Read-only data platform — fits the boundary.)
- **afadil/wealthfolio** [UK]: local-first portfolio tracker (tree verified: Tauri-style desktop app, AGENTS.md, docker + web variants). Local-first posture matches v2; internals not deep-read this pass.
- **TauricResearch/TradingAgents** + **virattt/ai-hedge-fund** [V: MIT]: multi-analyst LLM pipelines (fundamental/sentiment/technical analysts → debate → risk view) producing *analysis only*. Useful pattern for a v2 "explain my portfolio" read-only explainer; **their trade-decision outputs are explicitly out of v2 scope** — verdict: explanation pattern yes, decision/execution pattern no.
- **ananthakumaran/paisa** [GPL-family, COPYING present]: personal finance UI over **either** beancount **or** hledger ledgers (two Dockerfile variants) — proves the ledger-as-source-of-truth + swappable-engine design; insights (net worth, cash flow, budget vs actual) are pure queries over the ledger.
- **apauley/hledger-flow** (63 files): opinionated import pipeline — per-account `import/` dirs, rules files per bank, `hledger-flow import` builds the journal reproducibly. Ingestion-as-build-pipeline.
- **nordigen/nordigen-python** (49 files): GoCardless (PSD2) bank-data client — institution list → requisition (user consent link) → accounts → balances/transactions. The consent-first flow is the only legitimate shape for bank sync; v2 verdict: pattern noted, **no bank-credential handling in v2** (read files the owner exports instead).
- **jseutter/ofxparse** (2,573 lines incl. tests): mature OFX statement parser, ships `mcc_codes.csv` (merchant category codes) — MCC lookup is a free deterministic categorization signal for card transactions (groceries vs fuel) before any rules/LLM run.

## TRIAGE (one-liners)
- **akaunting/akaunting** [V: **BSL-1.1** — not open source]: double-entry SaaS for businesses; wrong shape and wrong license. Skip.
- **invoiceninja** / **InvoicePlane**: invoicing-first; only their recurring-invoice *scheduling* is adjacent. Skip for tracking.
- **MoneyFox/MoneyFox**, **ivy-apps/ivy-wallet** [V: GPL-3.0], **moneymanagerex** [V: GPL-2.0]: capable manual-entry trackers (desktop/mobile). Their value is UX, not mechanisms; nothing here beats the deep reads. Ideas only.
- **portfolio-performance/portfolio** [V: EPL-1.0]: serious desktop portfolio analysis (5,421 files) — benchmark/TTWRP depth, but Java/Eclipse stack; Ghostfolio covers the patterns.
- **beancount/fava** [V: MIT]: the beloved web UI over beancount — proof a thin read-only UI over a ledger is enough product.
- **budgetzero** [UK]: envelope/zero-based budgeting UI ("envelope budgeting" per README) on Actual's backend — envelope math (assign every unit of currency a job; category balances carry over) is the one transferable idea for a v2 budget view.
- **DumbWareio/DumbBudget** [V: GPL-3.0] (27 files): deliberately minimal budget tracker — the floor of the category: one file in, totals out. **DumbWareio/DumbAssets** [UK]: physical-asset + warranty/maintenance-expiry tracking — its *expiry alerting* (warranty end dates) is a cute adjacent pattern for subscription renewals.

---

## Cross-scan convergences (the PhD layer)

1. **Closed-vocabulary LLM categorization — found independently in Maybe, ezbookkeeping, Paperless.** LLM output is constrained (strict schema enums / passed-in category maps / candidate-ID allowlists) to the owner's *existing* categories; below ~60% confidence the correct answer is **null/abstain**; results carry provenance (`source: "ai"`) and **lock** so automation never overwrites a human. This is now a three-source-verified doctrine, not a preference.
2. **Dedup is layered:** exact identifier → tolerance-window fuzzy match (amount ±, days ±) → invariant validation after import. Every serious system has ≥2 layers; every toy has zero.
3. **Alerts fail by fatigue, not by silence:** changedetection's %-threshold override, Huginn's dedup+digest composition, Firefly's two-class bill alerts (upcoming vs overdue) — all engineered against notification spam. Matches Team 14's fire-discipline findings exactly.
4. **Everything converges on one canonical transaction model** with per-source converters (data-importer, ezbookkeeping, hledger-flow, paisa-over-ledgers). Ingestion quality = converter count × normalization discipline.
5. **The assistant is read-only by construction in the best systems** (Maybe's 4 functions). Capability absence beats permission checks.

## Top 5 repos (for JARVIS v2)
1. **actualbudget/actual** — the subscription-detection algorithm + staged rules.
2. **maybe-finance/maybe** — LLM categorization & read-only assistant design (archived, still the clearest code).
3. **dgtlmoon/changedetection.io** — price-watch alerting discipline (Apache-2.0).
4. **firefly-iii (+ data-importer)** — rules compilation, bill alerts, ingestion/dedup depth.
5. **mayswind/ezbookkeeping** — MIT converter architecture incl. AI-as-converter.

## Top 3 steals for v2 (all READ-ONLY)
1. **`finance_categorize` (closed-vocabulary LLM + rules first):** deterministic rules (owner-editable mapping files, hledger-style; MCC lookup via ofxparse's table as a free first signal) run first; the LLM only sees leftovers and may only answer with one of the owner's existing category IDs or `null` (<60% → null); writes are tagged `source="ai"` and locked against future automation. (Maybe × ezbookkeeping × Paperless convergence.)
2. **`finance_subscriptions` (Actual's find-schedules, ported):** pattern templates (weekly/2-weekly/monthly/month-end/nth-weekday) × payee match × date-distance rank × amount-consistency, transfers excluded → candidate subscriptions with evidence strings; renewal/overdue alerts fire through v2 proactivity (Team 14 fire discipline), never as raw per-event rings.
3. **`price_watch` (changedetection + Huginn composition):** structured-data-first price extraction with a **single parse point**, `last_price` state per watch, **%-threshold suppression** of noise, JSON-Logic conditions for owner rules ("below ₹X", "any drop ≥10%"), and dedup→digest delivery so ten drops become one briefing line. (Apache-2.0 design; write our own stdlib implementation.)

**Runner-up steal:** data-importer's repair-with-paper-trail + beancount-import's fuzzy-window dedup as layers 2–3 of v2 statement ingestion, behind ID-based dedup.

**Explicitly NOT stolen (boundary):** every payment/trading/wallet mechanism encountered (TradingAgents' trade decisions, bank-sync credential flows). V2 tracks, detects, and alerts — the owner's finger stays on every rupee.

## Honest gaps
- Wallos (the one dedicated subscription manager targeted) never cloned in 3 attempts — its reminder mechanics are **unverified**, not summarized from memory. Actual's `find-schedules` + Firefly's bill system cover the same ground from code, so the loss is redundancy, not coverage.
- Rotki and FinGPT clones never landed; both were portfolio-adjacent and are the first re-run candidates if this slice is revisited.
- Licenses marked [UK] were not read this pass (several repos were tree-only via `--no-checkout`); **no code from a [UK] or copyleft repo should be reused** — patterns only until verified.
