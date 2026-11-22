"""Pure synthetic tests: recorded events are never a complete dividend history."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import os
from pathlib import Path
import subprocess
import sys
import unittest

from scripts.twse_2022_reduction_only_240_sma_readonly import SMA_SCOPE
from scripts.twse_2022_two_stock_action_coverage_readonly import (
    EVIDENCE_SCOPE, SQL_ACTIONS, SQL_COUNT, MAX_ROWS,
    assess_recorded_actions, validate_prior_sma_report,
)


def prior_evidence():
    return {
        "schema_version": 1,
        "scope": SMA_SCOPE,
        "live_model_release_decision": "BLOCKED",
        "event_only_240_sma_stock_count": 2,
        "production_neon_writes": 0,
        "line_messages_sent": 0,
        "complete_all_corporate_actions_adjusted": False,
        "point_in_time_historical_listed_roster_proven": False,
        "real_2022_capital_reduction_halt_days_left_without_price": 14,
        "stock_capital_reduction_only_research_witnesses": [
            {
                "stock_id": sid,
                "last240_first_real_stock_session": "2021-12-30",
                "last240_final_real_stock_session": "2022-12-30",
                "last240_real_traded_days": 240,
                "2022_cash_reduction_only_decimal_sma240_computed_in_ram": True,
                "fully_adjusted_sma240_release_approved": False,
            }
            for sid in ("2327", "2603")
        ],
    }


def action(*, stock="2327", kind="CASH_DIVIDEND", day=date(2022, 8, 11),
           verified=True, source_event_id="source-event-01", cash="5",
           captured=datetime(2026, 11, 23, tzinfo=timezone.utc)):
    return {
        "market": "twse", "stock_id": stock, "ex_date": day,
        "action_type": kind,
        "price_factor": Decimal("0.96"),
        "share_factor": Decimal("1.0"),
        "cash_amount": Decimal(cash) if cash is not None else None,
        "stock_amount": None,
        "source_event_id": source_event_id,
        "source": "TWSE_TEST_OFFLINE",
        "verified": verified,
        "created_at": captured,
    }


class FrozenTwoEventInventoryOfflineTests(unittest.TestCase):
    def test_two_empty_database_event_sets_never_mean_no_dividends(self):
        result = assess_recorded_actions(prior_evidence(), [], total_rows=0)
        self.assertEqual(result["scope"], EVIDENCE_SCOPE)
        self.assertEqual(result["actual_readonly_stored_action_rows"], 0)
        self.assertFalse(result["zero_stored_events_may_be_interpreted_as_no_dividends"])
        self.assertFalse(result["independently_complete_historical_dividends_and_splits"])
        self.assertFalse(result["cash_reduction_only_sma240_is_complete_total_return"])
        self.assertEqual(result["live_model_release_decision"], "BLOCKED")
        self.assertEqual(result["production_neon_writes"], 0)
        for stock in result["per_stock_action_coverage"]:
            self.assertFalse(stock["no_stored_event_means_no_real_dividend"])
            self.assertEqual(stock["stored_event_rows_in_proven_240_traded_day_window"], 0)

    def test_recorded_cash_and_non_cash_events_are_counted_not_approved(self):
        events = [
            action(cash="5"),
            action(stock="2603", kind="STOCK_SPLIT", day=date(2022, 9, 1),
                   cash=None, source_event_id="event-split"),
            action(stock="2327", kind="CASH_CAPITAL_REDUCTION",
                   day=date(2022, 10, 31),
                   cash="2.0407502943",source_event_id="event-reduction",
                   verified=False),
        ]
        result = assess_recorded_actions(prior_evidence(), events,
                                         total_rows=len(events))
        by = {x["stock_id"]: x for x in result["per_stock_action_coverage"]}
        self.assertEqual(by["2327"]["stored_event_rows_in_proven_240_traded_day_window"], 2)
        self.assertEqual(by["2327"]["stored_non_cash_reduction_event_rows"], 1)
        self.assertEqual(by["2327"]["stored_verified_event_rows"], 1)
        self.assertEqual(by["2327"]["stored_unverified_event_rows"], 1)
        self.assertEqual(by["2327"]["stored_cash_dividend_rows"], 1)
        self.assertEqual(by["2327"]["stored_events_first_captured_after_ex_date"], 2)
        self.assertEqual(by["2603"]["stored_non_cash_reduction_event_rows"], 1)
        self.assertEqual(by["2603"]["stored_cash_dividend_rows"], 0)
        self.assertFalse(by["2603"]["full_corporate_action_and_dividend_history_verified"])
        self.assertEqual(result["actual_readonly_stored_action_rows"], 3)

    def test_identical_economics_from_multiple_source_ids_not_doubly_certified(self):
        row = action()
        copy = dict(row, source_event_id="second-source-id")
        report = assess_recorded_actions(prior_evidence(), [row, copy],
                                         total_rows=2)
        stock = report["per_stock_action_coverage"][0]
        self.assertEqual(stock["stored_event_rows_in_proven_240_traded_day_window"], 2)
        self.assertEqual(stock["distinct_stored_economic_events"], 1)
        self.assertEqual(stock["same_stock_date_type_conflicting_economic_terms"], 0)
        self.assertFalse(stock["any_verified_stored_event_proves_complete_history"])

    def test_same_date_type_economic_conflicts_flagged(self):
        row = action()
        copy = dict(row, source_event_id="second-source-id",
                    price_factor=Decimal("0.91"))
        report = assess_recorded_actions(prior_evidence(), [row, copy],
                                         total_rows=2)
        self.assertEqual(report["per_stock_action_coverage"][0][
            "same_stock_date_type_conflicting_economic_terms"], 1)
        self.assertFalse(report["validated_walkforward_total_return_labels"])

    def test_missing_cash_or_capture_is_explicitly_unverified(self):
        row = action(cash=None, captured=None, verified=False)
        r = assess_recorded_actions(prior_evidence(), [row], total_rows=1)
        a = r["per_stock_action_coverage"][0]
        self.assertEqual(a["stored_cash_dividend_rows_missing_amount"], 1)
        self.assertEqual(a["stored_events_without_capture_timestamp"], 1)
        self.assertEqual(a["stored_unverified_event_rows"], 1)
        self.assertFalse(a["source_capture_date_equals_original_issuer_publication_time"])

    def test_invalid_prior_evidence_is_refused_before_query(self):
        for key, val in (
            ("scope", "WRONG"), ("live_model_release_decision", "APPROVED"),
            ("event_only_240_sma_stock_count", 1), ("production_neon_writes", 1),
            ("complete_all_corporate_actions_adjusted", True),
        ):
            src = prior_evidence()
            src[key] = val
            with self.assertRaises(ValueError, msg=key):
                validate_prior_sma_report(src)
        src = prior_evidence()
        src["stock_capital_reduction_only_research_witnesses"][0][
            "last240_first_real_stock_session"] = "2021-12-29"
        with self.assertRaises(ValueError):
            validate_prior_sma_report(src)

    def test_truncated_wrong_stock_duplicate_invalid_action_refused(self):
        valid = action()
        for rows, n in (
            ([valid], 2), ([valid], MAX_ROWS+1),
            ([dict(valid, stock_id="1589")], 1),
            ([dict(valid, ex_date=date(2023,1,3))], 1),
            ([dict(valid, price_factor=Decimal("NaN"))], 1),
            ([dict(valid, created_at=datetime(2022, 8, 11))], 1),
            ([valid, dict(valid)], 2),
        ):
            with self.assertRaises(ValueError):
                assess_recorded_actions(prior_evidence(), rows, total_rows=n)

    def test_readonly_sql_only_select_and_fixed_two_stock_window(self):
        for query in (SQL_COUNT, SQL_ACTIONS):
            self.assertTrue(query.lstrip().upper().startswith("SELECT"))
            self.assertIn("market='twse'", query)
            self.assertIn("stock_id = ANY", query)
            self.assertIn("ex_date >=", query)
            self.assertIn("ex_date <=", query)
            self.assertNotIn("INSERT INTO", query.upper())
            self.assertNotIn("DELETE FROM", query.upper())
            self.assertNotIn("UPDATE public", query.upper())

    def test_help_without_keys_or_neon_credentials(self):
        repo = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env.pop("DATABASE_URL", None)
        env.pop("PYTHONPATH", None)
        env.pop("STOCK_ARCHIVE_KEY_HEX", None)
        p = subprocess.run(
            [sys.executable, "-m",
             "scripts.twse_2022_two_stock_action_coverage_readonly", "--help"],
            cwd=repo, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("--sma-report", p.stdout)
        self.assertIn("--out", p.stdout)


if __name__ == "__main__":
    unittest.main()
