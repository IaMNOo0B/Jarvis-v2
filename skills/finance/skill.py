"""Finance skill — READ-ONLY money tracking (Team 25 mega-scan steals).

HARD BOUNDARY: this skill only reads, computes, and remembers. It has no
payment path, no trading path, no credential handling, and imports no
network module — prices and transactions are always supplied by the owner
(bank-export files in the skill jail; prices quoted by the owner). There is
deliberately nothing here that could move a rupee.

Steals implemented (patterns only — Maybe / ezbookkeeping / Paperless are
AGPL/[UK]; Actual's find-schedules design is re-implemented from the scan
report, changedetection's alert discipline from its Apache-2.0 design):

1. Subscription detection (Actual `find-schedules`): cadence templates x
   payee x date-distance x amount consistency; transfers and exact
   duplicates excluded deterministically; every hit carries an evidence
   string like "matched 6 of 6, ±1 day, exact amount".
2. Closed-vocabulary categorization (Maybe x ezbookkeeping x Paperless
   convergence): deterministic payee rules first; an injected classifier
   may only answer with one of the owner's existing category ids, and
   abstains (null) below 60% confidence or on any out-of-vocabulary
   answer; a human-set (locked) category is NEVER overwritten.
3. Price watch (changedetection x Huginn): %-threshold suppression of
   noise. The change is measured against the price at the last alert (or
   the baseline), so sub-threshold moves accumulate silently instead of
   resetting the clock — ten small drops become one honest alert.

Storage: price_watches.json in the skill jail, atomic rewrites.
Stdlib only.
"""

import csv
import io
import json
import re
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

WATCH_STORE_NAME = "price_watches.json"
DEFAULT_THRESHOLD_PCT = 5.0
CONFIDENCE_FLOOR = 0.60  # Maybe's doctrine: favor null over false positives

# Payees containing any of these (case-insensitive) are money moving between
# the owner's own accounts — Actual: "Don't match transfers."
TRANSFER_MARKERS = (
    "transfer",
    "to self",
    "self neft",
    "self imps",
    "own account",
    "internal transfer",
    "account transfer",
    "fund transfer",
)

CADENCES = ("weekly", "biweekly", "monthly", "yearly")

_DATE_KEYS = ("date", "transaction_date", "txn_date", "posting_date",
              "value_date", "tran date")
_PAYEE_KEYS = ("payee", "description", "narration", "merchant", "name",
               "particulars", "details")
_AMOUNT_KEYS = ("amount", "amt", "transaction amount", "value")

_CSV_DATE_COLS = ("date", "posting date", "transaction date", "txn date",
                  "value date", "tran date")
_CSV_PAYEE_COLS = ("payee", "description", "narration", "merchant", "name",
                   "details", "particulars")
_CSV_AMOUNT_COLS = ("amount", "amt", "value", "transaction amount")
_CSV_DEBIT_COLS = ("debit", "debit amount", "withdrawal", "withdrawals", "dr")
_CSV_CREDIT_COLS = ("credit", "credit amount", "deposit", "deposits", "cr")

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d/%m/%Y",   # owner's locale first: DD/MM/YYYY
    "%d-%m-%Y",
    "%d-%b-%Y",
    "%d-%b-%y",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%m/%d/%Y",
)


# ---------------------------------------------------------------------------
# Parsing — bank exports into the one canonical transaction shape
# ---------------------------------------------------------------------------

def parse_date(value):
    """Parse a date/datetime string into a ``date``; None if unparseable."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(value):
    """Parse an amount into a float; None if unparseable.

    Handles bank-export dressing: thousands separators, currency symbols,
    ``(1,234.00)`` negatives, and trailing DR/CR (DR = money out = negative).
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    negative = False
    upper = text.upper()
    if upper.endswith("DR"):
        negative = True
        text = text[:-2].strip()
    elif upper.endswith("CR"):
        text = text[:-2].strip()
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()
    text = re.sub(r"[^\d.\-+]", "", text.replace(",", ""))
    if text in ("", "-", "+", ".", "-.", "+."):
        return None
    try:
        amount = float(text)
    except ValueError:
        return None
    return round(-abs(amount) if negative else amount, 2)


