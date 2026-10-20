"""Tests for skills/finance — read-only tracking (Team 25 steals).

Covers: manifest validity + clean static scan + no network/execution
surface; CSV/JSON ingestion; subscription detection (Actual's
find-schedules pattern) incl. the worked evidence-string example;
closed-vocabulary categorization incl. the never-overwrite-a-human proof;
price-watch threshold discipline; and end-to-end registry dispatch.
"""

import ast
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / "skills" / "finance"
SKILL_PATH = SKILL_DIR / "skill.py"
spec = importlib.util.spec_from_file_location("finance_skill", SKILL_PATH)
fin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fin)

from jarvis.skills.registry import SkillContext, SkillManifest, SkillRegistry, scan_skill

ALLOW_ALL = lambda tool, tier, args, ctx: True  # noqa: E731


class _Ctx:
    def __init__(self, jail):
        self.jail_dir = str(jail)


@pytest.fixture()
def ctx(tmp_path):
    return _Ctx(tmp_path)


def _monthly(payee, days, amount, year=2026):
    return [{"date": f"{year}-{m:02d}-{d:02d}", "payee": payee, "amount": amount}
            for m, d in enumerate(days, start=1)]


NETFLIX = _monthly("Netflix", [5, 6, 5, 6, 5, 6], -499.0)


# ---------------------------------------------------------------------------
# Manifest, scan, and the hard boundary
# ---------------------------------------------------------------------------

