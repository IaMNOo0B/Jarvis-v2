# Finance Skill — read-only money tracking

Track money; never move it. This skill has **no payment, trading, bank-login
or network capability of any kind** — it only analyzes data the owner hands
it (bank-export files placed in the skill's data folder, prices the owner
quotes). Patterns from the Team 25 mega-scan (Actual, Maybe,
changedetection.io), re-implemented in stdlib Python.

## Tools

- `finance_load_transactions` — read a CSV/JSON bank export from the skill
  data folder → normalized `{date, payee, amount}` rows. Bad rows are
  skipped and counted, never fatal.
- `finance_detect_subscriptions` — find weekly / every-2-weeks / monthly /
  yearly recurring charges (dates within ±1 day, amounts consistent).
  Transfers and exact duplicates are excluded. Each subscription carries an
  evidence string ("matched 6 of 6, ±1 day, exact amount"), the next
  expected date, and a monthly-cost rollup.
- `finance_categorize` — categorize ONE transaction using **only the
  owner's existing category ids**. Payee-substring `rules` run first; no
  rule hit → `category_id: null` (abstain — never invent a category). A
  transaction marked `locked` (human-set category) is returned unchanged.
- `price_watch_set` / `price_watch_check` / `price_watch_list` — watch a
  price (id = URL or label). `check` alerts **only** when the move vs the
  last alerted/baseline price reaches `threshold_pct` (default 5%).
  Smaller moves are recorded silently, so slow drift still alerts once it
  adds up — no notification fatigue.

## Rules for the brain

- Never invent a category. If `finance_categorize` returns null, either ask
  the owner or leave the transaction uncategorized.
- Prices are owner-supplied: JARVIS never fetches a price by itself through
  this skill. If the owner asks "what's the price now?", get the number
  from the web skill first, then call `price_watch_check` with it.
- Subscription evidence strings are the explanation — quote them when the
  owner asks "why do you think this is a subscription?"
- Nothing in this skill can pay, buy, sell, transfer, or log into anything.
  If the owner asks for that, say so plainly; the owner's finger stays on
  every rupee.
