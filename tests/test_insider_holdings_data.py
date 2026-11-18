import unittest
from src.insider_holdings_data import parse_rows, as_date


class InsiderHoldingsTests(unittest.TestCase):
    def test_roc_month_and_share_fields(self):
        rows = [{
            "公司代號": "6213", "資料年月": "11510", "姓名": "王小明",
            "職稱": "董事長本人", "持有股數": "1,234,567",
            "設質股數": "100,000", "持股比例": "1.25%",
        }]
        parsed = parse_rows(rows, "twse")
        self.assertEqual(parsed[0]["as_of_date"], "2026-10-01")
        self.assertEqual(parsed[0]["share_count"], 1234567)
        self.assertEqual(parsed[0]["pledged_shares"], 100000)
        self.assertEqual(parsed[0]["share_percent"], 1.25)

    def test_missing_optional_pledge_is_null(self):
        rows = [{
            "公司代號": "8937", "資料年月": "202610", "姓名": "測試法人",
            "職稱": "法人董事代表人", "持有股數": "50000",
        }]
        parsed = parse_rows(rows, "tpex")
        self.assertIsNone(parsed[0]["pledged_shares"])
        self.assertIsNone(parsed[0]["share_percent"])

    def test_rejects_pledge_greater_than_holding(self):
        rows = [{
            "公司代號": "4919", "資料年月": "11510", "姓名": "測試",
            "職稱": "董事", "持有股數": "100", "設質股數": "101",
        }]
        with self.assertRaises(RuntimeError):
            parse_rows(rows, "twse")

    def test_filters_other_symbols(self):
        rows = [{
            "公司代號": "2330", "資料年月": "11510", "姓名": "測試",
            "職稱": "董事", "持有股數": "100",
        }]
        with self.assertRaises(RuntimeError):
            parse_rows(rows, "twse")

    def test_column_keys_ignore_whitespace_and_bom(self):
        rows = [{
            chr(65279) + "公司 代號": "6213", "資料 年月": "11510", "姓 名": "測試",
            "職 稱": "董事", "持有 股數": "100",
        }]
        parsed = parse_rows(rows, "twse")
        self.assertEqual(parsed[0]["share_count"], 100)

    def test_date_parser(self):
        self.assertEqual(as_date("115/10/31"), "2026-10-31")
        self.assertEqual(as_date("2026-10"), "2026-10-01")


if __name__ == "__main__":
    unittest.main()
