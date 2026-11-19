import unittest

from src.official_source_reconciliation import reconcile_tpex_payloads


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
        self.assertFalse(result["ohlc_imputed"])

    def test_missing_bulk_count_is_pending_not_conflict(self):
        payload = {"tables": [{"totalCount": None, "fields": [], "data": []}]}
        result = reconcile_tpex_payloads(self.monthly, payload, "1259", "2026-10-05")
        self.assertEqual(result["classification"], "pending_review")

    def test_monthly_missing_row_is_pending(self):
        result = reconcile_tpex_payloads(self.monthly, self.bulk_empty, "1259", "2026-10-06")
        self.assertEqual(result["classification"], "pending_review")


if __name__ == "__main__":
    unittest.main()
