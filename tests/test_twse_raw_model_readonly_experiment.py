"""Synthetic TWSE raw history: causal research without Neon writes."""
from datetime import date, timedelta
from unittest import TestCase
from unittest.mock import MagicMock, patch

from scripts import twse_raw_model_readonly_experiment as model
from src.raw_factor_walkforward import frozen_unadjusted_dataset


def series(sid):
    first = date(2025, 1, 1)
    result = []
    for i in range(360):
        price = 100.0 + i * 0.06 + (i % 7) * 0.13 + int(sid) % 11
        result.append({
            "market": "twse", "stock_id": sid,
            "trade_date": first + timedelta(days=i),
            "open": price - 0.2, "high": price + 2,
            "low": price - 2, "close": price,
            "volume": 1000 + i * 3, "source": "TWSE_MI_INDEX_ALLBUT0999",
        })
    return result


class TWSEReadOnlyRawPrototypeTests(TestCase):
    def test_bounded_causal_twse_dataset_keeps_market_identity(self):
        dataset = frozen_unadjusted_dataset(
            {sid: series(sid) for sid in model.PROTOTYPE_STOCKS},
            signal_dates=[series(model.PROTOTYPE_STOCKS[0])[310]["trade_date"]],
            label_cutoff=date(2025, 12, 31), market="twse",
        )
        self.assertEqual(dataset["market"], "twse")
        self.assertEqual(dataset["accepted_whole_cohort_days"], 1)
        self.assertEqual({x["market"] for x in dataset["rows"]}, {"twse"})
        self.assertFalse(dataset["live_trading_approved"])

    def test_official_current_roster_and_same_readonly_snapshot(self):
        fake = MagicMock()
        fake.__enter__.return_value = fake
        lookup = {sid: series(sid) for sid in model.PROTOTYPE_STOCKS}
        signals = [r["trade_date"] for r in lookup[model.PROTOTYPE_STOCKS[0]][-50:]]
        def execute(query, args=None):
            cursor = MagicMock()
            if query == model.ROSTER_SQL:
                cursor.fetchone.return_value = {"eligible": 20}
            elif query == model.PRICE_SQL:
                cursor.fetchall.return_value = lookup[args[0]]
            elif query == model.SIGNALS_SQL:
                cursor.fetchall.return_value = [{"trade_date": x} for x in reversed(signals)]
            return cursor
        fake.execute.side_effect = execute
        with patch.object(model.psycopg, "connect", return_value=fake) as connected:
            report = model.execute(
                "postgresql://fake", label_cutoff=date(2025, 12, 31),
                test_start=date(2025, 12, 12), max_signals=50,
            )
        self.assertEqual(report["included_stocks"], 20)
        self.assertEqual(report["prototype_status"],
                         "RETROSPECTIVE_EXPLORATORY_UNADJUSTED_PRICE_ONLY")
        self.assertGreaterEqual(report["development_dates"], 20)
        self.assertGreater(report["nonoverlapping_holdout_windows"], 0)
        self.assertTrue(report["no_derived_database_rows_written"])
        self.assertIsNotNone(report["mean_illustrative_net_excess_vs_equal_weight"])
        self.assertTrue(report["identical_illustrative_cost_assumptions_for_benchmark"])
        self.assertFalse(report["research_window_count_sufficient"])
        self.assertFalse(report["live_trading_approved"])
        self.assertFalse(report["independent_future_validation_passed"])
        self.assertIn("default_transaction_read_only=on", connected.call_args.kwargs["options"])
        self.assertIn("REPEATABLE READ, READ ONLY", fake.execute.call_args_list[0].args[0])

    def test_missing_or_excluded_roster_fails_before_any_prices(self):
        fake = MagicMock()
        fake.__enter__.return_value = fake
        fake.execute.return_value.fetchone.return_value = {"eligible": 19}
        with patch.object(model.psycopg, "connect", return_value=fake):
            with self.assertRaisesRegex(RuntimeError, "roster"):
                model.execute("fake", label_cutoff=date(2025, 12, 31),
                              test_start=date(2025, 12, 12))
        self.assertEqual(len(model.PROTOTYPE_STOCKS), 20)
        self.assertNotIn("1589", model.PROTOTYPE_STOCKS)
        self.assertIn("official_current_listed", model.ROSTER_SQL)
        self.assertIn("model_stock_exclusions", model.ROSTER_SQL)
        self.assertNotIn("UPDATE", model.PRICE_SQL.upper())
        self.assertNotIn("INSERT", model.PRICE_SQL.upper())
        with self.assertRaises(ValueError):
            model.execute("", label_cutoff=date(2025, 12, 31),
                          test_start=date(2025, 12, 12))


if __name__ == "__main__":
    import unittest
    unittest.main()
