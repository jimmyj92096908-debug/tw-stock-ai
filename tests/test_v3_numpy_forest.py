"""Synthetic nonlinear learning and forest chronology regression tests."""
import unittest
from datetime import date,timedelta

from src.v3_purged_logistic_baseline import purged_logistic_predictions
from src.v3_walkforward_probability_archive import walkforward_logistic_archive

LABEL="b"*64


class ForestTests(unittest.TestCase):
    def history(self):
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

    def prediction(self,s,score):
        return dict(stock_id=s,market="TWSE",currently_listed=True,
                    signal_date="2024-02-05",feature_available_date="2024-02-05",
                    feature_vintage_declared=True,features={"score":score})

    def run_case(self,**kw):
        args=dict(feature_names=["score"],label_protocol_sha256=LABEL,
                  training_rows=self.history(),decision_date="2024-02-05",
                  prediction_rows=[self.prediction("2401",1),self.prediction("2402",-1)],
                  model_kind="forest")
        args.update(kw)
        return purged_logistic_predictions(**args)

    def test_forest_fit_and_protocol_separation(self):
        r=self.run_case()
        self.assertEqual(r["status"],"RETROSPECTIVE_NUMPY_FOREST")
        self.assertGreater(r["predictions"][0]["probability"],.9)
        self.assertLess(r["predictions"][1]["probability"],.1)
        self.assertNotEqual(r["protocol_sha256"],self.run_case(model_kind="logistic")["protocol_sha256"])
        self.assertEqual(r,self.run_case(training_rows=list(reversed(self.history()))))
        self.assertFalse(r["calibrated_probability"])
        self.assertEqual(r["model_release"],"BLOCKED")

    def test_nonlinear_interval(self):
        rows=self.history()
        for r in rows:
            j=int(r["stock_id"])-2300
            v=(-1.,0.,1.)[j%3]
            r["features"]={"score":v}
            r["net_return"]=.06 if v==0 else -.02
        r=self.run_case(training_rows=rows,prediction_rows=[
            self.prediction("2401",-1),self.prediction("2402",0),self.prediction("2403",1)])
        a,b,c=[p["probability"] for p in r["predictions"]]
        self.assertGreater(b,.8)
        self.assertLess(max(a,c),.2)

    def test_mature_cohort_purge(self):
        rows=self.history()
        extra=[dict(r,signal_date="2024-02-02",feature_available_date="2024-02-02",
                    exit_date="2024-02-03",label_available_date="2024-02-05")
               for r in rows[:10]]
        r=self.run_case(training_rows=rows+extra)
        self.assertEqual(r["purged_dates"],1)
        self.assertEqual(r["fit_sha256"],self.run_case()["fit_sha256"])

    def test_invalid_and_sparse_inputs(self):
        self.assertEqual(self.run_case(training_rows=self.history()[:100])["predictions"],[])
        with self.assertRaises(ValueError):
            self.run_case(model_kind="unknown")
        with self.assertRaises(ValueError):
            self.run_case(prediction_rows=[dict(self.prediction("2401",1),net_return=.1)])

    def test_forest_archive(self):
        r=walkforward_logistic_archive(rows=self.history(),feature_names=["score"],
                 label_protocol_sha256=LABEL,evaluation_dates=["2024-01-26","2024-01-29"],
                 archive_cutoff="2024-02-05",model_kind="forest")
        self.assertEqual(len(r["predictions"]),20)
        self.assertEqual(len(r["mature_outcomes"]),20)
        self.assertTrue(all(f["status"]=="RETROSPECTIVE_NUMPY_FOREST" for f in r["folds"]))


if __name__=="__main__":
    unittest.main()
