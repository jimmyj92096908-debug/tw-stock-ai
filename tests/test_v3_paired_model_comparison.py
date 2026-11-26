"""Synthetic paired model comparison; not a claim of market profitability."""
import unittest
from datetime import date,timedelta

from src.v3_paired_model_comparison import compare_probability_models


class PairedComparisonTests(unittest.TestCase):
    def rows(self):
        start=date(2024,1,2)
        return [dict(stock_id=str(2300+j),market="TWSE",currently_listed=True,
                    signal_date=(start+timedelta(days=i)).isoformat(),
                    feature_available_date=(start+timedelta(days=i)).isoformat(),
                    exit_date=(start+timedelta(days=i+1)).isoformat(),
                    label_available_date=(start+timedelta(days=i+2)).isoformat(),
                    feature_vintage_declared=True,label_protocol_sha256="c"*64,
                    features={"score":1.0 if j<5 else -1.0},
                    net_return=.06 if j<5 else -.02)
                for i in range(30) for j in range(10)]

    def run_case(self,**kw):
        args=dict(rows=self.rows(),feature_names=["score"],
                  label_protocol_sha256="c"*64,evaluation_dates=["2024-01-26","2024-01-29"],
                  archive_cutoff="2024-02-05")
        args.update(kw)
        return compare_probability_models(**args)

    def test_paired_mature_metrics_and_fixed_screen(self):
        r=self.run_case()
        self.assertEqual(r["matched_observations"],20)
        self.assertEqual(r["matched_signal_dates"],2)
        self.assertEqual(r["constant_0_5_reference"]["brier"],.25)
        self.assertEqual(r["constant_0_5_reference"]["screened_count"],0)
        for m in r["models"].values():
            self.assertEqual(m["forecast_count"],20)
            self.assertLess(m["metrics"]["brier"],.25)
            self.assertEqual(m["metrics"]["accuracy_at_0_5"],1)
            self.assertEqual(m["metrics"]["screened_count"],10)
            self.assertEqual(m["metrics"]["screened_outcomes"]["net_win_rate"],1)
            self.assertFalse(m["metrics"]["screened_outcomes"]["point_targets_met"])
        self.assertIsNone(r["selected_model"])
        self.assertFalse(r["portfolio_returns_verified"])
        self.assertEqual(r["model_release"],"BLOCKED")

    def test_incomplete_cohort_not_used_in_metrics(self):
        rows=self.rows()
        next(x for x in rows if x["signal_date"]=="2024-01-29")["label_available_date"]="2024-02-05"
        r=self.run_case(rows=rows)
        self.assertEqual(r["matched_observations"],10)
        self.assertEqual(r["matched_signal_dates"],1)
        self.assertTrue(all(m["forecast_count"]==20 for m in r["models"].values()))

    def test_no_mature_outcomes_returns_no_scores(self):
        r=self.run_case(evaluation_dates=["2024-01-04"])
        self.assertEqual(r["status"],"NO_MATURE_MATCHED_OUTCOMES")
        self.assertIsNone(r["constant_0_5_reference"])
        self.assertTrue(all(m["metrics"] is None for m in r["models"].values()))

    def test_order_invariance(self):
        self.assertEqual(self.run_case(),self.run_case(rows=list(reversed(self.rows()))))


if __name__=="__main__":
    unittest.main()
