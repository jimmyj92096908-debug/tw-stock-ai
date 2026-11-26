"""CatBoost integration contracts; real backend smoke test is optional."""
import unittest
from datetime import date,timedelta
from importlib.metadata import version,PackageNotFoundError
from unittest.mock import patch
import numpy as np

from src.v3_catboost_adapter import fit_catboost,CATBOOST_VERSION
from src.v3_purged_logistic_baseline import purged_logistic_predictions
from src.v3_walkforward_probability_archive import walkforward_logistic_archive

LABEL="d"*64

def backend_present():
    try:
        return version("catboost")==CATBOOST_VERSION
    except PackageNotFoundError:
        return False


class CatBoostTests(unittest.TestCase):
    def rows(self):
        start=date(2024,1,2)
        return [dict(stock_id=str(2300+j),market="TWSE",currently_listed=True,
                    signal_date=(start+timedelta(days=i)).isoformat(),
                    feature_available_date=(start+timedelta(days=i)).isoformat(),
                    exit_date=(start+timedelta(days=i+1)).isoformat(),
                    label_available_date=(start+timedelta(days=i+2)).isoformat(),
                    feature_vintage_declared=True,label_protocol_sha256=LABEL,
                    features={"score":1.0 if j<5 else -1.0},
                    net_return=.06 if j<5 else -.02)
                for i in range(30) for j in range(10)]

    def fit(self,rows=None,model_kind="catboost"):
        return purged_logistic_predictions(feature_names=["score"],
                    label_protocol_sha256=LABEL,training_rows=self.rows() if rows is None else rows,
                    prediction_rows=[dict(stock_id="2401",market="TWSE",currently_listed=True,
                         signal_date="2024-02-05",feature_available_date="2024-02-05",
                         feature_vintage_declared=True,features={"score":1.0})],
                    decision_date="2024-02-05",model_kind=model_kind)

    def test_missing_backend_and_version_mismatch_block(self):
        X=np.array([[-1.],[1.]])
        y=np.array([0.,1.])
        for effect in (PackageNotFoundError("catboost"),):
            with patch("src.v3_catboost_adapter.version",side_effect=effect):
                with self.assertRaisesRegex(RuntimeError,"not installed"):
                    fit_catboost(X,y)
        with patch("src.v3_catboost_adapter.version",return_value="0.0.0"):
            with self.assertRaisesRegex(RuntimeError,"Unexpected CatBoost version"):
                fit_catboost(X,y)

    def test_purge_before_backend_and_distinct_protocol(self):
        extra=[dict(x,signal_date="2024-02-02",feature_available_date="2024-02-02",
                    exit_date="2024-02-03",label_available_date="2024-02-05")
               for x in self.rows()[:10]]
        with patch("src.v3_purged_logistic_baseline.fit_catboost",
                   return_value=({"mock":True},lambda x:.7)) as fit:
            report=self.fit(self.rows()+extra)
            self.assertEqual(report["training_rows"],300)
            self.assertEqual(report["purged_dates"],1)
            self.assertEqual(fit.call_args.args[0].shape,(300,1))
            self.assertEqual(report["predictions"][0]["probability"],.7)
            self.assertEqual(report["model_release"],"BLOCKED")
            self.assertFalse(report["calibrated_probability"])
            self.assertNotEqual(report["protocol_sha256"],self.fit(model_kind="logistic")["protocol_sha256"])

    def test_insufficient_training_never_loads_backend(self):
        with patch("src.v3_purged_logistic_baseline.fit_catboost") as fit:
            self.assertEqual(self.fit(self.rows()[:100])["predictions"],[])
            fit.assert_not_called()

    def test_archive_integration_contract(self):
        with patch("src.v3_purged_logistic_baseline.fit_catboost",
                   return_value=({"mock":True},lambda x:.7)):
            r=walkforward_logistic_archive(rows=self.rows(),feature_names=["score"],
                       label_protocol_sha256=LABEL,evaluation_dates=["2024-01-26","2024-01-29"],
                       archive_cutoff="2024-02-05",model_kind="catboost")
        self.assertEqual(len(r["predictions"]),20)
        self.assertEqual(len(r["mature_outcomes"]),20)
        self.assertTrue(all(f["status"]=="RETROSPECTIVE_CATBOOST" for f in r["folds"]))

    @unittest.skipUnless(backend_present(),"Optional pinned CatBoost backend absent")
    def test_real_backend_smoke(self):
        a=self.fit()
        b=self.fit(list(reversed(self.rows())))
        self.assertEqual(a,b)
        self.assertGreater(a["predictions"][0]["probability"],.8)
        self.assertEqual(a["status"],"RETROSPECTIVE_CATBOOST")
        self.assertFalse(a["trading_approved"])


if __name__=="__main__":
    unittest.main()