def _first(raw, keys):
    for key in keys:
        if key in raw and raw[key] not in (None, ""):
            return raw[key]
    return None


def normalize_transaction(raw):
    """Normalize one raw dict into {date, payee, amount[, category_id,
    locked, transfer]} — or None when date or amount cannot be parsed."""
    if not isinstance(raw, dict):
        return None
    lowered = {str(k).strip().lower(): v for k, v in raw.items()}
    parsed_date = parse_date(_first(lowered, _DATE_KEYS))
    amount = parse_amount(_first(lowered, _AMOUNT_KEYS))
    if amount is None:  # debit/credit column pair instead of a signed amount
        debit = parse_amount(_first(lowered, _CSV_DEBIT_COLS))
        credit = parse_amount(_first(lowered, _CSV_CREDIT_COLS))
        if debit:
            amount = -abs(debit)
        elif credit:
            amount = abs(credit)
    if parsed_date is None or amount is None:
        return None
    payee = _first(lowered, _PAYEE_KEYS)
    txn = {
        "date": parsed_date.isoformat(),
        "payee": " ".join(str(payee).split()) if payee is not None else "",
        "amount": amount,
    }
    if lowered.get("category_id"):
        txn["category_id"] = str(lowered["category_id"])
    if lowered.get("locked"):
        txn["locked"] = bool(lowered["locked"])
    if lowered.get("transfer"):
        txn["transfer"] = bool(lowered["transfer"])
    kind = str(lowered.get("type") or lowered.get("kind") or "").lower()
    if kind == "transfer":
        txn["transfer"] = True
    return txn


def parse_transactions_csv(text):
    """CSV bank export -> (transactions, skipped_count)."""
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return [], 0
    headers = {str(h).strip().lower(): h for h in reader.fieldnames if h}
    date_col = next((headers[c] for c in _CSV_DATE_COLS if c in headers), None)
    payee_col = next((headers[c] for c in _CSV_PAYEE_COLS if c in headers), None)
    amount_col = next((headers[c] for c in _CSV_AMOUNT_COLS if c in headers), None)
    debit_col = next((headers[c] for c in _CSV_DEBIT_COLS if c in headers), None)
    credit_col = next((headers[c] for c in _CSV_CREDIT_COLS if c in headers), None)
    txns, skipped = [], 0
    for row in reader:
        raw = {}
        if date_col:
            raw["date"] = row.get(date_col)
        if payee_col:
            raw["payee"] = row.get(payee_col)
        if amount_col:
            raw["amount"] = row.get(amount_col)
        elif debit_col or credit_col:
            raw["debit"] = row.get(debit_col) if debit_col else None
            raw["credit"] = row.get(credit_col) if credit_col else None
        txn = normalize_transaction(raw)
        if txn is None:
            skipped += 1
        else:
            txns.append(txn)
    return txns, skipped


def parse_transactions_json(text):
    """JSON export (a list of transaction objects) -> (transactions, skipped)."""
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("JSON export must be a list of transactions")
    txns, skipped = [], 0
    for item in data:
        txn = normalize_transaction(item)
        if txn is None:
            skipped += 1
        else:
            txns.append(txn)
    return txns, skipped


def load_transactions_file(path):
    """Load a .csv/.json export from disk -> (transactions, skipped_count)."""
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".json":
        return parse_transactions_json(text)
    if path.suffix.lower() == ".csv":
        return parse_transactions_csv(text)
    stripped = text.lstrip()
    if stripped.startswith("[") or stripped.startswith("{"):
        return parse_transactions_json(text)
    return parse_transactions_csv(text)


# ---------------------------------------------------------------------------
# Subscription detection — Actual's find-schedules, deterministic, stdlib
# ---------------------------------------------------------------------------

def _days_in_month(year, month):
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - date(year, month, 1)).days


