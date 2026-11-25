import json
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch
from scripts import owner_twse_action_window_candidates as m

class CandidateTests(unittest.TestCase):
    def raw(self):
        return json.dumps({"stat":"OK","fields":["除權息日期","股票代號","息值"],
            "data":[["112/01/04","1101","1.25"],["112/01/05","9999","3"]]},
            ensure_ascii=False).encode()
    def test_candidate_not_cash_or_absence_proof(self):
        r=m.classify(self.raw(),"ex","2023-01-03","2023-01-10",("1101",))
        self.assertEqual(r["status"],"CANDIDATE_SCAN_ONLY")
        self.assertEqual(len(r["candidates"]),1)
        self.assertNotIn("cash_per_pre_event_share",r["candidates"][0])
        self.assertEqual(m.classify(self.raw(),"ex","2023-01-05","2023-01-10",("1101",))["status"],"OUT_OF_RANGE_UNVERIFIED")
        self.assertEqual(m.classify(b'{"stat":"NO"}',"ex","2023-01-03","2023-01-10",("1101",))["status"],"NON_OK_UNVERIFIED")
    def test_restart(self):
        w=("2022-12-30","2023-01-03","2023-01-10",("1101",))
        with TemporaryDirectory() as d,patch.object(m,"fetch",return_value=self.raw()) as f:
            a=m.capture(d,w,get=None,sleeper=lambda _:None)
            self.assertEqual(a["new_requests"],2)
            z=m.capture(d,w,get=None,sleeper=lambda _:None)
            self.assertEqual(z["new_requests"],0)
            self.assertEqual(f.call_count,2)

    def test_observed_reduction_no_match_is_not_coverage(self):
        def check(stat,kind="reduction",**extra):
            raw=json.dumps({"stat":stat,**extra},ensure_ascii=False).encode()
            return m.classify(raw,kind,"2023-01-03","2023-01-10",("1101",))
        message="很抱歉，沒有符合條件的資料!"
        self.assertEqual(check(message)["status"],"OFFICIAL_REDUCTION_NO_MATCH_ONLY")
        self.assertEqual(check(message,fields=[],data=[])["status"],"OFFICIAL_REDUCTION_NO_MATCH_ONLY")
        self.assertEqual(check(message,kind="ex")["status"],"NON_OK_UNVERIFIED")
        self.assertEqual(check(message,data=[["unexpected"]])["status"],"NON_OK_UNVERIFIED")
        self.assertEqual(check(message,fields=["unexpected"])["status"],"NON_OK_UNVERIFIED")
        self.assertEqual(check("查詢結束日期小於查詢開始日期，請重新查詢!")["status"],"NON_OK_UNVERIFIED")
        self.assertEqual(check("OK",fields=[],data=[])["status"],"SCHEMA_UNVERIFIED")
