import unittest
from src.margin_data import parse_twse, parse_tpex, roc_date

class MarginParserTests(unittest.TestCase):
    def test_roc_date(self):
        self.assertEqual(roc_date("1151117"), "2026-11-17")

    def test_twse_maps_fields(self):
        row = {"股票代號":"6213","融資買進":"100","融資賣出":"50","融資現金償還":"2","融資今日餘額":"1000","融券買進":"10","融券賣出":"20","融券現券償還":"1","融券今日餘額":"200","融資限額":"5000","融券限額":"5000"}
        rows = [dict(row, **{"股票代號": code}) for code in ("6213","4919","7827")]
        records = parse_twse({"stat":"OK","date":"1151117","data":rows}, "2026-11-17")
        self.assertEqual(len(records), 3)
        self.assertEqual(records[0]["margin_balance"], 1000)
        self.assertEqual(records[0]["short_buyback"], 10)

    def test_twse_supports_official_fields_and_array_rows(self):
        labels = ["證券代號", "融資買進", "融資賣出", "融資現金償還", "融資今日餘額",
                  "融券買進", "融券賣出", "融券現券償還", "融券今日餘額", "融資限額", "融券限額"]
        data = [[code, "100", "50", "2", "1000", "10", "20", "1", "200", "5000", "5000"]
                for code in ("6213", "4919", "7827")]
        records = parse_twse({"stat": "OK", "date": "1151117", "fields": labels, "data": data}, "2026-11-17")
        self.assertEqual(records[0]["margin_buy"], 100)
        self.assertEqual(records[0]["short_balance"], 200)

    def test_twse_parses_tables_per_stock_detail(self):
        fields = ["代號", "名稱", "買進", "賣出", "現金償還", "前日餘額", "今日餘額",
                  "次一營業日限額", "買進", "賣出", "現券償還", "前日餘額",
                  "今日餘額", "次一營業日限額", "資券互抵", "註記"]
        rows = [[code, "測試", "100", "50", "2", "900", "1000", "5000",
                 "10", "20", "1", "190", "200", "5000", "0", ""] for code in ("6213", "4919", "7827")]
        payload = {"stat": "OK", "date": "20261117", "tables": [
            {"fields": ["項目", "買進", "賣出"], "data": [["市場", "1", "2"]]},
            {"fields": fields, "data": rows},
        ]}
        records = parse_twse(payload, "2026-11-17")
        self.assertEqual(len(records), 3)
        self.assertEqual(records[0]["margin_balance"], 1000)
        self.assertEqual(records[0]["short_balance"], 200)
        self.assertEqual(records[0]["short_sell"], 20)

    def test_twse_rejects_wrong_date(self):
        with self.assertRaises(RuntimeError):
            parse_twse({"stat":"OK","date":"1151116","data":[]}, "2026-11-17")

    def test_tpex_maps_official_keys(self):
        row = {"Date":"1151117","SecuritiesCompanyCode":"8937","MarginPurchase":"100","MarginSales":"50","CashRedemption":"2","MarginPurchaseBalance":"1000","ShortConvering":"10","ShortSale":"20","StockRedemption":"1","ShortSaleBalance":"200","MarginPurchaseLimit":"5000","ShortSaleLimit":"5000"}
        records = parse_tpex([row], "2026-11-17")
        self.assertEqual(records[0]["margin_balance"], 1000)
        self.assertEqual(records[0]["short_sell"], 20)

    def test_tpex_rejects_wrong_snapshot_date(self):
        with self.assertRaises(RuntimeError):
            parse_tpex([{"Date":"1151116","SecuritiesCompanyCode":"8937"}], "2026-11-17")

if __name__ == "__main__":
    unittest.main()
