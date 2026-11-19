import unittest
from scripts.capture_official_raw_sources import (
    TARGETS, build_tpex_bulk_params, find_tpex_legacy_daily_row, find_tpex_monthly_row, find_twse_row, normalized_row, roc_date, tpex_legacy_response_date,
)


class OfficialRawCaptureTests(unittest.TestCase):
    def test_expanded_sample_targets_are_unique_and_cover_both_markets(self):
        keys = [(x["market"], x["stock_id"], x["trade_date"]) for x in TARGETS]
        self.assertEqual(len(keys), 9)
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual({x["market"] for x in TARGETS}, {"twse", "tpex"})

    def test_tpex_bulk_query_requests_all_securities(self):
        self.assertEqual(
            build_tpex_bulk_params("2026-10-05"),
            {"response": "json", "date": "2026/10/05", "type": "AL"},
        )

    def test_roc_date(self):
        self.assertEqual(roc_date("115/10/05"), "2026-10-05")
        self.assertIsNone(roc_date("--"))

    def test_tpex_row_exact_date(self):
        payload = {"tables": [{"data": [["115/10/05", "1,000", "20", "--", "--", "--", "--", "0", "12"]]}]}
        row = find_tpex_monthly_row(payload, "2026-10-05")
        self.assertEqual(row[0], "115/10/05")
        self.assertIsNone(find_tpex_monthly_row(payload, "2026-10-06"))

    def test_tpex_public_daily_close_current_schema_and_response_date(self):
        payload = {
            "date": "20261119",
            "tables": [{
                "date": "115/11/19",
                "fields": ["代號", "名稱", "收盤", "漲跌", "開盤", "最高", "最低"],
                "data": [["1259", "安心", "69.00", "+2.00", "66.90", "70.70", "66.90"]],
            }],
        }
        self.assertEqual(tpex_legacy_response_date(payload), "2026-11-19")
        self.assertEqual(find_tpex_legacy_daily_row(payload, "1259")[0], "1259")
        self.assertIsNone(find_tpex_legacy_daily_row(payload, "1264"))

    def test_tpex_public_daily_close_rejects_requested_historical_date_when_response_is_current(self):
        payload = {
            "date": "20261119",
            "tables": [{"date": "115/11/19", "fields": ["代號", "名稱"], "data": [["1259", "安心"]]}],
        }
        requested_date = "2026-10-05"
        self.assertNotEqual(tpex_legacy_response_date(payload), requested_date)

    def test_tpex_public_daily_close_rejects_conflicting_response_dates(self):
        payload = {
            "date": "20261119",
            "tables": [{"date": "115/10/05", "fields": ["代號"], "data": [["1259"]]}],
        }
        self.assertIsNone(tpex_legacy_response_date(payload))

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
