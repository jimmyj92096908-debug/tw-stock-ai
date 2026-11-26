"""Five-model tuning integration; synthetic fits only."""
import unittest
from datetime import date,timedelta
from unittest.mock import patch
from importlib.metadata import version,PackageNotFoundError
from src.v3_tuned_five_ensemble import walkforward_tuned_five_ensemble
from src.v3_five_model_ensemble import MODELS


def backend_present():
    try:
        return all(version(k)==v for k,v in (("lightgbm","4.6.0"),("xgboost-cpu","2.1.4"),("catboost","1.2.8")))
    except PackageNotFoundError:
        return False


class TunedFiveTests(unittest.TestCase):
    def args(self):
        start=date(2024,1,1)
        rows=[dict(stock_id=str(2300+j),market="TWSE",currently_listed=True,
                    signal_date=(start+timedelta(days=i)).isoformat(),
                    feature_available_date=(start+timedelta(days=i)).isoformat(),
                    exit_date=(start+timedelta(days=i+1)).isoformat(),
                    label_available_date=(start+timedelta(days=i+2)).isoformat(),
                    feature_vintage_declared=True,label_protocol_sha256="d"*64,
                    features={"score":1.0 if j<5 else -1.0},
                    net_return=.06 if j<5 else -.02)
                for i in range(52) for j in range(10)]
        return dict(rows=rows,feature_names=["score"],label_protocol_sha256="d"*64,
                  development_dates=[(start+timedelta(days=i)).isoformat() for i in range(22,44)],
                  holdout_dates=["2024-02-16","2024-02-19"],
                  selection_cutoff="2024-02-15",archive_cutoff="2024-02-25")

    def test_insufficient_evidence_stops_before_other_components(self):
        args=self.args()
        args["development_dates"]=["2024-01-23"]
        with patch("src.v3_tuned_five_ensemble.frozen_forest_tuning") as forest:
            r=walkforward_tuned_five_ensemble(**args)
            forest.assert_not_called()
        self.assertEqual(r["blocked_component"],"logistic")
        self.assertIsNone(r["ensemble"])
        self.assertFalse(r["trading_approved"])

    def fake_fit(self,X,y,*,depth):
        return {"depth":depth},lambda x:(.95 if x[0]>0 else .05) if depth==2 else .5

    def check_result(self,r):
        self.assertEqual(r["status"],"TUNED_FIVE_RETROSPECTIVE_RESEARCH")
        self.assertEqual(set(r["component_reports"]),set(MODELS))
        self.assertEqual(len({v["selection_sha256"] for v in r["component_reports"].values()}),5)
        self.assertTrue(r["hyperparameters_frozen"])
        self.assertEqual(len(r["ensemble"]["predictions"]),20)
        self.assertEqual(len(r["ensemble"]["mature_outcomes"]),20)
        self.assertTrue(all(w["weights"]==dict.fromkeys(MODELS,.2) for w in r["ensemble"]["weight_log"]))
        self.assertFalse(r["pristine_holdout_verified"])
        self.assertEqual(r["model_release"],"BLOCKED")

    def test_integrated_selection_and_future_mutation(self):
        with patch("src.v3_purged_logistic_baseline.fit_lightgbm",side_effect=self.fake_fit),patch("src.v3_purged_logistic_baseline.fit_xgboost",side_effect=self.fake_fit),patch("src.v3_purged_logistic_baseline.fit_catboost",side_effect=self.fake_fit):
            a=walkforward_tuned_five_ensemble(**self.args())
            args=self.args()
            for row in args["rows"]:
                if row["signal_date"]>="2024-02-15":
                    row["net_return"]=-row["net_return"]
            b=walkforward_tuned_five_ensemble(**args)
        self.check_result(a)
        self.assertEqual(a["selection_sha256"],b["selection_sha256"])
        self.assertEqual(a["ensemble"]["predictions"][:10],b["ensemble"]["predictions"][:10])
        self.assertNotEqual(a["ensemble"]["mature_outcomes"],b["ensemble"]["mature_outcomes"])

    @unittest.skipUnless(backend_present(),"Optional pinned boosters absent")
    def test_real_tuned_five_ensemble(self):
        self.check_result(walkforward_tuned_five_ensemble(**self.args()))


if __name__=="__main__":
    unittest.main()
