import unittest
from src.stock_query import normalize_query, format_analysis_message


class StockQueryTests(unittest.TestCase):
    def test_normalize_prefix_and_trim(self):
        self.assertEqual(normalize_query(" 分析 2330 "), "2330")
        self.assertEqual(normalize_query("台積電"), "台積電")
        self.assertEqual(normalize_query("查詢 聯發科"), "聯發科")

    def test_format_missing_data_is_explicit(self):
        message = format_analysis_message({
            "stock_id": "2330", "stock_name": "台積電", "market": "twse",
            "trade_date": "2026-10-30", "close": 2370, "price_change": -45,
        })
        self.assertIn("資料日期：2026-10-30", message)
        self.assertIn("缺資料", message)
        self.assertIn("不構成買賣建議", message)

    def test_format_volume_ratio(self):
        message = format_analysis_message({
            "stock_id": "2330", "stock_name": "台積電", "market": "twse",
            "trade_date": "2026-10-30", "close": 100, "volume": 200,
            "volume_ma20": 100,
        })
        self.assertIn("2倍", message)


if __name__ == "__main__":
    unittest.main()
