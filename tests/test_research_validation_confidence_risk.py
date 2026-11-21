"""Offline confidence, risk and time-isolated walk-forward regression tests."""
from __future__ import annotations

from datetime import date, timedelta
import math
import unittest

from src.research_confidence import data_quality_assessment
from src.research_risk import concentration, market_regime, nonoverlapping_path
from src.research_walkforward import walk_forward_diagnostics
from scripts.offline_research_diagnostics import audit_local


def current_data():
    stock = {
        "price_date": "2026-11-20",
        "technical_date": "2026-11-20",
        "composite_date": "2026-11-20",
        "composite_chip_component": None,
        "independent_chip_is_current": False,
        "independent_chip_coverage": None,
    }
    raw = {"latest_smc_date": "2026-11-20",
           "valid_price_days": 240, "latest_composite_coverage": .60}
    return stock, raw


def history_rows(count=100):
    rows = []
    first = date(2026, 8, 1)
    for i in range(count):
        day = first + timedelta(days=i)
        for j in range(10):
            change = (5-j)/100
            rows.append({
                "market":"twse","stock_id":str(1300+j),
                "as_of_date":day.isoformat(),
                "total_score":95-5*j, "technical_score":90-4*j,
                "smc_score":80-3*j,"short_term_score":85-4*j,
                "swing_score":75-2*j,"long_term_score":None,
                "coverage_weight": .60, "adjusted_close":100.0,
                "entry_close":100.0, "exit_close":100*(1+change),
                "exit_date":(day + timedelta(days=5)).isoformat(),
            })
    return rows


class ConfidenceTests(unittest.TestCase):
    def test_current_but_incomplete_chip_is_not_misrepresented(self):
        stock, raw = current_data()
        out = data_quality_assessment(stock,raw)
        self.assertEqual(out["status"],"CURRENT_EVIDENCE_PARTIAL")
        self.assertEqual(out["data_quality_index"],67.0)
        self.assertFalse(out["is_probability_of_profit"])
        self.assertFalse(out["trading_approved"])
        self.assertIn("CHIP_NOT_IN_CURRENT_COMPOSITE",out["reasons"])

    def test_future_chip_is_not_retroactively_attached(self):
        stock, raw = current_data()
        stock["independent_chip_is_current"] = True
        stock["independent_chip_coverage"] = .90
        out = data_quality_assessment(stock,raw)
        self.assertFalse(out["composite_contains_chip"])
        self.assertEqual(out["data_quality_index"],67.0)

    def test_verified_chip_and_more_factor_coverage_improve_index(self):
        stock, raw = current_data()
        stock.update(composite_chip_component=70.0,
                     independent_chip_is_current=True,
                     independent_chip_coverage=.8)
        raw["latest_composite_coverage"]=1.0
        out=data_quality_assessment(stock,raw)
        self.assertEqual(out["data_quality_index"],97.0)
        self.assertNotIn("CHIP_NOT_IN_CURRENT_COMPOSITE",out["reasons"])

    def test_stale_or_missing_history_never_produces_numeric_index(self):
        s, r = current_data()
        cases = [
            ({**s,"composite_date":"2026-11-19"},r),
            ({**s,"technical_date":"2026-11-19"},r),
            (s,{**r,"latest_smc_date":"2026-11-19"}),
            (s,{**r,"latest_composite_coverage":None}),
            (s,{**r,"latest_composite_coverage":float("nan")}),
            (s,{**r,"latest_composite_coverage":1.5}),
            (s,{**r,"valid_price_days":None}),
            (s,{**r,"valid_price_days":59}),
        ]
        for stock, raw in cases:
            with self.subTest(stock=stock,raw=str(raw)):
                out=data_quality_assessment(stock,raw)
                self.assertIsNone(out["data_quality_index"])
                self.assertEqual(out["status"],"INSUFFICIENT_CURRENT_EVIDENCE")


class RiskTests(unittest.TestCase):
    def test_nonoverlap_compounded_path_drawdown_and_benchmark(self):
        outcomes = [
            {"signal_date":"2026-11-01","exit_date":"2026-11-03",
             "net_return":.10,"excess_vs_universe":.04,
             "baseline_net_return":.08},
            {"signal_date":"2026-11-04","exit_date":"2026-11-07",
             "net_return":-.20,"excess_vs_universe":-.12,
             "baseline_net_return":-.10},
            {"signal_date":"2026-11-08","exit_date":"2026-11-12",
             "net_return":.10,"excess_vs_universe":.08,
             "baseline_net_return":.06},
        ]
        out=nonoverlapping_path(outcomes)
        self.assertAlmostEqual(out["maximum_drawdown"],.20)
        self.assertAlmostEqual(out["compounded_net_return"],-.032)
        self.assertFalse(out["external_benchmark_complete"])
        self.assertIsNone(out["external_benchmark_mean_net_return"])
        self.assertFalse(out["trading_approved"])
        outcomes[0]["benchmark_net_return"]=.03
        self.assertFalse(nonoverlapping_path(outcomes)["external_benchmark_complete"])
        outcomes[1]["benchmark_net_return"]=-.02
        outcomes[2]["benchmark_net_return"]=.01
        self.assertTrue(nonoverlapping_path(outcomes)["external_benchmark_complete"])

    def test_same_day_overlap_unsorted_and_bad_returns_are_rejected(self):
        event={"signal_date":"2026-11-01","exit_date":"2026-11-06",
               "net_return":.01,"excess_vs_universe":.01,
               "baseline_net_return":.00}
        with self.assertRaisesRegex(ValueError,"Overlapping"):
            nonoverlapping_path([event,{**event,"signal_date":"2026-11-06",
                                           "exit_date":"2026-11-10"}])
        with self.assertRaisesRegex(ValueError,"finite"):
            nonoverlapping_path([{**event,"net_return":float("nan")}])
        with self.assertRaisesRegex(ValueError,"below -100"):
            nonoverlapping_path([{**event,"net_return":-1.2}])

    def test_heuristic_regime_uses_only_past_verified_index_sessions(self):
        start=date(2026,1,1)
        series=[{"date":(start+timedelta(days=i)).isoformat(),"close":100+i} for i in range(81)]
        cutoff=series[79]["date"]
        result=market_regime(series,as_of_date=cutoff)
        self.assertEqual(result["regime"],"UPTREND")
        series[80]["close"]=1
        self.assertEqual(market_regime(series,as_of_date=cutoff),result)
        self.assertTrue(result["verified_index_provenance_required"])
        self.assertEqual(market_regime(series[:30],as_of_date=cutoff)["regime"],
                         "UNKNOWN_HISTORY")
        with self.assertRaises(ValueError):
            market_regime(series+series[-1:],as_of_date=cutoff)

    def test_concentration_requires_actual_normalized_weights(self):
        self.assertFalse(concentration([])["known"])
        out=concentration([
            {"market":"twse","stock_id":"2330","weight":.6},
            {"market":"tpex","stock_id":"6488","weight":.4},
        ])
        self.assertEqual(out["herfindahl_index"],.52)
        self.assertEqual(out["effective_number_of_holdings"],1.9231)
        self.assertEqual(out["max_single_weight"],.6)
        with self.assertRaisesRegex(ValueError,"sum"):
            concentration([{"market":"twse","stock_id":"2330","weight":.6}])
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            concentration([{"market":"twse","stock_id":"2330","weight":.5},
                           {"market":"twse","stock_id":"2330","weight":.5}])


