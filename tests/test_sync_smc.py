"""Regression tests for the SMC-to-daily_smc persistence mapping."""

import unittest

from src.sync_smc import build_daily_smc_records


def bar(day, high, low, close, open_=None):
    return {
        "market": "twse",
        "stock_id": "2330",
        "trade_date": f"2026-01-{day:02d}",
        "open": close if open_ is None else open_,
        "high": high,
        "low": low,
        "close": close,
    }


class SMCSyncMappingTests(unittest.TestCase):
    def test_daily_summary_maps_pivots_fvg_and_trend(self):
        rows = [
            bar(1, 10, 8, 9), bar(2, 14, 11, 13), bar(3, 16, 12, 15),
            bar(4, 11, 7, 8), bar(5, 10, 5, 7),
        ]
        records = build_daily_smc_records(rows, pivot_left=2, pivot_right=2)
        self.assertEqual(len(records), len(rows))
        self.assertEqual(records[2]["fvg_type"], "bullish")
        self.assertEqual(records[2]["fvg_low"], 10)
        self.assertEqual(records[2]["fvg_high"], 12)
        self.assertEqual(records[4]["swing_high"], 16)
        self.assertEqual(records[4]["trend_direction"], 0)

    def test_flags_default_false_and_nullable_zones(self):
        records = build_daily_smc_records([bar(1, 10, 5, 8)])
        row = records[0]
        for key in (
            "bos_bullish", "bos_bearish", "choch_bullish", "choch_bearish",
            "liquidity_sweep_high", "liquidity_sweep_low",
        ):
            self.assertFalse(row[key])
        self.assertIsNone(row["order_block_type"])
        self.assertIsNone(row["fvg_type"])

    def test_sweep_maps_to_daily_columns(self):
        rows = [
            bar(1, 10, 6, 8), bar(2, 12, 7, 9), bar(3, 15, 8, 12),
            bar(4, 11, 7, 8), bar(5, 10, 6, 7),
            bar(6, 16, 8, 14), bar(7, 17, 9, 16),
        ]
        records = build_daily_smc_records(rows, pivot_left=2, pivot_right=2)
        self.assertTrue(records[5]["liquidity_sweep_high"])


if __name__ == "__main__":
    unittest.main()
