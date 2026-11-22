"""Pure synthetic tests for read-only AES × Neon TWSE 2022 cohort bridge."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import unittest

from scripts.twse_2022_aes_neon_readonly_240_panel import (
    FROZEN_STOCKS, _same_price, reconcile, SQL_NEON_DAYS, SQL_NEON_PANEL,
)
from tests.test_twse_2022_aes_factor_readiness import fake_row, sessions


def two_stock_panel(dates, names=("1103", "2330"), offset=0):
    return [
        fake_row(day, sid, i + offset)
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
        result = reconcile(two_stock_panel(local), two_stock_panel(other, offset=152),
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

    def test_other_official_twse_stock_day_fills_neon_primary_source_gap(self):
        days = sessions(246)
        local = two_stock_panel(days[:162])
        primary = two_stock_panel(days[162:], names=("1103",), offset=162)
        secondary = [
            dict(fake_row(d, "2330", idx + 162), source="TWSE_STOCK_DAY")
            for idx, d in enumerate(days[162:])
        ]
        secondary.append(dict(
            fake_row(days[161], "2330", 161), source="TWSE_STOCK_DAY"
        ))
        report = reconcile(local, primary + secondary, days[162:],
                           stocks=("1103", "2330"))
        self.assertEqual(report["neon_source_sessions"], 84)
        self.assertEqual(report["unique_observed_2022_source_sessions"], 246)
        self.assertEqual(report["neon_frozen_cohort_source_counts"],
                         {"TWSE_MI_INDEX_ALLBUT0999": 84, "TWSE_STOCK_DAY": 85})
        self.assertEqual(report["exact_duplicate_stock_day_ohlcv_matches"], 1)
        self.assertEqual(report["frozen_stocks_with_complete_last_240_source_sessions"], 2)
        self.assertEqual(report["live_model_release_decision"], "BLOCKED")
        self.assertEqual(report["neon_write_operations"], 0)

    def test_secondary_official_source_must_match_local_aes_stock_day(self):
        d = sessions(3)[-1]
        local = [fake_row(d, "2330", 2)]
        secondary = dict(fake_row(d, "2330", 2), source="TWSE_STOCK_DAY")
        secondary["volume"] += 1
        with self.assertRaisesRegex(ValueError, "discrepancy"):
            reconcile(local, [secondary], [], stocks=("2330",))

    def test_secondary_official_source_cannot_invent_unseen_market_day(self):
        d = sessions(1)[0]
        secondary = dict(fake_row(d, "2330", 0), source="TWSE_STOCK_DAY")
        with self.assertRaisesRegex(ValueError, "absent market source day"):
            reconcile([], [secondary], [], stocks=("2330",))
        secondary["source"] = "FAKE_OFFICIAL"
        with self.assertRaisesRegex(ValueError, "provenance"):
            reconcile([], [secondary], [], stocks=("2330",))

    def test_missing_last_day_for_one_stock_refuses_its_sma(self):
        days = sessions(241)
        local = two_stock_panel(days[:160])
        neon = two_stock_panel(days[160:])
        neon = [r for r in neon if not (
            r["stock_id"] == "2330" and r["trade_date"] == days[-1])]
        result = reconcile(local, neon, days[160:], stocks=("1103", "2330"))
        self.assertEqual(result["frozen_stocks_with_complete_last_240_source_sessions"], 1)
        self.assertEqual(result["raw_12_factor_vectors_spotchecked"], 1)
        self.assertTrue(result["sma240_stock_day_gap_diagnostics_available"])
        self.assertEqual(result["missing_sma240_stock_count"], 1)
        self.assertEqual(result["missing_sma240_stock_day_details"], [{
            "stock_id": "2330",
            "missing_observed_trade_day_count": 1,
            "missing_observed_trade_dates": [days[-1].isoformat()],
            "reason_unresolved_without_historical_listing_and_source_audit": True,
            "source_refetch_or_neon_write_authorized": False,
        }])
        self.assertTrue(
            result["missing_stock_day_not_independently_verified_as_exchange_or_listing_gap"])
        self.assertEqual(result["neon_write_operations"], 0)

    def test_two_missing_stocks_are_limited_to_final_240_observed_sessions(self):
        dates = sessions(246)
        panel = two_stock_panel(dates, names=("1103", "2330", "2454"))
        panel = [r for r in panel if not (
            (r["stock_id"] == "2330" and r["trade_date"] == dates[-1])
            or (r["stock_id"] == "2454" and r["trade_date"] == dates[-3])
            or (r["stock_id"] == "2454" and r["trade_date"] == dates[0])
        )]
        report = reconcile(panel, [], [], stocks=("1103", "2330", "2454"))
        self.assertEqual(report["frozen_stocks_with_complete_last_240_source_sessions"], 1)
        self.assertEqual(report["missing_sma240_stock_count"], 2)
        gaps = report["missing_sma240_stock_day_details"]
        self.assertEqual([g["stock_id"] for g in gaps], ["2330", "2454"])
        self.assertEqual(gaps[0]["missing_observed_trade_dates"], [dates[-1].isoformat()])
        self.assertEqual(gaps[1]["missing_observed_trade_dates"], [dates[-3].isoformat()])
        self.assertEqual(report["neon_write_operations"], 0)
        self.assertEqual(report["live_model_release_decision"], "BLOCKED")

    def test_short_market_calendar_does_not_invent_stock_day_gaps(self):
        dates = sessions(239)
        report = reconcile(two_stock_panel(dates), [], [],
                           stocks=("1103", "2330"))
        self.assertEqual(report["remaining_observed_sessions_to_240"], 1)
        self.assertFalse(report["sma240_stock_day_gap_diagnostics_available"])
        self.assertIsNone(report["missing_sma240_stock_count"])
        self.assertEqual(report["missing_sma240_stock_day_details"], [])
        self.assertEqual(report["frozen_stocks_with_complete_last_240_source_sessions"], 0)
        self.assertEqual(report["live_model_release_decision"], "BLOCKED")

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

    def test_neon_pooler_connect_has_no_startup_gucs_and_sets_local_timeout(self):
        # Pooled Neon rejects 'statement_timeout' within libpq startup options.
        # Keep the read-only transaction guard and short timeout at SQL level.
        from unittest.mock import patch
        from types import SimpleNamespace
        import sys
        from scripts.twse_2022_aes_neon_readonly_240_panel import (
            _read_neon_2022_frozen_panel,
        )

        statements = []
        connection_args = []
        class FakeCursor:
            description = None
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def execute(self, sql, params=None):
                statements.append((sql.strip(), params))
                if sql.strip() == SQL_NEON_PANEL.strip():
                    self.description = [
                        SimpleNamespace(name=n) for n in
                        ("market", "stock_id", "trade_date", "open", "high",
                         "low", "close", "volume", "turnover", "price_change",
                         "transactions", "source", "retrieved_at")
                    ]
            def fetchall(self):
                return []

        class FakeConnection:
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def cursor(self):
                return FakeCursor()
            def rollback(self):
                statements.append(("ROLLBACK", None))

        def connect(*args, **kwargs):
            connection_args.append((args, kwargs))
            return FakeConnection()

        with patch.dict(sys.modules, {"psycopg": SimpleNamespace(connect=connect)}):
            with patch.dict("os.environ", {"DATABASE_URL": "postgresql://fake"}, clear=False):
                dates, rows = _read_neon_2022_frozen_panel()

        self.assertEqual((dates, rows), ([], []))
        self.assertEqual(len(connection_args), 1)
        self.assertEqual(connection_args[0][1], {"connect_timeout": 15})
        self.assertEqual([sql for sql, _ in statements],
                         ["SET TRANSACTION READ ONLY",
                          "SET LOCAL statement_timeout = '90s'",
                          SQL_NEON_DAYS.strip(),
                          SQL_NEON_PANEL.strip(),
                          "ROLLBACK"])
        self.assertEqual(statements[3][1], (list(FROZEN_STOCKS),))

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