def _advance(cadence, current, anchor_day):
    """Next expected occurrence date after ``current`` for a cadence.

    Monthly/yearly steps keep the anchor's day-of-month, clamped to the
    target month (Jan 31 -> Feb 28 -> Mar 31).
    """
    if cadence == "weekly":
        return current + timedelta(days=7)
    if cadence == "biweekly":
        return current + timedelta(days=14)
    if cadence == "monthly":
        year = current.year + (1 if current.month == 12 else 0)
        month = 1 if current.month == 12 else current.month + 1
        return date(year, month, min(anchor_day, _days_in_month(year, month)))
    if cadence == "yearly":
        return date(current.year + 1, current.month,
                    min(anchor_day, _days_in_month(current.year + 1,
                                                   current.month)))
    raise ValueError(f"unknown cadence {cadence!r}")


def _match_cadence(dated_txns, cadence, anchor_index):
    """Match a cadence pattern anchored at one charge (find-schedules style).

    Expected dates are generated from the anchor; each is matched to the
    closest still-unused charge within ±1 day — extra one-off charges are
    simply never matched, and the run stops at the first expected date
    with no charge near it. Returns (matched_txns, max_deviation,
    next_expected) or None when fewer than 2 charges match.
    """
    anchor = dated_txns[anchor_index][0]
    last_date = dated_txns[-1][0]
    used = set()
    matched = []
    max_dev = 0
    expected = anchor
    while expected <= last_date + timedelta(days=1):
        best = None
        for idx, (d, _txn) in enumerate(dated_txns):
            if idx in used:
                continue
            dev = abs((d - expected).days)
            if dev <= 1 and (best is None or dev < best[0]
                             or (dev == best[0] and d < best[1])):
                best = (dev, d, idx)
        if best is None:
            break
        dev, _d, idx = best
        used.add(idx)
        matched.append(dated_txns[idx][1])
        max_dev = max(max_dev, dev)
        expected = _advance(cadence, expected, anchor.day)
    if len(matched) < 2:
        return None
    return matched, max_dev, expected


def _monthly_cost(cadence, amount):
    if cadence == "weekly":
        return amount * 52 / 12
    if cadence == "biweekly":
        return amount * 26 / 12
    if cadence == "yearly":
        return amount / 12
    return amount


def _is_transfer(txn):
    if txn.get("transfer"):
        return True
    payee = txn.get("payee", "").lower()
    return any(marker in payee for marker in TRANSFER_MARKERS)


def detect_subscriptions(transactions, *, min_occurrences=3,
                         amount_tolerance_pct=2.0):
    """Find recurring subscriptions in normalized transactions.

    Deterministic: exact duplicates are dropped, transfers are excluded,
    and a payee qualifies only when a whole run of charges fits one
    cadence (±1 day) with amounts consistent within tolerance.
    """
    pool = []
    seen = set()
    for raw in transactions or []:
        txn = normalize_transaction(raw)
        if txn is None or _is_transfer(txn):
            continue
        key = (txn["date"], txn["payee"].lower(), txn["amount"])
        if key in seen:
            continue  # exact duplicate — count the charge once
        seen.add(key)
        pool.append(txn)

    by_payee = {}
    for txn in pool:
        if txn["payee"]:
            by_payee.setdefault(txn["payee"].lower(), []).append(txn)

    subscriptions = []
    for group in by_payee.values():
        group.sort(key=lambda t: (t["date"], t["amount"]))
        dated = [(date.fromisoformat(t["date"]), t) for t in group]
        best = None
        for cadence in CADENCES:
            for anchor_index in range(len(dated)):
                found = _match_cadence(dated, cadence, anchor_index)
                if found is None:
                    continue
                matched, max_dev, next_expected = found
                if len(matched) < min_occurrences:
                    continue
                if best is None or len(matched) > len(best[1]):
                    best = (cadence, matched, max_dev, next_expected)
        if best is None:
            continue
        cadence, matched, max_dev, next_expected = best
        amounts = [abs(t["amount"]) for t in matched]
        median = statistics.median(amounts)
        if median <= 0:
            continue
        if all(a == amounts[0] for a in amounts):
            amount_note = "exact amount"
        elif all(abs(a - median) <= median * amount_tolerance_pct / 100
                 for a in amounts):
            amount_note = f"amount within {amount_tolerance_pct:g}%"
        else:
            continue  # cadence fits but amounts wander — not a subscription
        subscriptions.append({
            "payee": matched[-1]["payee"],
            "cadence": cadence,
            "occurrences": len(matched),
            "amount": median,
            "monthly_cost": round(_monthly_cost(cadence, median), 2),
            "last_date": matched[-1]["date"],
            "next_expected": next_expected.isoformat(),
            "evidence": (
                f"matched {len(matched)} of {len(group)}, "
                f"±{max_dev} day{'s' if max_dev != 1 else ''}, {amount_note}"
            ),
        })

    subscriptions.sort(key=lambda s: s["payee"].lower())
    return {
        "subscriptions": subscriptions,
        "monthly_total": round(sum(s["monthly_cost"] for s in subscriptions), 2),
        "count": len(subscriptions),
    }


