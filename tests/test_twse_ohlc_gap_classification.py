import unittest

from scripts.classify_twse_ohlc_gaps import classify_record, build_report


class TwseOhlcGapClassificationTests(unittest.TestCase):
    def setUp(self):
        self.bulk = {
            "trade_date": "2026-11-19", "stock_id": "2330",
            "volume": 1000, "turnover": 100000,
            "open": None, "high": None, "low": None, "close": None,
        }

    def test_official_individual_ohlc_missing_is_not_imputed(self):
        individual = {
            "individual_source_status": "matched", "volume": 1000, "turnover": 100000,
            "open": None, "high": None, "low": None, "close": None,
        }
        result = classify_record(self.bulk, individual)
        self.assertEqual(result["classification"], "OFFICIAL_INDIVIDUAL_OHLC_MISSING")
        self.assertFalse(result["price_imputation_allowed"])

    def test_matching_individual_ohlc_is_discrepancy_not_auto_backfill(self):
        individual = {
            "individual_source_status": "matched", "volume": 1000, "turnover": 100000,
            "open": 100, "high": 102, "low": 99, "close": 101,
        }
        result = classify_record(self.bulk, individual)
        self.assertEqual(result["classification"], "INDIVIDUAL_OHLC_AVAILABLE_BULK_GAP")
        self.assertTrue(result["review_required"])
        self.assertFalse(result["price_imputation_allowed"])

    def test_mismatched_volume_requires_manual_review(self):
        individual = {
            "individual_source_status": "matched", "volume": 900, "turnover": 100000,
            "open": 100, "high": 102, "low": 99, "close": 101,
        }
        result = classify_record(self.bulk, individual)
        self.assertEqual(result["classification"], "INDIVIDUAL_OHLC_AVAILABLE_VALUES_MISMATCH")

    def test_no_individual_match_stays_pending(self):
        result = classify_record(self.bulk, None)
        self.assertEqual(result["classification"], "INDIVIDUAL_SOURCE_NO_MATCH")

    def test_partial_ohlc_stays_null(self):
        individual = {
            "individual_source_status": "matched", "volume": 1000, "turnover": 100000,
            "open": 100, "high": None, "low": 99, "close": 101,
        }
        result = classify_record(self.bulk, individual)
        self.assertEqual(result["classification"], "INDIVIDUAL_OHLC_PARTIAL_OR_INVALID")

    def test_report_is_read_only_and_never_authorizes_imputation(self):
        bulk = {"records": [self.bulk]}
        individual = {"comparisons": []}
        report = build_report(bulk, individual)
        self.assertTrue(report["read_only"])
        self.assertFalse(report["database_modified"])
        self.assertFalse(report["automatic_backfill_allowed"])
        self.assertFalse(report["price_imputation_performed"])


if __name__ == "__main__":
    unittest.main()
