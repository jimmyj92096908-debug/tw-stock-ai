"""Tests for bounded, non-overwriting 100% eligible research catch-up."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from scripts import eligible_100_catchup as task


def snap(matched=994,both=994,scored=994,*,eligible=1107,price_rows=197207):
    return {
        "stock_master_total":1991,"raw_price_rows":price_rows,
        "latest_price_date":"2026-11-20",
        "database_bytes":230000000,
        "eligible":eligible,
        "technical_current":both,"smc_current":both,
        "both_current":both,
        "scored_current":scored,
        "matched_current":matched,
    }


class Eligible100Tests(unittest.TestCase):
    def test_correct_subset_is_not_1991_and_query_requires_same_stock_date(self):
        q=task.SNAPSHOT_SQL.lower()
        self.assertIn("valid_days>=60",q)
        self.assertIn("interval '7 days'",q)
        self.assertIn("stock_id<>'1808'",q)
        self.assertIn("technical and smc and scored",q)
        self.assertIn("trade_date=e.last_valid",q)
        self.assertIn("as_of_date=e.last_valid",q)
        self.assertNotIn("insert into",q)
        self.assertNotIn("update ",q)
        self.assertEqual(task.MAX_PER_MARKET,20)
        self.assertLessEqual(task.MAX_ROUNDS,9)

    def test_dry_run_never_writes_and_does_not_claim_100pct_master(self):
        with patch.object(task,"snapshot",return_value=snap()),\
             patch.object(task,"indicator_run") as indicators,\
             patch.object(task,"calculate_all") as score:
            result=task.execute("fake",apply=False,max_rounds=9)
        indicators.assert_not_called()
        score.assert_not_called()
        self.assertFalse(result["eligible_complete"])
        self.assertTrue(result["not_all_1991_master_stocks"])
        self.assertFalse(result["paid_upgrade_requested"])

    def test_write_requires_both_explicit_gates(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaisesRegex(ValueError,"Both"):
                task.execute("fake",apply=True,max_rounds=9)
        with patch.dict(os.environ,{"STOCK_ELIGIBLE_100_COVERAGE_WRITE_ENABLED":"yes"}):
            with self.assertRaises(ValueError):
                task.execute("fake",apply=True,max_rounds=9)
        with self.assertRaises(ValueError):
            task.execute("fake",apply=True,max_rounds=10)

    def test_success_after_two_indicator_rounds_and_followon_composites(self):
        series=[snap(),snap(both=1050,matched=994),
                snap(both=1107,matched=994),
                snap(matched=1107,both=1107,scored=1107)]
        items=[{"status":"verified"}]
        with patch.dict(os.environ,{"STOCK_ELIGIBLE_100_COVERAGE_WRITE_ENABLED":"yes",
                                     "STOCK_INDICATOR_CATCHUP_WRITE_ENABLED":"yes"}),\
             patch.object(task,"snapshot",side_effect=series),\
             patch.object(task,"indicator_run",return_value=items) as ind,\
             patch.object(task,"calculate_all",return_value=103) as calc:
            out=task.execute("fake",apply=True,max_rounds=3)
        self.assertTrue(out["eligible_complete"])
        self.assertEqual(len(out["rounds"]),2)
        self.assertTrue(out["score_rebuild_attempted"])
        self.assertEqual(ind.call_count,2)
        calc.assert_called_once_with("fake")
        self.assertFalse(out["raw_prices_modified"])

    def test_indicator_failure_no_progress_and_market_change_abort(self):
        outcomes=[
            (snap(),snap(both=994,matched=994),[{"status":"verified"}],"did not increase"),
            (snap(),snap(both=1020,matched=994),[{"status":"failed"}],"failed"),
            (snap(),snap(both=1020,matched=994,price_rows=197208),
             [{"status":"verified"}],"changed"),
        ]
        for before,after,items,phrase in outcomes:
            with self.subTest(phrase=phrase),\
                 patch.dict(os.environ,{"STOCK_ELIGIBLE_100_COVERAGE_WRITE_ENABLED":"yes",
                                        "STOCK_INDICATOR_CATCHUP_WRITE_ENABLED":"yes"}),\
                 patch.object(task,"snapshot",side_effect=[before,after]),\
                 patch.object(task,"indicator_run",return_value=items),\
                 patch.object(task,"calculate_all") as calc:
                with self.assertRaisesRegex(RuntimeError,phrase):
                    task.execute("fake",apply=True,max_rounds=1)
                calc.assert_not_called()

    def test_rebuild_not_skipped_when_indicators_done_but_scores_missing(self):
        items=[snap(matched=994,both=1107,scored=994),
               snap(matched=1107,both=1107,scored=1107)]
        with patch.dict(os.environ,{"STOCK_ELIGIBLE_100_COVERAGE_WRITE_ENABLED":"yes",
                                     "STOCK_INDICATOR_CATCHUP_WRITE_ENABLED":"yes"}),\
             patch.object(task,"snapshot",side_effect=items),\
             patch.object(task,"indicator_run") as ind,\
             patch.object(task,"calculate_all",return_value=1107) as calc:
            out=task.execute("fake",apply=True,max_rounds=1)
        self.assertTrue(out["eligible_complete"])
        ind.assert_not_called()
        calc.assert_called_once_with("fake")

    def test_no_false_success_when_scores_remain_incomplete(self):
        items=[snap(matched=994,both=1107,scored=994),
               snap(matched=994,both=1107,scored=994)]
        with patch.dict(os.environ,{"STOCK_ELIGIBLE_100_COVERAGE_WRITE_ENABLED":"yes",
                                     "STOCK_INDICATOR_CATCHUP_WRITE_ENABLED":"yes"}),\
             patch.object(task,"snapshot",side_effect=items),\
             patch.object(task,"calculate_all",return_value=0):
            with self.assertRaisesRegex(RuntimeError,"not verified"):
                task.execute("fake",apply=True,max_rounds=1)

    def test_storage_ceiling_and_count_regression_fail_closed(self):
        with self.assertRaisesRegex(RuntimeError,"regressed"):
            task.unchanged_market_data(snap(),snap(both=993))
        with self.assertRaisesRegex(RuntimeError,"ceiling"):
            task.unchanged_market_data(snap(),{**snap(),"database_bytes":800000000})
        with self.assertRaisesRegex(RuntimeError,"changed"):
            task.unchanged_market_data(snap(),snap(eligible=1106))
        with patch.object(task,"snapshot",return_value=snap(matched=994,both=994)):
            with patch.dict(os.environ,{"STOCK_ELIGIBLE_100_COVERAGE_WRITE_ENABLED":"yes",
                                         "STOCK_INDICATOR_CATCHUP_WRITE_ENABLED":"yes"}):
                with patch.object(task,"indicator_run",return_value=[{"status":"verified"}]):
                    with self.assertRaisesRegex(StopIteration,""):
                        task.execute("fake",apply=True,max_rounds=1)


if __name__=="__main__":
    unittest.main()
