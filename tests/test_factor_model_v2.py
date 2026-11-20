"""Regression contract for strict adjusted-return holdout evaluation."""
import unittest
from datetime import date
from src.factor_model_v2 import evaluate_adjusted, ADJUSTED_EVALUATION_SQL


def row(i, *, signal="2026-10-01", score=None, entry=100, exit_=105,
        exit_date="2026-10-09", adjusted=100):
    return dict(market="twse",stock_id=str(i),as_of_date=date.fromisoformat(signal),
                total_score=100-i if score is None else score,
                coverage_weight=.60,adjusted_close=adjusted,entry_close=entry,
                exit_close=exit_,exit_date=date.fromisoformat(exit_date) if exit_date else None)


class AdjustedFactorModelV2Tests(unittest.TestCase):
    def test_adjusted_label_and_cost_are_really_applied(self):
        rows=[row(i,exit_=110 if i==0 else 100) for i in range(10)]
        result=evaluate_adjusted(rows,round_trip_cost_bps=30)
        self.assertEqual(result["holdout"]["cohorts"],1)
        self.assertAlmostEqual(result["cohorts"][0]["top_gross"],.05)
        self.assertAlmostEqual(result["cohorts"][0]["top_net_after_assumed_cost"],.047)
        self.assertAlmostEqual(result["cohorts"][0]["net_excess_vs_gross_universe"],.037)
        self.assertTrue(result["research_only"])

    def test_incomplete_forward_label_invalidates_entire_cohort(self):
        rows=[row(i) for i in range(10)]
        rows[0]["exit_close"]=None
        result=evaluate_adjusted(rows)
        self.assertEqual(result["holdout"]["cohorts"],0)
        self.assertEqual(result["missing_forward_labels_in_large_cohorts"],1)
        self.assertEqual(result["skipped_dates"]["incomplete_forward_label"],1)
        self.assertIsNone(result["holdout"]["mean_gross_excess"])

    def test_missing_adjusted_signal_is_explicitly_excluded(self):
        rows=[row(i) for i in range(6)]
        rows[0]["adjusted_close"]=None
        result=evaluate_adjusted(rows)
        self.assertEqual(result["excluded"]["missing_adjusted_signal_close"],1)
        self.assertEqual(result["holdout"]["cohorts"],1)

    def test_development_does_not_read_exit_from_holdout(self):
        rows=[row(i,signal="2026-09-30",exit_date="2026-10-08") for i in range(5)]
        result=evaluate_adjusted(rows)
        self.assertEqual(result["skipped_dates"]["development_holdout_boundary"],1)
        self.assertEqual(result["development"]["cohorts"],0)
        rows=[row(i,signal="2026-09-18",exit_date="2026-09-28") for i in range(5)]
        self.assertEqual(evaluate_adjusted(rows)["development"]["cohorts"],1)

    def test_reversed_inputs_cannot_affect_model(self):
        rows=[row(i,score=90 if i<3 else 50,exit_=100+i) for i in range(10)]
        self.assertEqual(evaluate_adjusted(rows),evaluate_adjusted(list(reversed(rows))))

    def test_no_parameter_tuning_outside_cost_bounds(self):
        for cost in (-1,1001):
            with self.assertRaises(ValueError):
                evaluate_adjusted([],round_trip_cost_bps=cost)
        with self.assertRaises(ValueError):
            evaluate_adjusted([],holdout_start="not-a-date")

    def test_lead_uses_raw_session_timeline_and_adjusted_prices(self):
        sql=ADJUSTED_EVALUATION_SQL
        self.assertIn("FROM public.daily_prices p",sql)
        self.assertIn("LEFT JOIN public.daily_adjusted_prices a",sql)
        self.assertIn("LEAD(a.close,1)",sql)
        self.assertIn("LEAD(a.close,6)",sql)
        self.assertIn("LEAD(p.trade_date,6)",sql)
        self.assertIn("b.trade_date=s.as_of_date",sql)
        self.assertNotIn("INSERT ",sql)
        self.assertNotIn("UPDATE ",sql)

    def test_missing_future_does_not_make_hit_rate(self):
        rows=[row(i,exit_=None) for i in range(10)]
        result=evaluate_adjusted(rows)
        self.assertEqual(result["holdout"]["cohorts"],0)
        self.assertIsNone(result["holdout"]["positive_net_excess_fraction"])


if __name__=="__main__":
    unittest.main()
