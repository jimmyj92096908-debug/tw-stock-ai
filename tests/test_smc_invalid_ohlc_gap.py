import unittest

from src.smc_indicators import compute_smc


def rows(count=12):
    result = []
    for i in range(count):
        close = 100 + i
        result.append({
            "market": "tpex",
            "stock_id": "1259",
            "trade_date": f"2026-01-{i + 1:02d}",
            "open": close - 0.5,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 1000,
        })
    return result


class SMCInvalidOHLCGapTests(unittest.TestCase):
    def test_invalid_ohlc_day_has_no_smc_events_and_resets_structure(self):
        source = rows()
        source[6].update(open=None, high=None, low=None, close=None, volume=1)
        result = compute_smc(source)
        gap = result[6]
        self.assertEqual(gap["trend_direction"], 0)
        self.assertFalse(gap["bos_bullish"])
        self.assertFalse(gap["bos_bearish"])
        self.assertFalse(gap["liquidity_sweep_high"])
        self.assertFalse(gap["liquidity_sweep_low"])
        self.assertIsNone(gap["fvg_type"])
        self.assertEqual(len(result), len(source))

    def test_valid_rows_before_and_after_gap_are_preserved(self):
        source = rows()
        source[5].update(open=None, high=None, low=None, close=None, volume=4)
        result = compute_smc(source)
        self.assertEqual(len(result), len(source))
        self.assertEqual(result[5]["trend_direction"], 0)
        self.assertEqual(result[6]["trade_date"], source[6]["trade_date"])


if __name__ == "__main__":
    unittest.main()