# ---------------------------------------------------------------------------
# Categorization — closed vocabulary, rules first, never overwrite a human
# ---------------------------------------------------------------------------

def _vocabulary_ids(categories):
    ids = []
    for cat in categories or []:
        if isinstance(cat, str):
            ids.append(cat)
        elif isinstance(cat, dict):
            cid = cat.get("id") or cat.get("category_id") or cat.get("name")
            if cid:
                ids.append(str(cid))
    return ids


def _classifier_verdict(raw):
    """Normalize a classifier reply to (category_id, confidence) or None."""
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw, 1.0
    if isinstance(raw, (tuple, list)) and len(raw) == 2:
        try:
            return str(raw[0]), float(raw[1])
        except (TypeError, ValueError):
            return None
    if isinstance(raw, dict):
        cid = raw.get("category_id") or raw.get("category") or raw.get("id")
        if not cid:
            return None
        try:
            return str(cid), float(raw.get("confidence", 1.0))
        except (TypeError, ValueError):
            return None
    return None


def categorize_transaction(transaction, categories, rules=None,
                           classifier=None):
    """Categorize one transaction into the owner's existing categories only.

    Order: (1) a locked (human-set) category is returned untouched —
    automation NEVER overwrites it; (2) deterministic payee-substring
    rules; (3) the optional injected classifier, whose answer is honored
    only if it names a real category id at >= 60% confidence
    (allowlist + abstain, the Maybe/Paperless doctrine). Anything else
    abstains: {"category_id": None, "source": None, "confidence": None}.
    """
    txn = transaction if isinstance(transaction, dict) else {}
    vocab = set(_vocabulary_ids(categories))

    if txn.get("locked") and txn.get("category_id"):
        return {"category_id": txn["category_id"], "source": "human",
                "confidence": 1.0}

    haystack = " ".join(
        str(txn.get(k) or "") for k in ("payee", "description", "narration")
    ).lower()
    for rule in rules or []:
        if not isinstance(rule, dict):
            continue
        needle = rule.get("contains") or rule.get("match") or rule.get("substring")
        cid = rule.get("category_id") or rule.get("category")
        if needle and cid and str(cid) in vocab \
                and str(needle).lower() in haystack:
            return {"category_id": str(cid), "source": "rule",
                    "confidence": 1.0}

    if classifier is not None:
        verdict = _classifier_verdict(classifier(txn, sorted(vocab)))
        if verdict is not None:
            cid, confidence = verdict
            if cid in vocab and confidence >= CONFIDENCE_FLOOR:
                return {"category_id": cid, "source": "ai",
                        "confidence": confidence}

    return {"category_id": None, "source": None, "confidence": None}


# ---------------------------------------------------------------------------
# Price watch — state in the skill jail, %-threshold anti-fatigue discipline
# ---------------------------------------------------------------------------

