import unittest

from src.ohlc_source_audit import classify_source_evidence


class TestOHLCSourceAudit(unittest.TestCase):
    def base(self, **overrides):
        row = {"open": 10, "high": 12, "low": 9, "close": 11, "volume": 1000}
        row.update(overrides)
        return row

    def test_complete_ohlc_is_valid(self):
        result = classify_source_evidence(self.base())
        self.assertEqual(result.status, "valid")
        self.assertTrue(result.eligible_for_indicators)

    def test_positive_volume_without_ohlc(self):
        row = self.base(open=None, high=None, low=None, close=None)
        result = classify_source_evidence(row)
        self.assertEqual(result.status, "positive_volume_no_ohlc")
        self.assertFalse(result.eligible_for_indicators)

    def test_all_checked_official_sources_missing_ohlc_with_positive_volume(self):
        row = self.base(open=None, high=None, low=None, close=None, volume=1)
        observations = [
            {"source": "tpex_individual", "open": None, "high": None, "low": None, "close": None, "volume": 1},
            {"source": "tpex_monthly", "open": None, "high": None, "low": None, "close": None, "volume": 1},
        ]
        result = classify_source_evidence(row, observations)
        self.assertEqual(result.status, "official_sources_missing_ohlc_with_volume")

    def test_zero_volume_and_missing_ohlc_is_not_assumed_no_trade(self):
        row = self.base(open=None, high=None, low=None, close=None, volume=0)
        result = classify_source_evidence(row)
        self.assertEqual(result.status, "zero_volume_no_ohlc_unconfirmed")
        self.assertFalse(result.eligible_for_indicators)

    def test_official_volume_disagreement_is_source_conflict(self):
        row = self.base(open=None, high=None, low=None, close=None, volume=1)
        observations = [
            {"source": "individual", "volume": 1, "transactions": 12},
            {"source": "monthly", "volume": 0, "transactions": 0},
        ]
        result = classify_source_evidence(row, observations)
        self.assertEqual(result.status, "source_conflict")
        self.assertEqual(result.conflicting_fields, ("volume", "transactions"))
        self.assertFalse(result.eligible_for_indicators)

    def test_partial_ohlc_requires_review(self):
        row = self.base(close=None)
        self.assertEqual(classify_source_evidence(row).status, "pending_review")

    def test_missing_volume_requires_review(self):
        row = self.base(volume=None)
        self.assertEqual(classify_source_evidence(row).status, "pending_review")

    def test_invalid_ohlc_range_is_rejected(self):
        row = self.base(high=8)
        self.assertEqual(classify_source_evidence(row).status, "invalid")

    def test_source_missing_fields_are_not_treated_as_zero(self):
        row = self.base(open=None, high=None, low=None, close=None, volume=1)
        result = classify_source_evidence(row, [{"source": "official", "volume": 1}])
        self.assertEqual(result.status, "official_sources_missing_ohlc_with_volume")


if __name__ == "__main__":
    unittest.main()
