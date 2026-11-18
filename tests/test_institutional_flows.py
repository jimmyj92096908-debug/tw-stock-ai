import unittest
from datetime import date

from src.institutional_flows import parse_number, parse_twse, parse_tpex, _payload_rows


class InstitutionalFlowTests(unittest.TestCase):
    def test_parse_number_handles_commas_and_missing(self):
        self.assertEqual(parse_number("1,234"), 1234)
        self.assertEqual(parse_number("-500"), -500)
        self.assertIsNone(parse_number("--"))
        self.assertIsNone(parse_number(None))

    def test_twse_maps_buy_sell_and_dealer_subtypes(self):
        payload = {
            "stat": "OK",
            "fields": ["證券代號", "外陸資買進股數(不含外資自營商)",
                       "外陸資賣出股數(不含外資自營商)", "投信買進股數",
                       "投信賣出股數", "自營商買進股數(自行買賣)",
                       "自營商賣出股數(自行買賣)", "自營商買進股數(避險)",
                       "自營商賣出股數(避險)", "三大法人買賣超股數"],
            "data": [["2330", "10,000", "3,000", "2,000", "1,000",
                      "500", "200", "300", "100", "8,500"]],
        }
        rows = parse_twse(payload, date(2026, 11, 18))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["foreign_net"], 7000)
        self.assertEqual(row["trust_net"], 1000)
        self.assertEqual(row["dealer_net"], 500)
        self.assertEqual(row["total_net"], 8500)
        self.assertEqual(row["market"], "twse")

    def test_tpex_handles_english_field_variants(self):
        payload = [{
            "SecuritiesCompanyCode": "6488",
            "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Total Buy": "1000",
            "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Total Sell": "400",
            "SecuritiesInvestmentTrustCompanies-TotalBuy": "300",
            "SecuritiesInvestmentTrustCompanies-TotalSell": "100",
            "Dealers-TotalBuy": "250",
            "Dealers-TotalSell": "150",
            "TotalDifference": "900",
        }]
        row = parse_tpex(payload, date(2026, 11, 18))[0]
        self.assertEqual(row["foreign_net"], 600)
        self.assertEqual(row["trust_net"], 200)
        self.assertEqual(row["dealer_net"], 100)
        self.assertEqual(row["total_net"], 900)
        self.assertEqual(row["market"], "tpex")

    def test_tpex_maps_official_net_difference_fields(self):
        payload = [{
            "SecuritiesCompanyCode": "6488",
            "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference": "600",
            "SecuritiesInvestmentTrustCompanies-Difference": "200",
            "Dealers-Difference": "100",
            "TotalDifference": "900",
        }]
        row = parse_tpex(payload, date(2026, 11, 18))[0]
        self.assertIsNone(row["foreign_buy"])
        self.assertEqual(row["foreign_net"], 600)
        self.assertEqual(row["trust_net"], 200)
        self.assertEqual(row["dealer_net"], 100)
        self.assertEqual(row["total_net"], 900)

    def test_missing_fields_stay_null_and_nonstock_codes_are_ignored(self):
        payload = [{"證券代號": "6488", "投信買進股數": "1,000"}]
        row = parse_tpex(payload, date(2026, 11, 18))[0]
        self.assertIsNone(row["foreign_net"])
        self.assertEqual(row["trust_buy"], 1000)
        self.assertEqual(parse_tpex([{"證券代號": "00679B"}], date(2026, 11, 18)), [])

    def test_nontrading_day_response_is_empty(self):
        self.assertEqual(_payload_rows({"stat": "查無資料", "data": []}), [])


if __name__ == "__main__":
    unittest.main()
