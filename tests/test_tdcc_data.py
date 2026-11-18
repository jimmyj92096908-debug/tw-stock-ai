import json
import unittest

from src.tdcc_data import parse_csv


class TDCCTests(unittest.TestCase):
    def test_parses_roc_date_and_allows_known_tiers(self):
        csv_text = (
            "資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%\n"
            "1151113,6213,1,100,20000,0.25\n"
            "1151113,6213,15,2,5000000,62.5\n"
            "1151113,6213,16,0,0,0\n"
            "1151113,6213,17,102,5020000,100\n"
            "1151113,9999,1,1,100,0.01\n"
        )
        rows = parse_csv(csv_text, {"6213": "twse"})
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["as_of_date"], "2026-11-13")
        self.assertEqual(rows[0]["holder_range"], "1-999")
        self.assertEqual(rows[1]["holder_range"], "1,000,001以上")
        self.assertEqual(rows[2]["holder_range"], "合計")


    def test_parses_bom_prefixed_date_header(self):
        csv_text = (
            "證券代號,占集保庫存數比例%,人數,\\ufeff資料日期,股數,持股分級\n"
            "6213,0.25,100,1151113,20000,1\n"
        )
        rows = parse_csv(csv_text, {"6213": "twse"})
        self.assertEqual(rows[0]["as_of_date"], "2026-11-13")

    def test_parses_openapi_json_rows(self):
        payload = {
            "data": [
                {"資料日期": "2026-11-13", "證券代號": "6213", "持股分級": "1",
                 "人數": 100, "股數": 20000, "占集保庫存數比例%": 0.25}
            ]
        }
        rows = parse_csv(json.dumps(payload, ensure_ascii=False).encode("utf-8"), {"6213": "twse"})
        self.assertEqual(rows[0]["as_of_date"], "2026-11-13")
        self.assertEqual(rows[0]["holder_range"], "1-999")

    def test_rejects_missing_required_column(self):
        with self.assertRaises(RuntimeError):
            parse_csv("資料日期,證券代號,持股分級,人數,股數\n1151113,6213,1,1,100\n")

    def test_rejects_invalid_values(self):
        csv_text = (
            "資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%\n"
            "1151113,6213,1,-1,100,0.1\n"
        )
        with self.assertRaises(RuntimeError):
            parse_csv(csv_text, {"6213": "twse"})


if __name__ == "__main__":
    unittest.main()
