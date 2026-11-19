import unittest

from scripts.diagnose_tpex_bulk_fallback import parse_csv_payload


class TPExBulkFallbackParserTests(unittest.TestCase):
    def test_parses_complete_official_ohlc_row(self):
        payload = (
            "代號,名稱,收盤,漲跌,開盤,最高,最低,均價,成交股數\n"
            "1259,示例公司,47.0,0.0,46.5,47.5,46.0,47.0,1000\n"
        )
        result = parse_csv_payload(payload, "1259")
        self.assertTrue(result["eligible"])
        self.assertEqual(result["open"], 46.5)
        self.assertEqual(result["high"], 47.5)
        self.assertEqual(result["low"], 46.0)
        self.assertEqual(result["close"], 47.0)

    def test_missing_official_ohlc_is_not_eligible(self):
        payload = (
            "代號,名稱,收盤,漲跌,開盤,最高,最低,均價,成交股數\n"
            "1259,示例公司,--,0,--,--,--,--,1000\n"
        )
        result = parse_csv_payload(payload, "1259")
        self.assertFalse(result["eligible"])

    def test_rejects_inconsistent_ohlc(self):
        payload = (
            "代號,名稱,收盤,漲跌,開盤,最高,最低,均價,成交股數\n"
            "1259,示例公司,47,0,46,45,44,46,1000\n"
        )
        result = parse_csv_payload(payload, "1259")
        self.assertFalse(result["eligible"])
        self.assertEqual(result["validation_error"], "inconsistent_ohlc_range")

    def test_returns_none_when_symbol_is_absent(self):
        payload = (
            "代號,名稱,收盤,漲跌,開盤,最高,最低,均價,成交股數\n"
            "1264,另一公司,47,0,46,48,45,47,1000\n"
        )
        self.assertIsNone(parse_csv_payload(payload, "1259"))


if __name__ == "__main__":
    unittest.main()
