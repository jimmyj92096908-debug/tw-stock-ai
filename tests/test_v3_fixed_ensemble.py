"""Synthetic paired tests for fixed-weight ensemble, not real performance."""
import unittest
from datetime import date,timedelta
from src.v3_purged_logistic_baseline import purged_logistic_predictions
from src.v3_walkforward_probability_archive import walkforward_logistic_archive

LABEL="c"*64


class FixedEnsembleTests(unittest.TestCase):
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

    def fit(self,kind,rows=None):
        preds=[dict(stock_id=s,market="TWSE",currently_listed=True,
                    signal_date="2024-02-05",feature_available_date="2024-02-05",
                    feature_vintage_declared=True,features={"score":v})
               for s,v in (("2401",1.),("2402",-1.))]
        return purged_logistic_predictions(feature_names=["score"],
              label_protocol_sha256=LABEL,training_rows=self.rows() if rows is None else rows,
              prediction_rows=preds,decision_date="2024-02-05",model_kind=kind)

    def test_exact_component_average_and_distinct_protocol(self):
        a,b,c=[self.fit(k) for k in ("logistic","forest","ensemble")]
        self.assertEqual(c["status"],"RETROSPECTIVE_FIXED_ENSEMBLE")
        self.assertEqual(len({r["protocol_sha256"] for r in (a,b,c)}),3)
        self.assertEqual(len({r["training_fingerprint"] for r in (a,b,c)}),1)
        for pa,pb,pc in zip(a["predictions"],b["predictions"],c["predictions"]):
            self.assertAlmostEqual(pc["probability"],.5*(pa["probability"]+pb["probability"]))
            self.assertEqual(pc["training_labels_through"],pa["training_labels_through"])
        self.assertFalse(c["calibrated_probability"])
        self.assertEqual(c["model_release"],"BLOCKED")
        self.assertFalse(c["trading_approved"])

    def test_determinism_and_maturity(self):
        r=self.fit("ensemble")
        self.assertEqual(r,self.fit("ensemble",list(reversed(self.rows()))))
        extra=[dict(x,signal_date="2024-02-02",feature_available_date="2024-02-02",
                    exit_date="2024-02-03",label_available_date="2024-02-05")
               for x in self.rows()[:10]]
        q=self.fit("ensemble",self.rows()+extra)
        self.assertEqual(q["fit_sha256"],r["fit_sha256"])
        self.assertEqual(q["predictions"],r["predictions"])
        self.assertEqual(q["purged_dates"],1)

    def test_insufficient_training_abstains(self):
        self.assertEqual(self.fit("ensemble",self.rows()[:100])["predictions"],[])

    def test_walkforward_ensemble(self):
        r=walkforward_logistic_archive(rows=self.rows(),feature_names=["score"],
                   label_protocol_sha256=LABEL,evaluation_dates=["2024-01-26","2024-01-29"],
                   archive_cutoff="2024-02-05",model_kind="ensemble")
        self.assertEqual(len(r["predictions"]),20)
        self.assertEqual(len(r["mature_outcomes"]),20)
        self.assertTrue(all(f["status"]=="RETROSPECTIVE_FIXED_ENSEMBLE" for f in r["folds"]))
        self.assertTrue(all(p["protocol_sha256"]==r["protocol_sha256"] for p in r["predictions"]))


if __name__=="__main__":
    unittest.main()