class TestBoundary:
    def test_manifest_validates_and_is_all_tier1(self):
        raw = json.loads((SKILL_DIR / "skill.json").read_text(encoding="utf-8"))
        manifest = SkillManifest.from_dict(raw, source="finance")
        assert manifest.name == "finance"
        assert {t.name for t in manifest.tools} == {
            "finance_load_transactions", "finance_detect_subscriptions",
            "finance_categorize", "price_watch_set", "price_watch_check",
            "price_watch_list",
        }
        assert all(t.tier == 1 for t in manifest.tools)

    def test_static_scan_is_clean(self):
        assert scan_skill(SKILL_DIR) == []

    def test_no_network_or_execution_surface(self):
        tree = ast.parse(SKILL_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        # Only inert stdlib: parsing + math + dates. No net, no exec, no OS.
        assert imported <= {"csv", "io", "json", "re", "statistics",
                            "datetime", "pathlib"}
        src = SKILL_PATH.read_text(encoding="utf-8")
        for banned in ("eval(", "exec(", "__import__", "os.system",
                       "subprocess", "urllib", "socket", "requests"):
            assert banned not in src


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

class TestLoadTransactions:
    def test_parse_amount_dressing(self):
        assert fin.parse_amount("₹1,499.00") == 1499.0
        assert fin.parse_amount("(2,000.00)") == -2000.0
        assert fin.parse_amount("500.00 DR") == -500.0
        assert fin.parse_amount("500.00 CR") == 500.0
        assert fin.parse_amount("-499") == -499.0
        assert fin.parse_amount("") is None
        assert fin.parse_amount("abc") is None

    def test_csv_indian_dates_and_bad_row_skipped(self, ctx, tmp_path):
        (tmp_path / "stmt.csv").write_text(
            "Date,Description,Amount\n"
            "05/01/2026,Netflix,-499.00\n"
            "06/02/2026,Netflix,-499.00\n"
            "not-a-date,Broken,-1.00\n",
            encoding="utf-8")
        out = fin.handle("finance_load_transactions",
                         {"filename": "stmt.csv"}, ctx)
        assert out["count"] == 2 and out["skipped"] == 1
        assert out["transactions"][0] == {
            "date": "2026-01-05", "payee": "Netflix", "amount": -499.0}

    def test_csv_debit_credit_columns(self):
        txns, skipped = fin.parse_transactions_csv(
            "Date,Description,Debit,Credit\n"
            "05/01/2026,Salary,,50000.00\n"
            "06/01/2026,Rent,15000.00,\n")
        assert skipped == 0
        assert txns[0]["amount"] == 50000.0
        assert txns[1]["amount"] == -15000.0

    def test_json_aliases(self):
        txns, skipped = fin.parse_transactions_json(
            '[{"date": "2026-01-05", "description": "Netflix",'
            ' "amount": -499}]')
        assert skipped == 0
        assert txns[0]["payee"] == "Netflix"

    def test_path_escape_refused(self, ctx):
        with pytest.raises(ValueError):
            fin.handle("finance_load_transactions",
                       {"filename": "../outside.csv"}, ctx)

    def test_missing_file_is_an_honest_error(self, ctx):
        with pytest.raises(ValueError):
            fin.handle("finance_load_transactions",
                       {"filename": "nope.csv"}, ctx)


# ---------------------------------------------------------------------------
# Subscription detection
# ---------------------------------------------------------------------------

class TestDetectSubscriptions:
    def test_worked_example_netflix(self):
        """The brief's example: 6 monthly charges, ±1 day, exact amount."""
        out = fin.detect_subscriptions(NETFLIX)
        assert out["count"] == 1
        sub = out["subscriptions"][0]
        assert sub["payee"] == "Netflix"
        assert sub["cadence"] == "monthly"
        assert sub["occurrences"] == 6
        assert sub["evidence"] == "matched 6 of 6, ±1 day, exact amount"
        assert sub["next_expected"] == "2026-07-05"
        assert sub["monthly_cost"] == 499.0
        assert out["monthly_total"] == 499.0

    def test_weekly_rollup(self):
        mondays = [{"date": d, "payee": "Gym", "amount": -99.0} for d in (
            "2026-01-05", "2026-01-12", "2026-01-19", "2026-01-26",
            "2026-02-02", "2026-02-09", "2026-02-16", "2026-02-23")]
        out = fin.detect_subscriptions(mondays)
        assert out["count"] == 1
        assert out["subscriptions"][0]["cadence"] == "weekly"
        assert out["monthly_total"] == 429.0  # 99 * 52 / 12

    def test_yearly_rollup(self):
        txns = [{"date": f"{y}-03-10", "payee": "Insurance",
                 "amount": -12000.0} for y in (2024, 2025, 2026)]
        out = fin.detect_subscriptions(txns)
        assert out["count"] == 1
        sub = out["subscriptions"][0]
        assert sub["cadence"] == "yearly"
        assert sub["monthly_cost"] == 1000.0
        assert sub["next_expected"] == "2027-03-10"

    def test_month_end_clamp(self):
        txns = [{"date": d, "payee": "Rent", "amount": -15000.0} for d in
                ("2026-01-31", "2026-02-28", "2026-03-31")]
        out = fin.detect_subscriptions(txns)
        assert out["count"] == 1
        assert out["subscriptions"][0]["cadence"] == "monthly"

    def test_amount_within_tolerance(self):
        txns = _monthly("Music", [5, 5, 5, 5], 0.0)
        for txn, amt in zip(txns, (-499.0, -505.0, -499.0, -505.0)):
            txn["amount"] = amt
        out = fin.detect_subscriptions(txns)
        assert out["count"] == 1
        assert out["subscriptions"][0]["evidence"].endswith("amount within 2%")

    def test_amount_too_inconsistent_rejected(self):
        txns = _monthly("RandomShop", [5, 5, 5], 0.0)
        for txn, amt in zip(txns, (-499.0, -499.0, -899.0)):
            txn["amount"] = amt
        assert fin.detect_subscriptions(txns)["count"] == 0

    def test_transfers_excluded(self):
        transfers = _monthly("Self Transfer to Savings",
                             [5, 5, 5, 5, 5, 5], -10000.0)
        assert fin.detect_subscriptions(transfers)["count"] == 0
        flagged = _monthly("Rent Move", [5, 5, 5], -9000.0)
        for txn in flagged:
            txn["transfer"] = True
        assert fin.detect_subscriptions(flagged)["count"] == 0

    def test_exact_duplicates_counted_once(self):
        txns = NETFLIX + [dict(NETFLIX[0])]  # one exact duplicate row
        out = fin.detect_subscriptions(txns)
        assert out["count"] == 1
        assert out["subscriptions"][0]["occurrences"] == 6
        assert out["subscriptions"][0]["evidence"].startswith("matched 6 of 6")

    def test_too_few_occurrences(self):
        assert fin.detect_subscriptions(NETFLIX[:2])["count"] == 0

    def test_irregular_payee_not_a_subscription(self):
        txns = [{"date": d, "payee": "Cafe", "amount": -250.0} for d in
                ("2026-01-03", "2026-01-17", "2026-02-02", "2026-03-01")]
        assert fin.detect_subscriptions(txns)["count"] == 0

    def test_extra_one_off_charge_still_detected(self):
        txns = NETFLIX + [{"date": "2026-03-20", "payee": "Netflix",
                           "amount": -199.0}]
        out = fin.detect_subscriptions(txns)
        assert out["count"] == 1
        assert out["subscriptions"][0]["evidence"].startswith("matched 6 of 7")


# ---------------------------------------------------------------------------
# Categorization — closed vocabulary + never overwrite a human
# ---------------------------------------------------------------------------

class TestCategorize:
    CATS = [{"id": "food"}, {"id": "rent"}, {"id": "groceries"}]
    RULES = [{"contains": "swiggy", "category_id": "food"}]

    def test_rule_wins_first(self):
        out = fin.categorize_transaction(
            {"payee": "Swiggy Order #42"}, self.CATS, rules=self.RULES)
        assert out == {"category_id": "food", "source": "rule",
                       "confidence": 1.0}

    def test_rule_with_unknown_category_is_skipped(self):
        out = fin.categorize_transaction(
            {"payee": "Swiggy"}, self.CATS,
            rules=[{"contains": "swiggy", "category_id": "luxury"}])
        assert out["category_id"] is None

    def test_no_match_abstains_null(self):
        out = fin.categorize_transaction({"payee": "Unknown Shop"}, self.CATS)
        assert out == {"category_id": None, "source": None,
                       "confidence": None}

    def test_classifier_valid_answer(self):
        out = fin.categorize_transaction(
            {"payee": "Big Bazaar"}, self.CATS,
            classifier=lambda txn, cats: ("groceries", 0.9))
        assert out == {"category_id": "groceries", "source": "ai",
                       "confidence": 0.9}

    def test_classifier_invented_category_discarded(self):
        # Paperless allowlist: an out-of-vocabulary answer is thrown away.
        out = fin.categorize_transaction(
            {"payee": "Big Bazaar"}, self.CATS,
            classifier=lambda txn, cats: ("luxury", 0.99))
        assert out["category_id"] is None

    def test_classifier_below_confidence_floor_abstains(self):
        low = fin.categorize_transaction(
            {"payee": "Big Bazaar"}, self.CATS,
            classifier=lambda txn, cats: ("groceries", 0.59))
        assert low["category_id"] is None
        edge = fin.categorize_transaction(
            {"payee": "Big Bazaar"}, self.CATS,
            classifier=lambda txn, cats: ("groceries", 0.60))
        assert edge["category_id"] == "groceries"

    def test_classifier_none_abstains(self):
        out = fin.categorize_transaction(
            {"payee": "Big Bazaar"}, self.CATS,
            classifier=lambda txn, cats: None)
        assert out["category_id"] is None

    def test_never_overwrites_locked_human_category(self):
        """THE proof: locked + human-set beats BOTH a matching rule and a
        99%-confident classifier. Automation never fights the owner."""
        txn = {"payee": "Swiggy Order", "category_id": "groceries",
               "locked": True}
        out = fin.categorize_transaction(
            txn, self.CATS, rules=self.RULES,
            classifier=lambda t, cats: ("food", 0.99))
        assert out == {"category_id": "groceries", "source": "human",
                       "confidence": 1.0}
        # And across a batch, the locked row is the one that never changes.
        batch = [txn, {"payee": "Swiggy Again"}]
        results = [fin.categorize_transaction(t, self.CATS, rules=self.RULES)
                   for t in batch]
        assert results[0]["category_id"] == "groceries"
        assert results[1]["category_id"] == "food"


# ---------------------------------------------------------------------------
# Price watch — threshold discipline
# ---------------------------------------------------------------------------

class TestPriceWatch:
    def test_exact_threshold_alerts(self, tmp_path):
        store = tmp_path / "w.json"
        fin.watch_set(store, "gpu", 100.0)
        out = fin.watch_check(store, "gpu", 105.0)
        assert out["alert"] is True
        assert out["change_pct"] == 5.0

    def test_sub_threshold_recorded_silently(self, tmp_path):
        store = tmp_path / "w.json"
        fin.watch_set(store, "gpu", 1000.0)
        out = fin.watch_check(store, "gpu", 1030.0)
        assert out["alert"] is False
        assert out["change_pct"] == 3.0
        state = fin.watch_list(store)["watches"][0]
        assert state["last_price"] == 1030.0       # recorded…
        assert state["reference_price"] == 1000.0  # …but baseline unmoved

    def test_slow_drift_accumulates_to_alert(self, tmp_path):
        store = tmp_path / "w.json"
        fin.watch_set(store, "gpu", 1000.0)
        assert fin.watch_check(store, "gpu", 1030.0)["alert"] is False
        out = fin.watch_check(store, "gpu", 1060.0)  # +6% vs baseline
        assert out["alert"] is True
        assert fin.watch_list(store)["watches"][0]["reference_price"] == 1060.0

    def test_drop_alerts_and_rebaselines(self, tmp_path):
        store = tmp_path / "w.json"
        fin.watch_set(store, "gpu", 1000.0)
        out = fin.watch_check(store, "gpu", 940.0)
        assert out["alert"] is True and out["change_pct"] == -6.0
        # After the alert, small moves vs the NEW baseline stay silent.
        assert fin.watch_check(store, "gpu", 950.0)["alert"] is False

    def test_custom_threshold(self, tmp_path):
        store = tmp_path / "w.json"
        fin.watch_set(store, "gpu", 1000.0, threshold_pct=10.0)
        assert fin.watch_check(store, "gpu", 1060.0)["alert"] is False

    def test_unknown_watch_is_an_honest_error(self, tmp_path):
        with pytest.raises(ValueError):
            fin.watch_check(tmp_path / "w.json", "ghost", 1.0)

    def test_handle_roundtrip_and_persistence(self, ctx, tmp_path):
        out = fin.handle("price_watch_set",
                         {"id": "ssd", "price": 5000.0}, ctx)
        assert out["reference_price"] == 5000.0
        out = fin.handle("price_watch_check",
                         {"id": "ssd", "current_price": 5100.0}, ctx)
        assert out["alert"] is False
        listed = fin.handle("price_watch_list", {}, ctx)
        assert [w["id"] for w in listed["watches"]] == ["ssd"]
        # State survives on disk (fresh load sees the same watch).
        assert (tmp_path / "price_watches.json").exists()
        assert fin.watch_list(tmp_path / "price_watches.json")["watches"]


# ---------------------------------------------------------------------------
# End-to-end through the real registry pipeline
# ---------------------------------------------------------------------------

class TestRegistryDispatch:
    @pytest.fixture()
    def reg(self, tmp_path):
        skills = tmp_path / "skills"
        skills.mkdir()
        shutil.copytree(SKILL_DIR, skills / "finance")
        data = tmp_path / "data"
        data.mkdir()
        registry = SkillRegistry(skills, data)
        registry.discover()
        return registry

    def _skill_ctx(self, tmp_path):
        jail = tmp_path / "jail"
        jail.mkdir(exist_ok=True)
        return SkillContext(skill_name="finance",
                            capabilities=["fs.read", "fs.write"],
                            jail_dir=str(jail))

    def test_discovery_clean_and_quarantined_until_approved(self, reg):
        rec = reg._records["finance"]
        assert rec.load_error is None
        assert reg.quarantine() == ["finance"]

    def test_dispatch_detect_and_watch(self, reg, tmp_path):
        ctx = self._skill_ctx(tmp_path)
        out = reg.dispatch("finance_detect_subscriptions",
                           {"transactions": NETFLIX}, ctx, ALLOW_ALL)
        assert out["ok"] is False
        assert out["error"]["code"] == "skill_quarantined"

        reg.approve("finance")
        out = reg.dispatch("finance_detect_subscriptions",
                           {"transactions": NETFLIX}, ctx, ALLOW_ALL)
        assert out["ok"] is True
        assert out["result"]["subscriptions"][0]["evidence"] == \
            "matched 6 of 6, ±1 day, exact amount"

        out = reg.dispatch("price_watch_set",
                           {"id": "gpu", "price": 25000.0}, ctx, ALLOW_ALL)
        assert out["ok"] is True
        out = reg.dispatch("price_watch_check",
                           {"id": "gpu", "current_price": 24000.0},
                           ctx, ALLOW_ALL)
        assert out["ok"] is True
        assert out["result"]["alert"] is False  # -4% < 5% threshold

        out = reg.dispatch("finance_categorize",
                           {"transaction": {"payee": "Swiggy"},
                            "categories": [{"id": "food"}],
                            "rules": [{"contains": "swiggy",
                                       "category_id": "food"}]},
                           ctx, ALLOW_ALL)
        assert out["ok"] is True
        assert out["result"]["category_id"] == "food"
        assert out["result"]["source"] == "rule"
