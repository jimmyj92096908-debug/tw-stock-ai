import unittest

from src.composite_scoring import compute_composite_score


class CompositeScoringTests(unittest.TestCase):
    def test_score_range_and_chip_marked_unavailable(self):
        row = {
            "close": 100, "ma5": 99, "ma20": 95, "ma60": 90,
            "ma120": 85, "ma240": 80, "rsi14": 58,
            "volume": 1500, "volume_ma20": 1000,
            "trend_direction": 1, "bos_bullish": True,
            "bos_bearish": False, "choch_bullish": False,
            "choch_bearish": False, "liquidity_sweep_low": True,
            "liquidity_sweep_high": False, "fvg_type": "bullish",
            "order_block_type": "bullish",
        }
        result = compute_composite_score(row)
        for key in ("total_score", "technical_score", "smc_score",
                    "short_term_score", "swing_score", "long_term_score"):
            self.assertGreaterEqual(result[key], 0)
            self.assertLessEqual(result[key], 100)
        self.assertIsNone(result["chip_score"])
        self.assertEqual(result["component_status"]["chip"], "not_available")
        self.assertAlmostEqual(result["coverage_weight"], 0.8)

    def test_chip_factor_is_integrated_when_source_coverage_is_sufficient(self):
        row = {
            "close": 100, "ma5": 99, "ma20": 95, "ma60": 90,
            "ma120": 85, "ma240": 80, "rsi14": 58,
            "volume": 1500, "volume_ma20": 1000,
            "trend_direction": 1, "bos_bullish": True,
            "bos_bearish": False, "choch_bullish": False,
            "choch_bearish": False, "liquidity_sweep_low": True,
            "liquidity_sweep_high": False, "fvg_type": "bullish",
            "order_block_type": "bullish", "chip_score": 90,
            "chip_coverage_weight": 0.75,
        }
        result = compute_composite_score(row)
        self.assertEqual(result["chip_score"], 90)
        self.assertEqual(result["component_status"]["chip"], "available")
        self.assertAlmostEqual(result["coverage_weight"], 0.95)
        self.assertAlmostEqual(result["short_coverage"], 0.95)

    def test_chip_factor_below_minimum_coverage_is_not_used(self):
        row = {"trend_direction": 1, "chip_score": 99, "chip_coverage_weight": 0.25}
        result = compute_composite_score(row)
        self.assertIsNone(result["chip_score"])
        self.assertEqual(result["component_status"]["chip"], "insufficient_coverage")
        self.assertAlmostEqual(result["coverage_weight"], 0.3)

    def test_missing_technical_data_is_not_fabricated(self):
        result = compute_composite_score({"trend_direction": 0})
        self.assertIsNone(result["technical_score"])
        self.assertIsNotNone(result["smc_score"])
        self.assertIsNotNone(result["short_term_score"])
        self.assertAlmostEqual(result["coverage_weight"], 0.3)

    def test_overbought_rsi_does_not_get_maximum_score(self):
        base = {"trend_direction": 0, "rsi14": 50, "close": 100, "ma5": 99,
                "ma20": 98, "volume": 100, "volume_ma20": 100}
        normal = compute_composite_score(base)
        overbought = compute_composite_score({**base, "rsi14": 95})
        self.assertLess(overbought["technical_score"], normal["technical_score"])

    def test_missing_smc_row_is_not_fabricated_as_neutral(self):
        result = compute_composite_score({
            "close": 100, "ma5": 99, "ma20": 98, "rsi14": 55,
            "volume": 100, "volume_ma20": 100,
        })
        self.assertIsNone(result["smc_score"])
        self.assertAlmostEqual(result["coverage_weight"], 0.5)
        self.assertEqual(result["component_status"]["smc"], "insufficient_data")

    def test_all_scores_are_none_when_no_data(self):
        result = compute_composite_score({})
        self.assertIsNone(result["total_score"])
        self.assertEqual(result["coverage_weight"], 0.0)


if __name__ == "__main__":
    unittest.main()
