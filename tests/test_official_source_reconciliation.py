import unittest

from src.official_source_reconciliation import _valid_ohlc, reconcile_tpex_payloads, reconcile_twse_payloads


class TpexReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.monthly = {
            "tables": [{
                "fields": ["日 期", "成交張數", "成交仟元", "開盤", "最高", "最低", "收盤", "漲跌", "筆數"],
                "data": [["115/10/05", "1", "47", "--", "--", "--", "--", "0.00", "12"]],
            }]
        }
        self.bulk_empty = {
            "tables": [{
                "title": "上櫃股票每日收盤行情(不含定價)",
                "totalCount": 0,
                "fields": ["代號", "名稱", "收盤 ", "漲跌", "開盤 ", "最高 ", "最低", "成交股數  "],
                "data": [],
            }]
        }

    def test_positive_monthly_volume_vs_empty_bulk_is_conflict_not_zero_trade(self):
        result = reconcile_tpex_payloads(self.monthly, self.bulk_empty, "1259", "2026-10-05")
        self.assertEqual(result["classification"], "source_conflict")
        self.assertEqual(result["reason"], "monthly_individual_positive_volume_but_bulk_table_total_count_zero")
        self.assertEqual(result["evidence_confidence"], "insufficient")
        self.assertFalse(result["ohlc_imputed"])

    def test_missing_bulk_count_is_pending_not_conflict(self):
        payload = {"tables": [{"totalCount": None, "fields": [], "data": []}]}
        result = reconcile_tpex_payloads(self.monthly, payload, "1259", "2026-10-05")
        self.assertEqual(result["classification"], "pending_review")

    def test_monthly_missing_row_is_pending(self):
        result = reconcile_tpex_payloads(self.monthly, self.bulk_empty, "1259", "2026-10-06")
        self.assertEqual(result["classification"], "pending_review")


class TwseReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.monthly = {
            "data": [["115/11/18", "1234567", "32345678", "26.80", "26.85", "26.15", "26.25", "0.00", "1234"]]
        }
        self.daily = {
            "tables": [{
                "fields": ["證券代號", "證券名稱", "成交股數", "成交筆數", "開盤價", "最高價", "最低價", "收盤價"],
                "data": [["1101", "台泥", "1234567", "1234", "26.80", "26.85", "26.15", "26.25"]],
            }]
        }

    def test_matching_twse_sources_are_corroborated(self):
        result = reconcile_twse_payloads(self.monthly, self.daily, "1101", "2026-11-18")
        self.assertEqual(result["classification"], "corroborated")
        self.assertTrue(result["ohlc_match"])
        self.assertTrue(result["volume_match"])
        self.assertTrue(result["trade_count_match"])
        self.assertEqual(result["evidence_confidence"], "corroborated_two_official_endpoints")
        self.assertFalse(result["ohlc_imputed"])

    def test_twse_value_mismatch_is_source_conflict(self):
        changed = {
            "tables": [{
                "fields": ["證券代號", "證券名稱", "成交股數", "成交筆數", "開盤價", "最高價", "最低價", "收盤價"],
                "data": [["1101", "台泥", "1234567", "1234", "26.80", "26.85", "26.15", "26.20"]],
            }]
        }
        result = reconcile_twse_payloads(self.monthly, changed, "1101", "2026-11-18")
        self.assertEqual(result["classification"], "source_conflict")

    def test_twse_missing_ohlc_is_pending_not_imputed(self):
        missing = {
            "tables": [{
                "fields": ["證券代號", "證券名稱", "成交股數", "成交筆數", "開盤價", "最高價", "最低價", "收盤價"],
                "data": [["1101", "台泥", "1234567", "1234", "--", "26.85", "26.15", "26.25"]],
            }]
        }
        result = reconcile_twse_payloads(self.monthly, missing, "1101", "2026-11-18")
        self.assertEqual(result["classification"], "pending_review")
        self.assertFalse(result["ohlc_imputed"])


class OhlcValidationTests(unittest.TestCase):
    def test_valid_ohlc(self):
        self.assertTrue(_valid_ohlc({"open": 10, "high": 12, "low": 9, "close": 11}))

    def test_missing_zero_negative_and_nonfinite_values_are_invalid(self):
        cases = [
            {"open": None, "high": 12, "low": 9, "close": 11},
            {"open": 0, "high": 12, "low": 0, "close": 11},
            {"open": -1, "high": 12, "low": 9, "close": 11},
            {"open": 10, "high": float("inf"), "low": 9, "close": 11},
        ]
        for values in cases:
            with self.subTest(values=values):
                self.assertFalse(_valid_ohlc(values))

    def test_high_must_cover_open_and_close(self):
        self.assertFalse(_valid_ohlc({"open": 13, "high": 12, "low": 9, "close": 11}))
        self.assertFalse(_valid_ohlc({"open": 10, "high": 12, "low": 9, "close": 13}))

    def test_low_must_not_exceed_open_or_close(self):
        self.assertFalse(_valid_ohlc({"open": 10, "high": 12, "low": 11, "close": 11.5}))


if __name__ == "__main__":
    unittest.main()
