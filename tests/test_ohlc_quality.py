import unittest

from src.ohlc_quality import classify_ohlc_row


class TestOHLCQuality(unittest.TestCase):
    def row(self, **overrides):
        row = {"open": 10, "high": 12, "low": 9, "close": 11, "volume": 1000}
        row.update(overrides)
        return row

    def test_valid_row_is_indicator_eligible(self):
        result = classify_ohlc_row(self.row())
        self.assertEqual(result.status, "valid")
        self.assertTrue(result.eligible_for_indicators)

    def test_zero_volume_and_all_null_prices_is_no_trade(self):
        result = classify_ohlc_row(self.row(
            open=None, high=None, low=None, close=None, volume=0
        ))
        self.assertEqual(result.status, "no_trade")
        self.assertFalse(result.eligible_for_indicators)

    def test_missing_price_with_volume_is_invalid(self):
        result = classify_ohlc_row(self.row(close=None))
        self.assertEqual(result.status, "invalid")

    def test_partial_null_zero_volume_is_invalid(self):
        result = classify_ohlc_row(self.row(open=None, volume=0))
        self.assertEqual(result.status, "invalid")

    def test_negative_volume_is_invalid(self):
        self.assertEqual(classify_ohlc_row(self.row(volume=-1)).reason, "negative_volume")

    def test_inconsistent_high_low_is_invalid(self):
        self.assertEqual(
            classify_ohlc_row(self.row(high=8)).reason,
            "inconsistent_ohlc_range",
        )

    def test_non_positive_price_is_invalid(self):
        self.assertEqual(
            classify_ohlc_row(self.row(low=0)).reason,
            "non_positive_price",
        )

    def test_input_is_not_mutated(self):
        row = self.row()
        original = row.copy()
        classify_ohlc_row(row)
        self.assertEqual(row, original)


if __name__ == "__main__":
    unittest.main()
