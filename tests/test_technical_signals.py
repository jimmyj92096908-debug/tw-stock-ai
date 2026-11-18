import unittest

from src.technical_signals import compute_signals


def row(**overrides):
    data = {
        "market": "twse", "stock_id": "2330", "trade_date": "2026-11-18",
        "rsi14": 50, "volume": 1000, "volume_ma20": 1000,
    }
    for window in (5, 10, 13, 20, 34, 55, 60, 120, 240):
        data[f"ma{window}"] = 250 - window
    data.update(overrides)
    return data


class TechnicalSignalsTests(unittest.TestCase):
    def test_bullish_and_bearish_alignment(self):
        bullish = row(**{f"ma{w}": 300 - i for i, w in enumerate((5, 10, 13, 20, 34, 55, 60, 120, 240))})
        bearish = row(**{f"ma{w}": 200 + i for i, w in enumerate((5, 10, 13, 20, 34, 55, 60, 120, 240))})
        self.assertEqual(compute_signals([bullish])[0]["ma_alignment"], "bullish")
        self.assertEqual(compute_signals([bearish])[0]["ma_alignment"], "bearish")

    def test_golden_cross_requires_previous_and_current_values(self):
        previous = row(ma5=99, ma20=100)
        current = row(trade_date="2026-11-19", ma5=101, ma20=100)
        result = compute_signals([previous, current])
        self.assertEqual(result[0]["ma5_ma20_cross"], "insufficient_data")
        self.assertEqual(result[1]["ma5_ma20_cross"], "golden_cross")

    def test_death_cross(self):
        result = compute_signals([
            row(ma5=101, ma20=100),
            row(trade_date="2026-11-19", ma5=99, ma20=100),
        ])
        self.assertEqual(result[1]["ma5_ma20_cross"], "death_cross")

    def test_rsi_thresholds(self):
        result = compute_signals([
            row(rsi14=75),
            row(trade_date="2026-11-19", rsi14=25),
            row(trade_date="2026-11-20", rsi14=50),
        ])
        self.assertEqual([x["rsi_state"] for x in result], ["overbought", "oversold", "neutral"])

    def test_volume_expansion_threshold(self):
        result = compute_signals([
            row(volume=1500, volume_ma20=1000),
            row(trade_date="2026-11-19", volume=1499, volume_ma20=1000),
        ])
        self.assertEqual(result[0]["volume_state"], "expanded")
        self.assertEqual(result[1]["volume_state"], "normal")
        self.assertAlmostEqual(result[0]["volume_ratio"], 1.5)

    def test_missing_data_is_not_fabricated(self):
        result = compute_signals([row(rsi14=None, volume_ma20=None, ma240=None)])
        self.assertEqual(result[0]["rsi_state"], "insufficient_data")
        self.assertEqual(result[0]["volume_state"], "insufficient_data")
        self.assertEqual(result[0]["ma_alignment"], "mixed_or_insufficient_data")


if __name__ == "__main__":
    unittest.main()
