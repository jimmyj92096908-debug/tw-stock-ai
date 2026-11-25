from datetime import date,timedelta
import copy
import unittest
from src import research_monthly_ridge_hypothetical as m

def fixture(n=30):
    features=[];obs=[]
    for i in range(n):
        year=2023+i//12;month=1+i%12
        d=date(year,month,1)
        while d.weekday()>=5:d+=timedelta(days=1)
        sessions=[];x=d
        while len(sessions)<6:
            x+=timedelta(days=1)
            if x.weekday()<5:sessions.append(x.isoformat())
        for j in range(5):
            sid=str(2300+j)
            features.append({"signal_date":d.isoformat(),"market":"twse","stock_id":sid,
                "feature_vector":[float(j)]*12})
            obs.append({"market":"twse","stock_id":sid,"signal_date":d.isoformat(),"sessions":sessions,
                "prices":[{"trade_date":s,"close":str(100+j*2) if s==sessions[-1] else "100","evidence_sha256":"a"*64} for s in sessions],
                "actions":[],"coverage":{"market":"twse","stock_id":sid,"start_exclusive":sessions[0],
                    "end_inclusive":sessions[-1],"all_action_types_covered_asserted":True,"evidence_sha256":"b"*64}})
    return features,obs

class RidgeTests(unittest.TestCase):
    def test_fit_and_no_future_label_leakage(self):
        f,o=fixture();start=f[20*5]["signal_date"]
        args=dict(label_cutoff="2026-12-31",test_start=start)
        r=m.evaluate(f,o,**args)
        self.assertTrue(r["model_trained"])
        self.assertEqual(len(r["folds"]),10)
        self.assertEqual(r["model_release"],"BLOCKED")
        self.assertFalse(r["alpha_verified"])
        for fold in r["folds"]:
            self.assertLess(fold["last_mature_training_exit"],fold["signal_date"])
            self.assertEqual(fold["selected_count"],1)
        changed=copy.deepcopy(o)
        changed[20*5]["prices"][-1]["close"]="150"
        alt=m.evaluate(f,changed,**args)
        self.assertEqual(r["folds"][0]["fitted_state_sha256"],alt["folds"][0]["fitted_state_sha256"])
        self.assertEqual(r["folds"][0]["selection_sha256"],alt["folds"][0]["selection_sha256"])

    def test_no_survivor_only_fitting(self):
        f,o=fixture()
        with self.assertRaises(ValueError):
            m.evaluate(f,o[:-1],label_cutoff="2026-12-31",test_start=f[100]["signal_date"])
        f,o=fixture(17)
        r=m.evaluate(f,o,label_cutoff="2026-12-31",test_start=f[50]["signal_date"])
        self.assertFalse(r["model_trained"])

    def test_costs_apply_to_sale_not_cash(self):
        a=m.net_return(.98,.02,10)
        b=m.net_return(1,0,10)
        self.assertGreater(a,b)
        self.assertGreater(a,m.net_return(.98,.02,60))
