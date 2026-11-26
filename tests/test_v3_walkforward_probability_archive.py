"""Synthetic chronological forecast archive and maturity isolation checks."""
import unittest
from datetime import date,timedelta
from src.v3_walkforward_probability_archive import walkforward_logistic_archive, mature_evidence_before

LABEL="b"*64


class WalkforwardArchiveTests(unittest.TestCase):
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

    def run_case(self,**kw):
        args=dict(rows=self.rows(),feature_names=["score"],label_protocol_sha256=LABEL,
                  evaluation_dates=["2024-01-26","2024-01-29","2024-01-31"],
                  archive_cutoff="2024-02-05")
        args.update(kw)
        return walkforward_logistic_archive(**args)

    def test_refit_and_mature_stream(self):
        r=self.run_case()
        self.assertEqual(len(r["predictions"]),30)
        self.assertEqual(len(r["mature_outcomes"]),30)
        self.assertEqual([f["training_dates"] for f in r["folds"]],[22,25,27])
        self.assertEqual(len(mature_evidence_before(r,decision_date="2024-01-29")),10)
        self.assertEqual(len(mature_evidence_before(r,decision_date="2024-01-31")),10)
        self.assertEqual(len(mature_evidence_before(r,decision_date="2024-02-01")),20)
        self.assertEqual(r["model_release"],"BLOCKED")

    def test_future_outcome_mutation_does_not_change_prior_forecast(self):
        rows=self.rows()
        for x in rows:
            if x["signal_date"]>="2024-01-26":
                x["net_return"]=-x["net_return"]
        a,b=self.run_case(),self.run_case(rows=rows)
        self.assertEqual(a["predictions"][:10],b["predictions"][:10])
        self.assertEqual(a["folds"][0],b["folds"][0])
        self.assertNotEqual(a["mature_outcomes"],b["mature_outcomes"])

    def test_cohort_maturity_is_atomic(self):
        rows=self.rows()
        next(x for x in rows if x["signal_date"]=="2024-01-26")["label_available_date"]="2024-02-05"
        r=self.run_case(rows=rows)
        self.assertEqual(len(r["predictions"]),30)
        self.assertEqual(len(r["mature_outcomes"]),20)
        self.assertEqual(mature_evidence_before(r,decision_date="2024-01-29"),[])

    def test_invalid_dates_and_duplicates(self):
        for kw in ({"evaluation_dates":["2024-01-29","2024-01-26"]},
                   {"evaluation_dates":["2024-02-01"]},
                   {"rows":self.rows()+self.rows()[:1]}):
            with self.assertRaises(ValueError):
                self.run_case(**kw)
        with self.assertRaises(ValueError):
            mature_evidence_before(self.run_case(),decision_date="2024-02-06")

    def test_order_invariance(self):
        self.assertEqual(self.run_case(),self.run_case(rows=list(reversed(self.rows()))))


if __name__=="__main__":
    unittest.main()
