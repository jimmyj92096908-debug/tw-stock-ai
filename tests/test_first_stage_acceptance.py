"""Phase one scope: real research report accepted, never LINE or trading."""
import json
from pathlib import Path
import tempfile
import unittest

from scripts import first_stage_acceptance as stage
from scripts import render_first_stage_report as research
from tests.test_first_stage_report import fixture


def sample():
    return research.build_summary(
        *fixture(), generated_at="2026-11-20T11:45:00+00:00"
    )


class FirstStageAcceptanceTests(unittest.TestCase):
    def test_accepted_research_is_not_a_trade_or_line_release(self):
        r=stage.accept(sample())
        self.assertEqual(r["result"],"accepted")
        self.assertTrue(r["core_research_mvp_accepted"])
        self.assertTrue(r["research_only"])
        self.assertEqual(r["market_date"],"2026-11-19")
        self.assertEqual(r["stocks_with_prices"],1968)
        self.assertEqual(r["indicator_pending"],1044)
        self.assertEqual(r["indicator_complete"],62)
        self.assertEqual(r["scored_stocks"],164)
        self.assertEqual(r["research_eligible_universe"],153)
        self.assertFalse(r["line_webhook_cutover_verified"])
        self.assertFalse(r["live_trading_approved"])
        self.assertEqual(r["other_scope"]["unattended_cron_run"],
                         "requires_independent_github_schedule_run_evidence")
        text=stage.markdown(r)
        self.assertIn("驗收通過",text)
        self.assertIn("尚待另外驗證",text)
        self.assertIn("交易",text)

    def test_real_historical_model_not_mistaken_for_profitable_system(self):
        r=stage.accept(sample())
        self.assertLess(r["model_holdout_mean_net_excess"],0)
        self.assertFalse(r["holdout_research_gate_passed"])
        self.assertIn("樣本外平均淨超額",stage.markdown(r))

    def test_bad_quality_or_stale_score_blocks_acceptance(self):
        for field,value in (("quality_violations",1),("score_date","2026-11-18"),
                            ("market_date","junk"),("research_eligible_universe",0)):
            report=sample()
            report[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                stage.accept(report)

    def test_cannot_label_trading_or_line_enabled_as_accepted(self):
        for field,value in (
            ("live_trading_approved",True),
            ("holdout_research_gate_passed",True),
            ("line_stock_gateway_enabled",True),
            ("abstain",False),
            ("research_report_available",False),
        ):
            report=sample()
            report[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                stage.accept(report)

    def test_zero_or_inconsistent_market_counts_block_acceptance(self):
        for field,value in (
            ("candidate_stocks",0),
            ("stocks_with_prices",0),
            ("technical_stocks",0),
            ("smc_stocks",0),
            ("scored_stocks",0),
            ("indicator_complete",0),
            ("indicator_pending",3),
            ("indicator_unstarted",10000),
        ):
            report=sample()
            report[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                stage.accept(report)

    def test_invalid_market_breakdown_or_missing_ranking_blocks_acceptance(self):
        report=sample()
        report["indicator_backlog_by_market"][0]["pending"]=3
        with self.assertRaisesRegex(ValueError,"market coverage"):
            stage.accept(report)
        report=sample()
        report["indicator_backlog_by_market"].pop()
        with self.assertRaisesRegex(ValueError,"exact TWSE"):
            stage.accept(report)
        report=sample()
        report["research_ranked"]=[]
        with self.assertRaisesRegex(ValueError,"ranking"):
            stage.accept(report)

    def test_rejects_missing_or_invalid_holdout_evidence(self):
        for name,value in (
            ("holdout_dates",0),
            ("holdout_mean_net_excess","not-a-rate"),
            ("holdout_mean_net_excess",float("nan")),
        ):
            report=sample()
            report[name]=value
            with self.subTest(name=name),self.assertRaises(ValueError):
                stage.accept(report)

    def test_generated_files_are_safe_summary_not_private_or_stock_payload(self):
        accepted=stage.accept(sample())
        payload=json.dumps(accepted,ensure_ascii=False)
        self.assertNotIn("DATABASE_URL",payload)
        self.assertNotIn("LINE_CHANNEL_SECRET",payload)
        self.assertNotIn("三洋電",payload)
        self.assertNotIn("1614",payload)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"first-stage-acceptance.json"
            path.write_text(json.dumps(accepted),encoding="utf-8")
            again=json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(again["core_research_mvp_accepted"])


if __name__=="__main__":
    unittest.main()
