import unittest
from src.market_benchmark import parse_month

class TAIEXParserTests(unittest.TestCase):
    def test_parse_roc_dates_and_commas(self):
        payload={"stat":"OK","fields":["日期","開盤指數","最高指數","最低指數","收盤指數"],
                 "data":[["115/11/17","39,000","40,000","38,900","39,701.64"]]}
        self.assertEqual(parse_month(payload)[0][0].isoformat(),"2026-11-17")
        self.assertAlmostEqual(parse_month(payload)[0][1],39701.64)
    def test_reject_unexpected_fields(self):
        with self.assertRaises(ValueError):
            parse_month({"stat":"OK","fields":["date","close"],"data":[]})
    def test_reject_non_ok(self):
        with self.assertRaises(ValueError):
            parse_month({"stat":"很抱歉","fields":[],"data":[]})

if __name__=="__main__": unittest.main()
