"""No hidden model promotion via overlapping frozen research windows."""
from __future__ import annotations

from datetime import date,timedelta
from pathlib import Path
import unittest

from src.frozen_cohort_progress import DATES_SQL,MAX_DAYS,summarize_progress
from scripts import audit_recent_frozen_cohorts as cli


def waiting(signal="2026-11-20",hash_="a"*64):
    return {
        "model_version":"tw-factor-ridge-1",
        "signal_date":signal,"model_sha256":hash_,
        "cohort_sha256":"b"*64,
        "universe_count":50,"selected_count":10,
        "matured_members":0,
        "status":"AWAIT_ENTRY",
        "portfolio_entry_date":None,"portfolio_exit_date":None,
        "model_net_excess":None,"baseline_net_excess":None,
        "production_database_written":False,
        "line_signal_delivery_approved":False,
        "live_trading_approved":False,
    }


def complete(signal,entry,exit_):
    return {
        **waiting(signal),
        "matured_members":50,
        "status":"FULL_COHORT_MATURE_RESEARCH_ONLY",
        "portfolio_entry_date":entry,
        "portfolio_exit_date":exit_,
        "model_net_excess":.02,
        "baseline_net_excess":.005,
        "independently_verified_investment_alpha":False,
        "corporate_action_adjustment_vintage_verified":False,
    }


class RecentResearchProgressTests(unittest.TestCase):
    def test_current_unmatured_research_has_zero_proven_alpha(self):
        s=summarize_progress([waiting()],market_date=date(2026,11,20),limit=6)
        self.assertEqual(s["audited_frozen_days"],1)
        self.assertEqual(s["cohort_status_counts"],{"AWAIT_ENTRY":1})
        self.assertEqual(s["mature_full_cohorts"],0)
        self.assertIsNone(s["exploratory_nonoverlap_model_mean_net_excess"])
        self.assertFalse(s["minimum_window_count_met_within_this_bounded_sample"])
        self.assertEqual(s["research_model_release_decision"],"BLOCKED")
        self.assertFalse(s["line_signal_delivery_approved"])
        self.assertFalse(s["live_trading_approved"])

    def test_overlap_cannot_count_as_two_independent_holdout_periods(self):
        r=[
          complete("2026-11-20","2026-11-23","2026-11-30"),
          complete("2026-11-24","2026-11-25","2026-12-02"),
          complete("2026-12-01","2026-12-03","2026-12-09"),
        ]
        s=summarize_progress(r,market_date="2026-12-31",limit=6)
        self.assertEqual(s["mature_full_cohorts"],3)
        self.assertEqual(s["independent_nonoverlapping_complete_windows"],2)
        self.assertIsNone(s["exploratory_nonoverlap_model_mean_net_excess"])
        self.assertEqual(s["research_model_release_decision"],"BLOCKED")

    def test_even_ten_disjoint_windows_only_exploratory_not_live(self):
        anchor=date(2026,1,2)
        periods=[]
        for i in range(10):
            signal=anchor+timedelta(days=i*15)
            periods.append(complete(signal.isoformat(),
                                    (signal+timedelta(days=1)).isoformat(),
                                    (signal+timedelta(days=8)).isoformat()))
        s=summarize_progress(periods,market_date="2026-11-20",limit=10)
        self.assertEqual(s["independent_nonoverlapping_complete_windows"],10)
        self.assertTrue(s["minimum_window_count_met_within_this_bounded_sample"])
        self.assertAlmostEqual(s["exploratory_nonoverlap_model_mean_net_excess"],0.02)
        self.assertAlmostEqual(s["exploratory_nonoverlap_baseline_mean_net_excess"],0.005)
        self.assertFalse(s["pristine_future_holdout_independently_reviewed"])
        self.assertFalse(s["corporate_action_asof_vintage_audited"])
        self.assertEqual(s["research_model_release_decision"],"BLOCKED")
        self.assertFalse(s["live_trading_approved"])

    def test_invalid_saved_roster_hash_dates_permissions_and_partial_labels_fail(self):
        base=waiting()
        cases=[
            [{**base,"signal_date":"2026-12-01"}],
            [base,base],
            [{**base,"model_sha256":"invalid"}],
            [{**base,"line_signal_delivery_approved":True}],
            [{**base,"status":"AWAIT_ENTRY","model_net_excess":.05}],
            [{**base,"status":"FULL_COHORT_MATURE_RESEARCH_ONLY"}],
            [{**base,"model_version":"new-unapproved-version"}],
        ]
        for rs in cases:
            with self.subTest(rs=rs):
                with self.assertRaises((ValueError,KeyError)):
                    summarize_progress(rs,market_date=date(2026,11,20),limit=6)
        r=[waiting(),{**waiting("2026-11-19"),"model_sha256":"c"*64}]
        with self.assertRaisesRegex(ValueError,"different model artifacts"):
            summarize_progress(r,market_date=date(2026,11,20),limit=6)
        for limit in (0,13,True):
            with self.assertRaises(ValueError):
                summarize_progress([],market_date=date(2026,11,20),limit=limit)

    def test_bounded_sql_and_real_db_read_only_contract(self):
        self.assertIn("FROM public.research_forward_frozen_cohorts",DATES_SQL)
        self.assertIn("ORDER BY signal_date DESC",DATES_SQL)
        self.assertIn("LIMIT %s::integer",DATES_SQL)
        self.assertEqual(MAX_DAYS,12)
        source=(Path(__file__).resolve().parents[1]/
                "scripts/audit_recent_frozen_cohorts.py").read_text()
        self.assertIn("default_transaction_read_only=on",source)
        self.assertIn("REPEATABLE READ READ ONLY",source)
        self.assertIn("statement_timeout='25000ms'",source)
        self.assertIn("FROZEN_LABEL_SQL",source)
        self.assertNotIn("LINE_CHANNEL",source)
        with self.assertRaises(ValueError):
            cli.run("",limit=6)


if __name__=="__main__":
    unittest.main()
