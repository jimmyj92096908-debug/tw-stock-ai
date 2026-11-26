"""Frozen booster depth tuning contracts and mandatory backend CI smoke."""
import unittest
from datetime import date,timedelta
from importlib.metadata import version,PackageNotFoundError
from unittest.mock import patch

from src.v3_frozen_booster_tuning import frozen_booster_tuning

MODELS=("lightgbm","xgboost","catboost")

def backend_present():
    try:
        return all(version(k)==v for k,v in (("lightgbm","4.6.0"),("xgboost-cpu","2.1.4"),("catboost","1.2.8")))
    except PackageNotFoundError:
        return False


class FrozenBoosterTests(unittest.TestCase):
    def rows(self):
        start=date(2024,1,1)
        return [dict(stock_id=str(2300+j),market="TWSE",currently_listed=True,
                    signal_date=(start+timedelta(days=i)).isoformat(),
                    feature_available_date=(start+timedelta(days=i)).isoformat(),
                    exit_date=(start+timedelta(days=i+1)).isoformat(),
                    label_available_date=(start+timedelta(days=i+2)).isoformat(),
                    feature_vintage_declared=True,label_protocol_sha256="d"*64,
                    features={"score":1.0 if j<5 else -1.0},
                    net_return=.06 if j<5 else -.02)
                for i in range(52) for j in range(10)]

    def run_case(self,kind,**kw):
        start=date(2024,1,1)
        args=dict(model_kind=kind,rows=self.rows(),feature_names=["score"],label_protocol_sha256="d"*64,
                  development_dates=[(start+timedelta(days=i)).isoformat() for i in range(22,44)],
                  holdout_dates=["2024-02-16","2024-02-19"],
                  selection_cutoff="2024-02-15",archive_cutoff="2024-02-25")
        args.update(kw)
        return frozen_booster_tuning(**args)

    def fake_fit(self,X,y,*,depth):
        return {"depth":depth},lambda x:(.95 if x[0]>0 else .05) if depth==2 else .5

    def test_selection_and_future_outcome_isolation(self):
        for kind in MODELS:
            with self.subTest(kind=kind),patch("src.v3_purged_logistic_baseline.fit_"+kind,side_effect=self.fake_fit):
                a=self.run_case(kind)
                self.assertEqual(a["selected_depth"],2)
                self.assertEqual(len(a["holdout_archive"]["predictions"]),20)
                self.assertEqual(len({x["protocol_sha256"] for x in a["development_scores"]}),3)
                rows=self.rows()
                for r in rows:
                    if r["signal_date"]>="2024-02-15":
                        r["net_return"]=-r["net_return"]
                b=self.run_case(kind,rows=rows)
                self.assertEqual(a["selection_sha256"],b["selection_sha256"])
                self.assertEqual(a["holdout_archive"]["predictions"][:10],b["holdout_archive"]["predictions"][:10])
                self.assertEqual(a["model_release"],"BLOCKED")

    def test_invalid_kind_and_overlap(self):
        with self.assertRaises(ValueError):
            self.run_case("forest")
        with self.assertRaises(ValueError):
            self.run_case("lightgbm",holdout_dates=["2024-02-01"])

    @unittest.skipUnless(backend_present(),"Optional pinned boosters absent")
    def test_real_all_booster_depths(self):
        for kind in MODELS:
            with self.subTest(kind=kind):
                r=self.run_case(kind)
                self.assertIn(r["selected_depth"],(2,4,6))
                self.assertEqual(len(r["holdout_archive"]["predictions"]),20)
                self.assertTrue(all(s["brier"] is not None for s in r["development_scores"]))
                self.assertEqual(len({x["protocol_sha256"] for x in r["development_scores"]}),3)
                self.assertEqual(r["model_release"],"BLOCKED")


if __name__=="__main__":
    unittest.main()
