"""Proof: TWSE 240-session research recalculation never modifies raw prices."""
import os
from unittest import TestCase
from unittest.mock import patch

from scripts import twse_240_research_catchup as task


def snap(*,source_days=1100,eligible=500,indicators=480,scores=300,
         missing_weekdays=0,
         rows=270000,db_bytes=400_000_000):
    return {
        "raw_twse_rows":rows,"verified_source_days":source_days,
        "database_bytes":db_bytes,"eligible":eligible,
        "current_indicators":indicators,"current_scores":scores,
        "missing_five_year_weekdays":missing_weekdays,
    }


GATES={
    "STOCK_TWSE_240_RESEARCH_WRITE_ENABLED":"yes",
    "STOCK_INDICATOR_CATCHUP_WRITE_ENABLED":"yes",
    "STOCK_TWSE_240_SCORE_RECALC_ENABLED":"yes",
}


class TWSE240ResearchAcceptanceTests(TestCase):
    def test_preview_and_missing_write_gates_cannot_modify_data(self):
        with (
            patch.object(task,"capture",return_value=snap()),
            patch.object(task,"indicator_run") as ind,
            patch.object(task,"calculate_all") as scores,
        ):
            report=task.execute("fake",apply=False)
        self.assertFalse(report["completed"])
        self.assertFalse(report["raw_prices_modified"])
        self.assertFalse(report["line_messages_sent"])
        ind.assert_not_called()
        scores.assert_not_called()
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaisesRegex(ValueError,"write gates"):
                task.execute("fake",apply=True)
        for n in (-1,61,500):
            with self.assertRaisesRegex(ValueError,"indicator"):
                task.execute("fake",max_rounds=n)
        for n in (-1,121,500):
            with self.assertRaisesRegex(ValueError,"score"):
                task.execute("fake",max_score_batches=n)

    def test_real_240_day_eligibility_gate_is_separate_from_60_day_scoring(self):
        for low in (snap(source_days=239),snap(eligible=499)):
            with (
                patch.dict(os.environ,GATES),
                patch.object(task,"capture",return_value=low),
                patch.object(task,"indicator_run") as ind,
                patch.object(task,"calculate_all") as score,
            ):
                with self.assertRaisesRegex(RuntimeError,"240-day cohort"):
                    task.execute("fake",apply=True)
                ind.assert_not_called()
                score.assert_not_called()
        self.assertIn("valid_days>=240",task.STATE_SQL)
        self.assertIn("missing_five_year_weekdays",task.STATE_SQL)
        self.assertIn("twse_history_day_progress",task.STATE_SQL)
        for source in (
            snap(source_days=999),
            snap(missing_weekdays=1),
            snap(db_bytes=650_000_000),
        ):
            with (
                patch.dict(os.environ,GATES),
                patch.object(task,"capture",return_value=source),
                patch.object(task,"indicator_run") as indicators,
                patch.object(task,"calculate_all") as scores,
            ):
                with self.assertRaisesRegex(RuntimeError,"five-year source backlog"):
                    task.execute("fake",apply=True)
                indicators.assert_not_called()
                scores.assert_not_called()
        self.assertIn("INNER JOIN official_current_listed listed",task.STATE_SQL)
        self.assertIn("INNER JOIN official_current_listed listed",task.SCORE_PAGE_SQL)
        self.assertIn("INTERVAL '14 days'",task.STATE_SQL)
        self.assertIn("history_days>=240",task.SCORE_PAGE_SQL)
        self.assertNotIn("INSERT INTO public.daily_prices",task.STATE_SQL.upper())
        self.assertNotIn("UPDATE public.daily_prices",task.STATE_SQL.upper())

    def test_successful_long_horizon_cohort_rebuilds_all_score_rows(self):
        states=[
            snap(),snap(indicators=500),
            *[snap(indicators=500,scores=300+4*(i+1)) for i in range(50)]
        ]
        def page(_url,offset):
            if offset>=500:
                return []
            return [("twse",str(1000+offset+j)) for j in range(10)]
        with (
            patch.dict(os.environ,GATES),
            patch.object(task,"capture",side_effect=states),
            patch.object(task,"indicator_run",return_value=[
                {"status":"verified"} for _ in range(20)
            ]) as ind,
            patch.object(task,"score_page",side_effect=page) as pages,
            patch.object(task,"calculate_all",return_value=10) as scores,
        ):
            report=task.execute("fake",apply=True,max_rounds=2,
                                max_score_batches=60)
        self.assertTrue(report["completed"])
        self.assertEqual(report["latest"]["current_indicators"],500)
        self.assertEqual(report["latest"]["current_scores"],500)
        self.assertEqual(len(report["score_batches"]),50)
        ind.assert_called_once_with("fake",apply=True,per_market=20,
                                    markets=("twse",),min_verified_price_days=240)
        self.assertEqual(scores.call_count,50)
        self.assertTrue(all(call.kwargs["missing_only"] is False
                            for call in scores.call_args_list))
        self.assertEqual(pages.call_count,51)

    def test_raw_price_mutation_or_cohort_change_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError,"raw market history changed"):
            task.assert_no_raw_price_change(snap(),snap(rows=270001))
        with self.assertRaisesRegex(RuntimeError,"cohort changed"):
            task.assert_no_raw_price_change(snap(),snap(eligible=501))
        with self.assertRaisesRegex(RuntimeError,"regressed"):
            task.assert_no_raw_price_change(snap(),snap(indicators=479))
        with (
            patch.dict(os.environ,GATES),
            patch.object(task,"capture",side_effect=[snap(),snap()]),
            patch.object(task,"indicator_run",return_value=[{"status":"verified"}]),
            patch.object(task,"calculate_all") as scores,
        ):
            with self.assertRaisesRegex(RuntimeError,"no verified progress"):
                task.execute("fake",apply=True,max_rounds=1)
            scores.assert_not_called()

    def test_scoped_score_pages_and_amount_limits(self):
        for invalid in (-1,1201,True):
            with self.assertRaisesRegex(ValueError,"score offset"):
                task.score_page("fake",invalid)
        self.assertEqual(task.MAX_ROUNDS,60)
        self.assertEqual(task.MAX_SCORE_BATCHES,120)
        self.assertEqual(task.MIN_VERIFIED_DAYS,240)
