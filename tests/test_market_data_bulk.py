import unittest

from src.market_data_bulk import parse_all_market_daily


class AllMarketDailyParserTests(unittest.TestCase):
    def test_parse_tpex_bulk_market_and_keep_scope_label(self):
        payload = {
            "stat": "ok",
            "date": "20261005",
            "tables": [{
                "date": "115/10/05",
                "title": "上櫃股票每日收盤行情(不含定價)",
                "fields": ["代號", "名稱", "收盤 ", "漲跌", "開盤 ", "最高 ", "最低", "成交股數  ", " 成交金額(元)", " 成交筆數 "],
                "data": [["1259", "安心", "47.00", "0.00", "47.00", "47.00", "47.00", "1000", "47000", "12"]],
            }],
        }
        rows = parse_all_market_daily(payload, "tpex", "2026-10-05")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["stock_id"], "1259")
        self.assertEqual(row["volume"], 1000)
        self.assertEqual(row["transactions"], 12)
        self.assertEqual(row["ohlc_status"], "complete")
        self.assertEqual(row["source"], "TPEX_OTC_EXCLUDING_FIXED_PRICE")

    def test_parse_twse_all_market_table(self):
        payload = {
            "stat": "OK",
            "date": "20261118",
            "tables": [{
                "title": "115年11月18日 每日收盤行情",
                "fields": ["證券代號", "證券名稱", "成交股數", "成交筆數", "成交金額", "開盤價", "最高價", "最低價", "收盤價", "漲跌價差"],
                "data": [["1101", "台泥", "1,234,567", "1,234", "32,345,678", "26.80", "26.85", "26.15", "26.25", "0.00"]],
            }],
        }
        rows = parse_all_market_daily(payload, "twse", "2026-11-18")
        self.assertEqual(rows[0]["stock_id"], "1101")
        self.assertEqual(rows[0]["volume"], 1234567)
        self.assertEqual(rows[0]["transactions"], 1234)
        self.assertEqual(rows[0]["close"], 26.25)
        self.assertEqual(rows[0]["ohlc_status"], "complete")

    def test_reject_response_date_mismatch(self):
        payload = {
            "stat": "ok",
            "date": "20261119",
            "tables": [{
                "date": "115/11/19",
                "fields": ["代號", "名稱", "收盤", "開盤", "最高", "最低", "成交股數"],
                "data": [["1259", "安心", "69", "66.9", "70.7", "66.9", "1000"]],
            }],
        }
        with self.assertRaisesRegex(ValueError, "returned 2026-11-19"):
            parse_all_market_daily(payload, "tpex", "2026-10-05")

    def test_missing_ohlc_is_preserved_as_null_and_not_imputed(self):
        payload = {
            "stat": "ok",
            "date": "20261005",
            "tables": [{
                "date": "115/10/05",
                "fields": ["代號", "名稱", "收盤", "開盤", "最高", "最低", "成交股數"],
                "data": [["1259", "安心", "--", "--", "--", "--", "1000"]],
            }],
        }
        row = parse_all_market_daily(payload, "tpex", "2026-10-05")[0]
        self.assertIsNone(row["open"])
        self.assertIsNone(row["close"])
        self.assertEqual(row["ohlc_status"], "missing")

    def test_reject_inconsistent_response_date_fields(self):
        payload = {
            "stat": "ok",
            "date": "20261119",
            "tables": [{
                "date": "115/10/05",
                "fields": ["代號", "名稱", "收盤", "開盤", "最高", "最低", "成交股數"],
                "data": [["1259", "安心", "69", "66.9", "70.7", "66.9", "1000"]],
            }],
        }
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            parse_all_market_daily(payload, "tpex", "2026-11-19")

    def test_duplicate_security_code_rejected(self):
        payload = {
            "stat": "ok",
            "date": "20261005",
            "tables": [{
                "date": "115/10/05",
                "fields": ["代號", "名稱", "收盤", "開盤", "最高", "最低", "成交股數"],
                "data": [
                    ["1259", "安心", "69", "66.9", "70.7", "66.9", "1000"],
                    ["1259", "安心", "69", "66.9", "70.7", "66.9", "1000"],
                ],
            }],
        }
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            parse_all_market_daily(payload, "tpex", "2026-10-05")


if __name__ == "__main__":
    unittest.main()
