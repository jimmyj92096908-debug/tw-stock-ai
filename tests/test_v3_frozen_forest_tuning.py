"""Synthetic frozen hyperparameter selection regression tests."""
import unittest
from datetime import date,timedelta
from src.v3_frozen_forest_tuning import frozen_forest_tuning


class FrozenForestTuningTests(unittest.TestCase):
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

    def run_case(self,**kw):
        start=date(2024,1,1)
        args=dict(rows=self.rows(),feature_names=["score"],label_protocol_sha256="d"*64,
                  development_dates=[(start+timedelta(days=i)).isoformat() for i in range(22,44)],
                  holdout_dates=["2024-02-16","2024-02-19"],
                  selection_cutoff="2024-02-15",archive_cutoff="2024-02-25")
        args.update(kw)
        return frozen_forest_tuning(**args)

    def test_actual_selection_and_frozen_protocol(self):
        r=self.run_case()
        self.assertEqual(r["status"],"FROZEN_DEVELOPMENT_SELECTION")
        self.assertIn(r["selected_depth"],(2,4,6))
        self.assertEqual([s["depth"] for s in r["development_scores"]],[2,4,6])
        winner=min(r["development_scores"],key=lambda x:(round(x["brier"],12),x["depth"]!=4,x["depth"]))
        self.assertEqual(r["selected_depth"],winner["depth"])
        self.assertEqual(len({x["protocol_sha256"] for x in r["development_scores"]}),3)
        self.assertTrue(all(x["dates"]>=20 for x in r["development_scores"]))
        a=r["holdout_archive"]
        self.assertEqual(len(a["predictions"]),20)
        self.assertNotEqual(a["protocol_sha256"],a["component_protocol_sha256"])
        self.assertTrue(all(p["protocol_sha256"]==a["protocol_sha256"] for p in a["predictions"]))
        self.assertFalse(r["pristine_holdout_verified"])
        self.assertEqual(r["model_release"],"BLOCKED")

    def test_holdout_mutations_do_not_change_selection(self):
        r=self.run_case()
        rows=self.rows()
        for row in rows:
            if row["signal_date"]>="2024-02-15":
                row["net_return"]=-row["net_return"]
        q=self.run_case(rows=rows)
        self.assertEqual(r["selection_sha256"],q["selection_sha256"])
        self.assertEqual(r["development_scores"],q["development_scores"])
        self.assertEqual(r["holdout_archive"]["predictions"][:10],
                         q["holdout_archive"]["predictions"][:10])
        self.assertNotEqual(r["holdout_archive"]["mature_outcomes"],
                            q["holdout_archive"]["mature_outcomes"])

    def test_insufficient_development_abstains(self):
        r=self.run_case(development_dates=["2024-01-23"])
        self.assertIsNone(r["selected_depth"])
        self.assertIsNone(r["holdout_archive"])

    def test_overlap_rejected(self):
        with self.assertRaises(ValueError):
            self.run_case(holdout_dates=["2024-02-01"])
        with self.assertRaises(ValueError):
            self.run_case(selection_cutoff="2024-02-01")


if __name__=="__main__":
    unittest.main()
