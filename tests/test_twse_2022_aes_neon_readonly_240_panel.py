"""Pure synthetic tests for read-only AES × Neon TWSE 2022 cohort bridge."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import unittest

from scripts.twse_2022_aes_neon_readonly_240_panel import (
    FROZEN_STOCKS, _same_price, reconcile, SQL_NEON_DAYS, SQL_NEON_PANEL,
)
from tests.test_twse_2022_aes_factor_readiness import fake_row, sessions


def two_stock_panel(dates, names=("1103", "2330")):
    return [
        fake_row(day, sid, i)
        for i, day in enumerate(dates)
        for sid in names
    ]


class ReadonlyJoinTests(unittest.TestCase):
    def test_162_local_plus_84_new_neon_days_supports_real_240_window(self):
        market_days = sessions(246)
        local_days = market_days[:162]
        neon_days = market_days[162:]
        result = reconcile(
            two_stock_panel(local_days), two_stock_panel(neon_days),
            neon_days, stocks=("1103", "2330"),
        )
        self.assertEqual(result["local_2022_source_sessions"], 162)
        self.assertEqual(result["neon_source_sessions"], 84)
        self.assertEqual(result["overlapping_source_sessions"], 0)
        self.assertEqual(result["unique_observed_2022_source_sessions"], 246)
        self.assertEqual(result["remaining_observed_sessions_to_240"], 0)
        self.assertEqual(result["frozen_stocks_with_complete_last_240_source_sessions"], 2)
        self.assertEqual(result["exact_decimal_sma240_computed_in_ram"], 2)
        self.assertEqual(result["raw_12_factor_vectors_spotchecked"], 2)
        self.assertEqual(result["causal_prefix_parity_checks"], 2)
        self.assertEqual(len(result["private_result_fingerprint_sha256"]), 64)
        self.assertEqual(result["neon_write_operations"], 0)
        self.assertEqual(result["local_persistent_factor_rows"], 0)
        self.assertFalse(result["dividends_splits_or_total_return_adjusted"])
        self.assertFalse(result["complete_historical_exchange_calendar_independently_verified"])
        self.assertEqual(result["live_model_release_decision"], "BLOCKED")

    def test_162_plus_84_with_partial_overlap_is_not_false_246(self):
        days = sessions(246)
        local = days[:162]
        # Ten official source dates overlap; only 236 unique market days.
        other = days[152:236]
        result = reconcile(two_stock_panel(local), two_stock_panel(other),
                           other, stocks=("1103", "2330"))
        self.assertEqual(result["overlapping_source_sessions"], 10)
        self.assertEqual(result["unique_observed_2022_source_sessions"], 236)
        self.assertEqual(result["remaining_observed_sessions_to_240"], 4)
        self.assertEqual(result["exact_duplicate_stock_day_ohlcv_matches"], 20)
        self.assertEqual(result["frozen_stocks_with_complete_last_240_source_sessions"], 0)
        self.assertIsNone(result["private_result_fingerprint_sha256"])

    def test_conflicting_price_on_same_date_fails_closed(self):
        dates = sessions(5)
        local = two_stock_panel(dates)
        neon = [dict(local[0])]
        neon[0]["close"] += Decimal("0.01")
        with self.assertRaisesRegex(ValueError, "discrepancy"):
            reconcile(local, neon, [dates[0]], stocks=("1103", "2330"))

    def test_missing_last_day_for_one_stock_refuses_its_sma(self):
        days = sessions(241)
        local = two_stock_panel(days[:160])
        neon = two_stock_panel(days[160:])
        neon = [r for r in neon if not (
            r["stock_id"] == "2330" and r["trade_date"] == days[-1])]
        result = reconcile(local, neon, days[160:], stocks=("1103", "2330"))
        self.assertEqual(result["frozen_stocks_with_complete_last_240_source_sessions"], 1)
        self.assertEqual(result["raw_12_factor_vectors_spotchecked"], 1)
        self.assertEqual(result["neon_write_operations"], 0)

    def test_duplicate_neon_stock_day_refused(self):
        days = sessions(4)
        record = fake_row(days[0], "2330", 0)
        with self.assertRaisesRegex(ValueError, "Duplicate database"):
            reconcile([], [record, record], days, stocks=("2330",))

    def test_unapproved_sid_or_invalid_neon_market_day_refused(self):
        days = sessions(4)
        with self.assertRaisesRegex(ValueError, "frozen"):
            reconcile([], [], days, stocks=("1589",))
        with self.assertRaisesRegex(ValueError, "absent market"):
            reconcile([], [fake_row(days[0], "2330", 0)],
                      [days[1]], stocks=("2330",))
        with self.assertRaisesRegex(ValueError, "Duplicate Neon"):
            reconcile([], [], [days[0], days[0]], stocks=("2330",))
        with self.assertRaisesRegex(ValueError, "Invalid Neon"):
            reconcile([], [], [date(2023, 1, 3)], stocks=("2330",))

    def test_aes_source_changed_between_passes_refused(self):
        days = sessions(4)
        rows = two_stock_panel(days)
        mismatch = {"authenticated_source_rows": len(rows)+1,
                    "authentic_distinct_2022_source_sessions":len(days)}
        with self.assertRaisesRegex(ValueError, "changed"):
            reconcile(rows, [], [], stocks=("1103", "2330"),
                      local_audit=mismatch)

    def test_raw_same_price_and_readonly_sql_contract(self):
        original = fake_row(sessions(1)[0], "2330", 0)
        equal = dict(original)
        equal["retrieved_at"] = "later source fetch timestamp"
        self.assertTrue(_same_price(original, equal))
        equal["turnover"] += Decimal("1")
        self.assertFalse(_same_price(original, equal))
        for statement in (SQL_NEON_DAYS, SQL_NEON_PANEL):
            self.assertTrue(statement.strip().upper().startswith("SELECT"))
            self.assertNotIn("UPDATE ", statement.upper())
            self.assertNotIn("DELETE ", statement.upper())
            self.assertNotIn("INSERT ", statement.upper())
        self.assertEqual(len(FROZEN_STOCKS), 20)
        self.assertNotIn("1589", FROZEN_STOCKS)


if __name__ == "__main__":
    unittest.main()
