import json
import unittest
from scripts.v3_twse_action_detail_pilot import inspect

class DetailPilotTests(unittest.TestCase):
    def test_exact_issuer_date(self):
        obj={"stat":"OK","fields":["股票代號","除權息日期","每股配發現金股利"],"data":[["2330","113/05/03","3"]]}
        raw=json.dumps(obj).encode()
        r=inspect(raw,"2330","2024-05-03")
        self.assertTrue(r["event_date_independently_matched"])
        self.assertEqual(r["status"],"DETAIL_CANDIDATE_ONLY")
        for stock,day in (("2317","2024-05-03"),("2330","2024-05-02")):
            with self.assertRaises(ValueError):
                inspect(raw,stock,day)
    def test_missing_date_not_certified(self):
        raw=json.dumps({"stat":"OK","fields":["股票代號","每股配發現金股利"],"data":[["2330","3"]]}).encode()
        self.assertFalse(inspect(raw,"2330","2024-05-03")["event_date_independently_matched"])
    def test_no_match_and_error(self):
        raw=json.dumps({"stat":"很抱歉，沒有符合條件的資料!"}).encode()
        self.assertEqual(inspect(raw,"2330","2024-05-03")["status"],"NO_MATCH_NOT_ZERO_PROOF")
        with self.assertRaises(ValueError):
            inspect(json.dumps({"stat":"系統忙碌"}).encode(),"2330","2024-05-03")
