"""Synthetic training and leakage tests; no real stock performance claims."""
import unittest
from datetime import date,timedelta
from src.v3_purged_logistic_baseline import purged_logistic_predictions

LABEL="b"*64


class PurgedLogisticTests(unittest.TestCase):
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
                for i in range(20) for j in range(10)]

    def prediction(self,s,score):
        return dict(stock_id=s,market="TWSE",currently_listed=True,
                    signal_date="2024-02-01",feature_available_date="2024-02-01",
                    feature_vintage_declared=True,features={"score":score})

    def run_case(self,**kw):
        args=dict(feature_names=["score"],label_protocol_sha256=LABEL,
                  training_rows=self.history(),decision_date="2024-02-01",
                  prediction_rows=[self.prediction("2401",1),self.prediction("2402",-1)])
        args.update(kw)
        return purged_logistic_predictions(**args)

    def test_actual_fit_and_reproducibility(self):
        r=self.run_case()
        self.assertEqual(r["status"],"RETROSPECTIVE_LOGISTIC_BASELINE")
        self.assertEqual(r["training_rows"],200)
        self.assertEqual(r["training_dates"],20)
        self.assertGreater(r["predictions"][0]["probability"],.8)
        self.assertLess(r["predictions"][1]["probability"],.2)
        self.assertEqual(r,self.run_case(training_rows=list(reversed(self.history()))))
        self.assertEqual(r["model_release"],"BLOCKED")
        self.assertFalse(r["calibrated_probability"])

    def test_purged_cohort_cannot_change_fit(self):
        extra=[dict(r,signal_date="2024-01-29",feature_available_date="2024-01-29",
                    exit_date="2024-01-30",label_available_date="2024-01-31")
               for r in self.history()[:10]]
        extra[0]["label_available_date"]="2024-02-01"
        a=self.run_case(training_rows=self.history()+extra)
        self.assertEqual(a["purged_dates"],1)
        self.assertEqual(a["fit_sha256"],self.run_case()["fit_sha256"])
        extra[1]["net_return"]=-.99
        extra[2]["features"]={"score":999}
        b=self.run_case(training_rows=self.history()+extra)
        self.assertEqual(a,b)

    def test_insufficient_rows_and_single_class(self):
        self.assertEqual(self.run_case(training_rows=self.history()[:-1])["predictions"],[])
        rows=[dict(r,net_return=.1) for r in self.history()]
        self.assertEqual(self.run_case(training_rows=rows)["predictions"],[])

    def test_future_features_and_outcome_fields_rejected(self):
        pred=self.prediction("2401",1)
        for patch in ({"feature_available_date":"2024-02-02"},
                      {"net_return":.1},{"stock_id":"1589"},{"stock_id":"1808"},
                      {"feature_vintage_declared":False}):
            with self.assertRaises(ValueError):
                self.run_case(prediction_rows=[dict(pred,**patch)])
        rows=self.history()
        rows[-1]["feature_available_date"]="2024-02-02"
        with self.assertRaises(ValueError):
            self.run_case(training_rows=rows)

    def test_protocol_duplicate_and_invalid_features(self):
        rows=self.history()
        with self.assertRaises(ValueError):
            self.run_case(training_rows=rows+[rows[0]])
        rows[-1]["label_protocol_sha256"]="a"*64
        with self.assertRaises(ValueError):
            self.run_case(training_rows=rows)
        with self.assertRaises(ValueError):
            self.run_case(feature_names=["future_return"])
        with self.assertRaises(ValueError):
            self.run_case(prediction_rows=[self.prediction("2401",float("nan"))])


if __name__=="__main__":
    unittest.main()
