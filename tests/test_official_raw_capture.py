import unittest
from scripts.capture_official_raw_sources import (
    TARGETS, find_tpex_monthly_row, find_twse_row, normalized_row, roc_date,
)


class OfficialRawCaptureTests(unittest.TestCase):
    def test_expanded_sample_targets_are_unique_and_cover_both_markets(self):
        keys = [(x["market"], x["stock_id"], x["trade_date"]) for x in TARGETS]
        self.assertEqual(len(keys), 7)
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual({x["market"] for x in TARGETS}, {"twse", "tpex"})

    def test_roc_date(self):
        self.assertEqual(roc_date("115/10/05"), "2026-10-05")
        self.assertIsNone(roc_date("--"))

    def test_tpex_row_exact_date(self):
        payload = {"tables": [{"data": [["115/10/05", "1,000", "20", "--", "--", "--", "--", "0", "12"]]}]}
        row = find_tpex_monthly_row(payload, "2026-10-05")
        self.assertEqual(row[0], "115/10/05")
        self.assertIsNone(find_tpex_monthly_row(payload, "2026-10-06"))

    def test_twse_row_exact_date(self):
        payload = {"data": [["115/11/18", "1,000", "20", "10", "11", "9", "10", "0", "12"]]}
        self.assertEqual(find_twse_row(payload, "2026-11-18")[0], "115/11/18")

    def test_normalizer_preserves_missing_markers(self):
        row = ["115/10/05", "1", "2", "--", "--", "--", "--", "0", "3"]
        self.assertEqual(normalized_row(row)["open"], "--")

    def test_short_row_rejected(self):
        self.assertIsNone(normalized_row(["115/10/05"]))


if __name__ == "__main__":
    unittest.main()
