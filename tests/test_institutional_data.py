import unittest
from src.institutional_data import ad_date, to_int, parse_tpex

class InstitutionalDataTests(unittest.TestCase):
    def test_numeric_parser(self):
        self.assertEqual(to_int("1,234"), 1234)
        self.assertEqual(to_int("-56"), -56)
        self.assertIsNone(to_int("--"))

    def test_minguo_date(self):
        self.assertEqual(ad_date("1151117"), "2026-11-17")

    def test_tpex_requires_matching_snapshot_date(self):
        row = {
            "Date": "1151117", "SecuritiesCompanyCode": "8937",
            "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-TotalBuy": "100",
            "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-TotalSell": "40",
            "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference": "60",
            "SecuritiesInvestmentTrustCompanies-TotalBuy": "20",
            "SecuritiesInvestmentTrustCompanies-TotalSell": "5",
            "SecuritiesInvestmentTrustCompanies-Difference": "15",
            "Dealers-TotalBuy": "10", "Dealers-TotalSell": "15", "Dealers-Difference": "-5",
            "TotalDifference": "70",
        }
        result = parse_tpex([row], "2026-11-17")
        self.assertEqual(result[0]["foreign_net"], 60)
        self.assertEqual(result[0]["dealer_net"], -5)
        with self.assertRaises(RuntimeError):
            parse_tpex([row], "2026-11-16")

if __name__ == "__main__":
    unittest.main()
