import copy
from datetime import date,timedelta
import unittest
from scripts.v3_raw_path_recovery import recover,digest,CapturePaused

class RawPathRecoveryTests(unittest.TestCase):
    def inputs(self):
        sessions=["2024-05-02","2024-05-03","2024-05-06","2024-05-07","2024-05-08","2024-05-09"]
        paths=[dict(market="twse",stock_id="2330",signal_date="2024-04-30",sessions=sessions)]
        missing=[dict(market="twse",stock_id="2317",signal_date="2024-04-30"),
                 dict(market="twse",stock_id="2303",signal_date="2024-05-31"),
                 dict(market="twse",stock_id="2317",signal_date="2024-06-28")]
        action=dict(summary=dict(matched_panel_sha256=digest(paths)),private_matched_rows=paths)
        plan=dict(summary=dict(scope="V3_OFFLINE_RAW_PATH_EXPANSION_PLAN_ONLY",
                  model_release="BLOCKED",execution_labels_approved=0,missing_path_rows=len(missing),
                  missing_keys_sha256=digest(missing),existing_paths_sha256=digest(paths)),
                  private_missing_keys=missing)
        return plan,action

    def test_existing_and_new_windows_without_future_requests(self):
        p,a=self.inputs()
        calls=[]
        def lookup(d):
            calls.append(d)
            return {"2317":"100.0","2303":"50.25"} if d.weekday()<5 else None
        r=recover(p,a,lookup,date(2024,7,1))
        self.assertEqual(r["summary"]["recovered_path_rows"],2)
        self.assertEqual(r["summary"]["counts"],{"recovered":2,"not_yet_mature":1})
        self.assertEqual(r["private_recovered_paths"][0]["sessions"],a["private_matched_rows"][0]["sessions"])
        self.assertEqual(r["private_recovered_paths"][1]["sessions"],["2024-06-03","2024-06-04","2024-06-05","2024-06-06","2024-06-07","2024-06-10"])
        self.assertTrue(all(d<=date(2024,7,1) for d in calls))
        self.assertEqual(r["summary"]["execution_labels_approved"],0)
        self.assertFalse(r["summary"]["official_calendar_independently_verified"])

    def test_missing_price_never_imputed_and_pause_visible(self):
        p,a=self.inputs()
        def lookup(d):
            if d>=date(2024,6,1):
                raise CapturePaused("budget")
            return {}
        r=recover(p,a,lookup,date(2024,7,1))
        self.assertEqual(r["summary"]["recovered_path_rows"],0)
        self.assertEqual(r["summary"]["counts"],{"missing_stock_close":1,"recovered":0,"capture_pending":1,"not_yet_mature":1})

    def test_changed_plan_rejected(self):
        p,a=self.inputs()
        p["private_missing_keys"][0]["stock_id"]="1589"
        with self.assertRaises(ValueError):
            recover(p,a,lambda d:{},date(2024,7,1))
        p["summary"]["missing_keys_sha256"]=digest(p["private_missing_keys"])
        with self.assertRaises(ValueError):
            recover(p,a,lambda d:{},date(2024,7,1))