def _watch_path(ctx):
    return Path(ctx.jail_dir) / WATCH_STORE_NAME


def _load_watches(path):
    path = Path(path)
    if not path.exists():
        return {"watches": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"watches": {}}
    if isinstance(data, dict) and isinstance(data.get("watches"), dict):
        return data
    return {"watches": {}}


def _save_watches(path, data):
    path = Path(path)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(path)


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def watch_set(path, watch_id, price, threshold_pct=DEFAULT_THRESHOLD_PCT):
    """Create a watch, or re-baseline an existing one to the given price."""
    price = float(price)
    threshold_pct = float(threshold_pct)
    if price <= 0:
        raise ValueError("price must be positive")
    if threshold_pct <= 0:
        raise ValueError("threshold_pct must be positive")
    data = _load_watches(path)
    watch = {
        "id": str(watch_id),
        "reference_price": price,
        "last_price": price,
        "threshold_pct": threshold_pct,
        "checks": 0,
        "updated_at": _now_iso(),
    }
    data["watches"][str(watch_id)] = watch
    _save_watches(path, data)
    return dict(watch)


def watch_check(path, watch_id, current_price):
    """Check a watch against a newly observed price.

    The move is measured against the reference price (the price at the
    last alert, or the baseline) — so sub-threshold moves are recorded
    silently yet still accumulate toward an alert instead of resetting
    the comparison every check. On alert the reference re-baselines.
    """
    current_price = float(current_price)
    if current_price < 0:
        raise ValueError("current_price must not be negative")
    data = _load_watches(path)
    watch = data["watches"].get(str(watch_id))
    if watch is None:
        raise ValueError(f"unknown watch {watch_id!r} — set it first")
    reference = float(watch["reference_price"])
    change_pct = round((current_price - reference) / reference * 100, 4) \
        if reference else 0.0
    alert = abs(change_pct) >= float(watch["threshold_pct"])
    watch["last_price"] = current_price
    watch["checks"] = int(watch.get("checks", 0)) + 1
    watch["updated_at"] = _now_iso()
    if alert:
        watch["reference_price"] = current_price
    _save_watches(path, data)
    return {
        "id": str(watch_id),
        "alert": alert,
        "change_pct": round(change_pct, 2),
        "reference_price": reference,
        "current_price": current_price,
        "threshold_pct": float(watch["threshold_pct"]),
    }


def watch_list(path):
    """All watches, sorted by id."""
    data = _load_watches(path)
    return {"watches": [data["watches"][k] for k in sorted(data["watches"])]}


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

def handle(tool_name, args, ctx):
    if tool_name == "finance_load_transactions":
        jail = Path(ctx.jail_dir).resolve()
        target = (jail / str(args["filename"])).resolve()
        if target != jail and jail not in target.parents:
            raise ValueError("file must live inside the skill data folder")
        if not target.is_file():
            raise ValueError(f"no such file in the skill data folder: "
                             f"{args['filename']!r}")
        txns, skipped = load_transactions_file(target)
        return {"transactions": txns, "count": len(txns), "skipped": skipped,
                "source_file": str(args["filename"])}

    if tool_name == "finance_detect_subscriptions":
        return detect_subscriptions(
            args["transactions"],
            min_occurrences=int(args.get("min_occurrences", 3)),
            amount_tolerance_pct=float(args.get("amount_tolerance_pct", 2.0)),
        )

    if tool_name == "finance_categorize":
        return categorize_transaction(
            args["transaction"], args["categories"],
            rules=args.get("rules"),
        )

    if tool_name == "price_watch_set":
        return watch_set(
            _watch_path(ctx), args["id"], args["price"],
            threshold_pct=float(args.get("threshold_pct",
                                         DEFAULT_THRESHOLD_PCT)),
        )

    if tool_name == "price_watch_check":
        return watch_check(_watch_path(ctx), args["id"], args["current_price"])

    if tool_name == "price_watch_list":
        return watch_list(_watch_path(ctx))

    raise ValueError(f"unknown tool {tool_name!r}")
