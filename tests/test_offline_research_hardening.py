"""Zero-network, zero-database acceptance of offline research hardening."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from src.research_coverage_acceptance import (
    acceptance, diagnose_missing, validate_snapshot, INTERSECTION_SQL
)
from src.research_execution_costs import scenario, stress_test
from src.research_fundamental_pit import asof_fundamentals
from src.research_anomaly_monitor import score_drift
from scripts import offline_research_readiness as cli


def snap(**kwargs):
    out={"universe":1991,"priced":1982,"price_rows":100000,
         "latest_price_date":"2026-11-20",
         "technical_current":120,"smc_current":120,
         "both_current":100,"scored_current":82}
    out.update(kwargs)
    return out


def fundamental(*,metric="revenue_yoy_pct",period="2026-09-30",
                pub="2026-11-18T12:00:00+08:00",
                rec="2026-11-18T12:01:00+08:00",
                value=20,stock="2330"):
    return {"market":"twse","stock_id":stock,"metric":metric,
            "period_end":period,"published_at":pub,
            "recorded_at":rec,"value":value,"source":"provided_sample"}


class CoverageTests(unittest.TestCase):
    def test_count_gates_do_not_pretend_separate_aggregates_are_identical_cohort(self):
        before=snap()
        after=snap(technical_current=1020,smc_current=1010,both_current=1000,
                   scored_current=999)
        a=acceptance(before,after)
        self.assertEqual(a["status"],"COHORT_INTERSECTION_NOT_VERIFIED")
        self.assertFalse(a["research_coverage_passed"])
        self.assertEqual(a["target_stocks"],996)
        b=acceptance(before,{**after,"scored_and_both_current":950})
        self.assertEqual(b["status"],"MATCHED_STOCK_COVERAGE_NOT_READY")
        c=acceptance(before,{**after,"scored_and_both_current":996})
        self.assertTrue(c["research_coverage_passed"])
        self.assertFalse(c["investment_alpha_validated"])
        self.assertFalse(c["live_trading_approved"])
        self.assertFalse(c["production_database_modified"])

    def test_scores_missing_blocks_composite_gate_and_no_regression(self):
        a=acceptance(snap(),snap(technical_current=1100,smc_current=1050,
                                 both_current=1000,scored_current=82))
        self.assertEqual(a["status"],"SCORE_REBUILD_NOT_READY")
        b=acceptance(snap(),snap(technical_current=300,smc_current=250,
                                 both_current=200,scored_current=82))
        self.assertEqual(b["status"],"INDICATOR_COVERAGE_NOT_READY")
        with self.assertRaisesRegex(ValueError,"regressed"):
            acceptance(snap(),snap(both_current=99))
        with self.assertRaisesRegex(ValueError,"changed"):
            acceptance(snap(),snap(price_rows=100001))
        with self.assertRaisesRegex(ValueError,"changed"):
            acceptance(snap(),snap(latest_price_date="2026-11-21"))

    def test_corrupt_and_inconsistent_snapshots_fail_closed(self):
        cases=[
            snap(universe=True),
            snap(priced=2000),
            snap(technical_current=5),
            snap(both_current=121),
            snap(scored_current=2100),
            snap(latest_price_date=None),
            snap(technical_current=-1),
            snap(scored_and_both_current=83),
        ]
        for example in cases:
            with self.subTest(example=str(example)):
                with self.assertRaises(ValueError):
                    validate_snapshot(example)
        self.assertIn("public.daily_composite_scores",INTERSECTION_SQL)
        self.assertIn("public.daily_smc",INTERSECTION_SQL)
        self.assertNotIn("INSERT INTO",INTERSECTION_SQL)

    def test_missing_stock_reason_specificity_and_duplicates(self):
        rows=[
            {"market":"twse","stock_id":"2330","valid_price_days":180,
             "current_price":True,"technical_current":True,
             "smc_current":True,"score_current":False},
            {"market":"tpex","stock_id":"6488","valid_price_days":49,
             "current_price":True,"technical_current":False,
             "smc_current":False,"score_current":False},
            {"market":"twse","stock_id":"1301","valid_price_days":240,
             "current_price":False,"technical_current":False,
             "smc_current":False,"score_current":False},
        ]
        result=diagnose_missing(rows)
        self.assertEqual(result["incomplete_stocks"],3)
        self.assertEqual(result["reasons"]["COMPOSITE_MISSING_ON_LAST_VALID_CLOSE"],1)
        self.assertEqual(result["reasons"]["LESS_THAN_60_VALID_SESSIONS"],1)
        self.assertEqual(result["reasons"]["NO_LATEST_VALID_PRICE"],1)
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            diagnose_missing(rows+[rows[0]])
        with self.assertRaisesRegex(ValueError,"verified"):
            diagnose_missing([{**rows[0],"score_current":None}])
        with self.assertRaises(ValueError):
            diagnose_missing([rows[0]]*2001)


class ExecutionCostTests(unittest.TestCase):
    def test_zero_costs_are_neutral_and_slippage_reduces_return(self):
        neutral=scenario(.10,entry_fee_bps=0,exit_fee_bps=0,
                         sell_tax_bps=0,entry_slippage_bps=0,
                         exit_slippage_bps=0)
        self.assertAlmostEqual(neutral["net_return"],.10)
        self.assertEqual(neutral["liquidity_screen"],"UNKNOWN")
        stressed=stress_test(.10,fee_bps=14.25,sell_tax_bps=30,
                             slippage_bps_scenarios=[0,10,30,60])
        self.assertEqual(len(stressed["cases"]),4)
        self.assertTrue(stressed["net_return_monotone_nonincreasing"])
        self.assertLess(stressed["worst_assumed_net_return"],.10)
        self.assertFalse(stressed["orders_enabled"])
        self.assertFalse(stressed["sufficient_real_microstructure_data_for_executability"])

    def test_unknown_turnover_never_claims_pass_and_bounded_volume(self):
        kwargs=dict(entry_fee_bps=10,exit_fee_bps=10,sell_tax_bps=30,
                    entry_slippage_bps=15,exit_slippage_bps=15)
        a=scenario(.02,**kwargs)
        self.assertEqual(a["liquidity_screen"],"UNKNOWN")
        b=scenario(.02,**kwargs,intended_notional_ntd=1e6,
                   verified_daily_turnover_ntd=1e7)
        self.assertEqual(b["liquidity_screen"],"EXCEEDS_ASSUMED_LIMIT")
        c=scenario(.02,**kwargs,intended_notional_ntd=1e5,
                   verified_daily_turnover_ntd=1e7)
        self.assertEqual(c["liquidity_screen"],"PASS_ASSUMED_LIMIT")
        self.assertFalse(c["executable_fill_verified"])

    def test_costs_require_explicit_assumptions_and_reject_invalid_values(self):
        base=dict(entry_fee_bps=10,exit_fee_bps=10,
                  sell_tax_bps=30,entry_slippage_bps=10,
                  exit_slippage_bps=10)
        for extra in ({"entry_fee_bps":-1},{"sell_tax_bps":float("nan")},
                      {"exit_fee_bps":True},{"entry_fee_bps":2500}):
            with self.subTest(case=str(extra)):
                with self.assertRaises(ValueError):
                    scenario(.1,**{**base,**extra})
        with self.assertRaises(TypeError):
            scenario(.1,entry_fee_bps=5)
        with self.assertRaises(ValueError):
            scenario(-1.2,**base)
        with self.assertRaises(ValueError):
            scenario(.02,**base,intended_notional_ntd=10000)
        with self.assertRaises(ValueError):
            stress_test(.02,fee_bps=10,sell_tax_bps=30,
                        slippage_bps_scenarios=[30,10])


class FundamentalTests(unittest.TestCase):
    SIGNAL="2026-11-20T13:30:00+08:00"

    def test_future_published_and_future_revision_are_not_fitted_to_old_signal(self):
        base=fundamental()
        next_day=fundamental(metric="roe_pct",pub="2026-11-21T09:00:00+08:00",
                             rec="2026-11-21T09:01:00+08:00")
        revision=fundamental(metric="eps_ttm_ntd",
                             rec="2026-11-21T09:00:00+08:00",
                             value=25)
        output=asof_fundamentals([base,next_day,revision],
                                 as_of_close=self.SIGNAL)
        self.assertEqual(output["fields"]["revenue_yoy_pct"]["value"],20)
        self.assertIsNone(output["fields"]["roe_pct"])
        self.assertIsNone(output["fields"]["eps_ttm_ntd"])
        self.assertEqual(output["excluded"]["future_publication"],1)
        self.assertEqual(output["excluded"]["future_revision"],1)
        self.assertAlmostEqual(output["metric_coverage"],1/6,places=5)
        self.assertFalse(output["all_fundamental_factors_applied_to_live_model"])
        self.assertFalse(output["orders_enabled"])

    def test_latest_known_record_not_latest_restatement(self):
        initial=fundamental(value=5)
        earlier=fundamental(metric="revenue_yoy_pct",period="2026-06-30",
                            pub="2026-08-01T08:00:00+08:00",
                            rec="2026-08-01T08:01:00+08:00",value=40)
        later_revision=fundamental(value=90,
            pub="2026-11-19T12:00:00+08:00",
            rec="2026-11-21T09:00:00+08:00")
        out=asof_fundamentals([later_revision,initial,earlier],
                              as_of_close=self.SIGNAL)
        self.assertEqual(out["fields"]["revenue_yoy_pct"]["value"],5)
        self.assertEqual(out["fields"]["revenue_yoy_pct"]["period_end"],"2026-09-30")

    def test_timezone_after_market_close_cannot_leak(self):
        item=fundamental(pub="2026-11-20T06:00:00+00:00",
                          rec="2026-11-20T06:01:00+00:00")
        out=asof_fundamentals([item],as_of_close=self.SIGNAL)
        self.assertIsNone(out["fields"]["revenue_yoy_pct"])
        with self.assertRaises(ValueError):
            asof_fundamentals([item],as_of_close="2026-11-20T13:30:00")
        with self.assertRaises(ValueError):
            asof_fundamentals([item],as_of_close="2026-11-20T14:30:00+08:00")

    def test_source_validation_and_duplicate_fail_closed(self):
        obs=fundamental()
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            asof_fundamentals([obs,obs],as_of_close=self.SIGNAL)
        with self.assertRaisesRegex(ValueError,"Disclosure"):
            asof_fundamentals([
                fundamental(pub="2026-09-29T13:00:00+08:00",
                            rec="2026-09-29T13:01:00+08:00")],
                as_of_close=self.SIGNAL)
        with self.assertRaisesRegex(ValueError,"numeric"):
            asof_fundamentals([{**obs,"value":float("inf")}],
                              as_of_close=self.SIGNAL)
        with self.assertRaisesRegex(ValueError,"Unknown"):
            asof_fundamentals([{**obs,"metric":"unknown"}],
                              as_of_close=self.SIGNAL)


class AnomalyTests(unittest.TestCase):
    @staticmethod
    def cohort(day, *,jump=0,n=40):
        return {"date":day,"scores":[
            {"market":"twse","stock_id":str(1300+i),
             "total_score":40+i/10+jump}
            for i in range(n)]}

    def test_same_stock_drift_vs_thin_unknown(self):
        a=self.cohort("2026-11-19")
        b=self.cohort("2026-11-20",jump=25)
        result=score_drift(a,b)
        self.assertEqual(result["status"],"SCORE_SHIFT_REVIEW")
        self.assertEqual(result["large_move_fraction"],1)
        self.assertFalse(result["performance_degradation_proven"])
        thin=score_drift(a,self.cohort("2026-11-20",n=5))
        self.assertEqual(thin["status"],"INSUFFICIENT_MATCHED_COHORT")
        self.assertIsNone(thin["warning"])
        with self.assertRaisesRegex(ValueError,"forward"):
            score_drift(b,a)

    def test_duplicate_or_fabricated_scores_are_rejected(self):
        a=self.cohort("2026-11-19")
        b=self.cohort("2026-11-20")
        b["scores"][0]["total_score"]=float("nan")
        with self.assertRaisesRegex(ValueError,"Invalid research score"):
            score_drift(a,b)
        b=self.cohort("2026-11-20")
        b["scores"].append(b["scores"][0])
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            score_drift(a,b)


class ReportTests(unittest.TestCase):
    def test_offline_report_never_claims_approval_even_if_coverage_met(self):
        output=cli.assemble_report(
            before=snap(),
            after=snap(technical_current=1000,smc_current=1000,
                       both_current=1000,scored_current=1000,
                       scored_and_both_current=997),
            evaluation={"holdout":{"model_mean_net_excess":-.02114523},
                        "holdout_research_gate_passed":False},
            cost_inputs={"gross_return":.05,"fee_bps":15,"sell_tax_bps":30},
            fundamentals=[fundamental()],
            as_of_close="2026-11-20T13:30:00+08:00",
            score_snapshots=[
                AnomalyTests.cohort("2026-11-19"),
                AnomalyTests.cohort("2026-11-20",jump=25)])
        self.assertTrue(output["coverage_acceptance"]["research_coverage_passed"])
        self.assertFalse(output["trade_recommendations_approved"])
        self.assertFalse(output["orders_enabled"])
        self.assertFalse(output["line_messages_sent"])
        self.assertFalse(output["payment_or_quota_upgrade_authorized"])
        self.assertEqual(output["score_shift"]["status"],"SCORE_SHIFT_REVIEW")
        md=cli.render_markdown(output)
        self.assertIn("-2.11%",md)
        self.assertIn("不代表投資模型已證明有效",md)

    def test_cli_creates_offline_json_and_markdown_without_neon_calls(self):
        with TemporaryDirectory() as folder:
            folder=Path(folder)
            before=folder/"before.json"
            after=folder/"after.json"
            out=folder/"report.json"
            md=folder/"report.md"
            before.write_text(json.dumps(snap()),encoding="utf-8")
            after.write_text(json.dumps(snap(technical_current=1000,
                                    smc_current=1000,both_current=1000,
                                    scored_current=82)),encoding="utf-8")
            with patch("sys.argv",["readiness","--before",str(before),
                              "--after",str(after),"--output-json",str(out),
                              "--output-md",str(md)]):
                cli.main()
            report=json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(report["coverage_acceptance"]["status"],
                             "SCORE_REBUILD_NOT_READY")
            self.assertTrue(md.exists())
            self.assertFalse(report["database_modified"])


if __name__=="__main__":
    unittest.main()