class WalkForwardTests(unittest.TestCase):
    START=(date(2026,8,1)+timedelta(days=31)).isoformat()

    def test_folds_require_mature_labels_and_dont_overlap(self):
        out=walk_forward_diagnostics(
            history_rows(),first_test_date=self.START,fold_signals=2,max_folds=3)
        self.assertEqual(len(out["folds"]),3)
        self.assertEqual(out["nonoverlapping_risk"]["observations"],6)
        self.assertFalse(out["pristine_future_holdout_proven"])
        self.assertFalse(out["orders_enabled"])
        self.assertFalse(out["line_trade_signals_enabled"])
        self.assertEqual(out["benchmark_status"],"NOT_PROVIDED_OR_INCOMPLETE")
        windows=out["tested_windows"]
        for prev,next_ in zip(windows,windows[1:]):
            self.assertLess(prev["exit_date"],next_["signal_date"])
        for fold in out["folds"]:
            self.assertTrue(fold["train_exit_before_first_test"])
            self.assertGreaterEqual(fold["train_dates"],20)
            self.assertLess(fold["train_through"],fold["first_test_date"])

    def test_fold_training_not_affected_by_future_labels(self):
        original=history_rows()
        changed=history_rows()
        for row in changed:
            if row["as_of_date"]>=self.START:
                row["exit_close"] = row["entry_close"] * 1.25
        a=walk_forward_diagnostics(original,first_test_date=self.START,max_folds=1)
        b=walk_forward_diagnostics(changed,first_test_date=self.START,max_folds=1)
        self.assertEqual(a["folds"][0]["train_fingerprint"],
                         b["folds"][0]["train_fingerprint"])
        self.assertNotEqual(a["tested_windows"],b["tested_windows"])

    def test_missing_future_label_excludes_entire_date_cohort(self):
        rows=history_rows()
        for row in rows:
            if row["as_of_date"]==self.START and row["stock_id"]=="1300":
                row["exit_close"]=None
        out=walk_forward_diagnostics(rows,first_test_date=self.START,max_folds=1,
                                     fold_signals=1)
        self.assertNotEqual(out["tested_windows"][0]["signal_date"],self.START)
        self.assertEqual(out["folds"][0]["excluded"]["skipped_dates"]["incomplete_forward"],1)

    def test_only_verified_explicit_benchmark_can_be_compared(self):
        rows=history_rows()
        dates={(date(2026,8,1)+timedelta(days=i)).isoformat():0.0 for i in range(100)}
        out=walk_forward_diagnostics(rows,first_test_date=self.START,max_folds=2,
                                     verified_benchmark_returns=dates)
        self.assertEqual(out["benchmark_status"],"ALIGNED_EXTERNALLY_SUPPLIED")
        self.assertEqual(out["nonoverlapping_risk"]["external_benchmark_mean_net_return"],0.0)

    def test_short_data_and_invalid_parameters_fail_closed(self):
        out=walk_forward_diagnostics(history_rows(10),first_test_date=self.START)
        self.assertEqual(out["folds"],[])
        self.assertEqual(out["research_status"],
                         "INSUFFICIENT_MATURE_TRAINING_AND_TEST_HISTORY")
        with self.assertRaises(ValueError):
            walk_forward_diagnostics(history_rows(),first_test_date=self.START,
                                     fold_signals=0)
        with self.assertRaises(ValueError):
            walk_forward_diagnostics(history_rows(),first_test_date=self.START,
                                     max_folds=25)

    def test_offline_report_has_no_database_or_orders(self):
        out=audit_local(history_rows(),first_test_date=self.START,max_folds=1)
        self.assertEqual(out["data_mode"],"offline_user_supplied_historical_evidence")
        self.assertFalse(out["production_database_modified"])
        self.assertFalse(out["trading_approved"])
        self.assertEqual(out["market_regime"]["regime"],"UNAVAILABLE")
        self.assertFalse(out["portfolio_concentration"]["known"])


if __name__=="__main__":
    unittest.main()
