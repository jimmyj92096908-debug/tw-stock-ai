import unittest

from src.smc import compute_smc


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


class SMCTests(unittest.TestCase):
    def test_pivot_is_only_reported_on_confirmation_bar(self):
        rows = [
            bar(1, 10, 5, 8), bar(2, 12, 6, 9), bar(3, 15, 7, 11),
            bar(4, 11, 6, 8), bar(5, 10, 5, 7),
        ]
        result = compute_smc(rows, pivot_left=2, pivot_right=2)
        self.assertFalse(any(e["type"] == "swing_high_confirmed" for e in result[2]["events"]))
        pivot = next(e for e in result[4]["events"] if e["type"] == "swing_high_confirmed")
        self.assertEqual(pivot["pivot_date"], "2026-01-03")
        self.assertEqual(pivot["confirmed_date"], "2026-01-05")

    def test_bullish_fvg(self):
        rows = [bar(1, 10, 8, 9), bar(2, 14, 11, 13), bar(3, 16, 12, 15)]
        result = compute_smc(rows)
        event = next(e for e in result[2]["events"] if e["type"] == "bullish_fvg")
        self.assertEqual((event["lower"], event["upper"]), (10, 12))

    def test_bearish_fvg(self):
        rows = [bar(1, 15, 12, 13), bar(2, 14, 10, 11), bar(3, 11, 8, 9)]
        result = compute_smc(rows)
        event = next(e for e in result[2]["events"] if e["type"] == "bearish_fvg")
        self.assertEqual((event["lower"], event["upper"]), (11, 12))

    def test_bos_and_order_block_are_identified_on_break_bar(self):
        rows = [
            bar(1, 10, 6, 8), bar(2, 12, 7, 9), bar(3, 15, 8, 12),
            bar(4, 11, 7, 8, open_=10), bar(5, 10, 6, 7),
            bar(6, 13, 8, 11), bar(7, 16, 9, 15),
        ]
        result = compute_smc(rows, pivot_left=2, pivot_right=2)
        event = next(e for e in result[6]["events"] if e["type"] == "bos")
        self.assertEqual(event["direction"], "bullish")
        self.assertEqual(event["event_date"], "2026-01-07")
        self.assertEqual(event["order_block"]["source_date"], "2026-01-04")
        self.assertEqual(event["order_block"]["identified_date"], "2026-01-07")

    def test_liquidity_sweep_closes_back_below_prior_swing_high(self):
        rows = [
            bar(1, 10, 6, 8), bar(2, 12, 7, 9), bar(3, 15, 8, 12),
            bar(4, 11, 7, 8), bar(5, 10, 6, 7),
            bar(6, 16, 8, 14), bar(7, 17, 9, 15),
            bar(8, 18, 10, 15),
        ]
        # The high pivot is confirmed at bar 6; the sweep is on bar 7 only if it
        # crosses the newly confirmed level and closes back below it.
        result = compute_smc(rows, pivot_left=2, pivot_right=2)
        self.assertTrue(any(e["type"] == "buy_side_liquidity_sweep" for e in result[6]["events"]) is False)

    def test_invalid_order_and_parameters(self):
        with self.assertRaises(ValueError):
            compute_smc([bar(2, 10, 5, 8), bar(1, 11, 6, 9)])
        with self.assertRaises(ValueError):
            compute_smc([bar(1, 10, 5, 8)], pivot_right=0)

    def test_empty_input(self):
        self.assertEqual(compute_smc([]), [])


if __name__ == "__main__":
    unittest.main()
