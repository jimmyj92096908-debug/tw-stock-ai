"""Research-only prospective frozen model outcome maturity gates."""
from __future__ import annotations

from datetime import date
from pathlib import Path
import unittest

from src.research_forward_outcome import assess_frozen_outcomes,FROZEN_LABEL_SQL
from scripts import audit_frozen_forward_outcomes as cli


def row(n=50):
    k=10
    return {
        "model_version":"tw-factor-ridge-1",
        "signal_date":"2026-11-20",
        "model_sha256":"a"*64,"cohort_sha256":"b"*64,
        "frozen_at":"2026-11-21 05:59:00+00",
        "universe_count":n,"selected_count":k,
        "actual_members":n,
        "seen_entries":0,"seen_exits":0,"matured":0,
        "late_precommit":0,"aligned_entries":0,"aligned_exits":0,
        "first_entry":None,"last_entry":None,"first_exit":None,"last_exit":None,
        "model_selection":k,"baseline_selection":k,
        "model_mature_selection":0,"baseline_mature_selection":0,
        "universe_gross":None,"model_gross":None,"baseline_gross":None,
    }


class FrozenOutcomeReadinessTests(unittest.TestCase):
    def test_first_real_precommit_has_no_future_label_or_model_alpha(self):
        q=assess_frozen_outcomes(row(),cutoff=date(2026,11,20))
        self.assertEqual(q["status"],"AWAIT_ENTRY")
        self.assertIsNone(q["model_net_excess"])
        self.assertEqual(q["matured_members"],0)
        self.assertFalse(q["independently_verified_investment_alpha"])
        self.assertFalse(q["live_trading_approved"])
        self.assertFalse(q["line_signal_delivery_approved"])
        self.assertFalse(q["production_database_written"])

    def test_partial_future_labels_never_result_in_cherrypicked_performance(self):
        initial=row()
        next_=dict(initial,seen_entries=50)
        x=assess_frozen_outcomes(next_,cutoff=date(2026,11,23))
        self.assertEqual(x["status"],"AWAIT_SIX_TRADING_SESSIONS")
        partial=dict(next_,seen_exits=50,matured=49,aligned_entries=1,
                     aligned_exits=1,model_mature_selection=10,
                     baseline_mature_selection=10,
                     first_entry="2026-11-23",last_entry="2026-11-23",
                     first_exit="2026-11-30",last_exit="2026-11-30",
                     universe_gross="0.02",model_gross="0.03",baseline_gross="0.01")
        p=assess_frozen_outcomes(partial,cutoff=date(2026,11,30))
        self.assertEqual(p["status"],"INCOMPLETE_OFFICIAL_ADJUSTED_LABELS")
        self.assertIsNone(p["model_net_return"])
        self.assertIsNone(p["baseline_net_excess"])
        late=dict(partial,matured=49,late_precommit=1)
        self.assertEqual(
            assess_frozen_outcomes(late,cutoff=date(2026,11,30))["status"],
            "PRECOMMIT_AFTER_ENTRY_CLOSE")

    def test_mismatched_stock_entry_or_exit_dates_are_not_comparable(self):
        x=dict(row(),seen_entries=50,seen_exits=50,matured=50,
               aligned_entries=2,aligned_exits=2,
               model_mature_selection=10,baseline_mature_selection=10,
               first_entry="2026-11-23",last_entry="2026-11-24",
               first_exit="2026-11-30",last_exit="2026-12-01",
               universe_gross="0.02",model_gross="0.03",baseline_gross="0.01")
        out=assess_frozen_outcomes(x,cutoff=date(2026,12,1))
        self.assertEqual(out["status"],"UNALIGNED_ACTUAL_ENTRY_EXIT_DATES")
        self.assertIsNone(out["model_net_excess"])
        self.assertFalse(out["independently_verified_investment_alpha"])

    def test_only_comparable_whole_cohort_computes_cost_adjusted_research_figures(self):
        v=dict(row(),seen_entries=50,seen_exits=50,matured=50,
               aligned_entries=1,aligned_exits=1,
               model_mature_selection=10,baseline_mature_selection=10,
               first_entry="2026-11-23",last_entry="2026-11-23",
               first_exit="2026-11-30",last_exit="2026-11-30",
               universe_gross="0.01",model_gross="0.03",baseline_gross="0.025")
        out=assess_frozen_outcomes(v,cutoff=date(2026,11,30))
        self.assertEqual(out["status"],"FULL_COHORT_MATURE_RESEARCH_ONLY")
        self.assertAlmostEqual(out["model_net_return"],0.027)
        self.assertAlmostEqual(out["model_net_excess"],0.017)
        self.assertAlmostEqual(out["baseline_net_excess"],0.012)
        self.assertEqual(out["round_trip_cost_bps_assumed"],30)
        self.assertFalse(out["corporate_action_adjustment_vintage_verified"])
        self.assertFalse(out["live_trading_approved"])

    def test_impossible_maturity_or_tampered_roster_rank_cannot_pass(self):
        for change in (
            {"actual_members":49},
            {"selected_count":11},
            {"model_selection":9},
            {"baseline_selection":9},
            {"matured":51},
            {"seen_entries":51},
            {"universe_count":0},
            {"model_sha256":"bad"},
        ):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    assess_frozen_outcomes({**row(),**change},
                                           cutoff=date(2026,11,20))
        with self.assertRaises(ValueError):
            assess_frozen_outcomes(row(),cutoff=date(2026,11,19))

    def test_real_sql_uses_original_raw_trade_day_offsets_not_future_rank_reselection(self):
        self.assertIn("ORDER BY trade_date LIMIT 6",FROZEN_LABEL_SQL)
        self.assertIn("ROW_NUMBER() OVER(ORDER BY p.trade_date)",FROZEN_LABEL_SQL)
        self.assertIn("jsonb_array_elements(f.roster)",FROZEN_LABEL_SQL)
        self.assertIn("frozen_at <",FROZEN_LABEL_SQL)
        self.assertIn("AT TIME ZONE 'Asia/Taipei'",FROZEN_LABEL_SQL)
        self.assertIn("gross_return",FROZEN_LABEL_SQL)
        self.assertNotIn("DO UPDATE",FROZEN_LABEL_SQL)
        self.assertNotIn("DELETE FROM",FROZEN_LABEL_SQL)
        source=(Path(__file__).resolve().parents[1]/
                "scripts/audit_frozen_forward_outcomes.py").read_text()
        self.assertIn("default_transaction_read_only=on",source)
        self.assertIn("REPEATABLE READ READ ONLY",source)
        self.assertIn("statement_timeout='30000ms'",source)
        self.assertNotIn("LINE_CHANNEL",source)


if __name__=="__main__":
    unittest.main()
