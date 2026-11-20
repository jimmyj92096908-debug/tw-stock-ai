"""Independent first-stage user-facing report acceptance tests (offline)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import render_first_stage_report as dashboard


def fixture():
    audit = {
        "latest": {
            "latest_price_date": "2026-11-19",
            "latest_score_date": "2026-11-19",
        },
        "coverage": [{"market": "twse", "universe": 1093, "priced": 1090},
                     {"market": "tpex", "universe": 898, "priced": 878}],
        "quality": {
            "invalid_close": 0, "negative_volume": 0, "inverted_high_low": 0,
            "invalid_score": 0, "invalid_score_coverage": 0,
        },
        "analysis_readiness": {
            "technical_stocks": 164, "smc_stocks": 164, "scored_stocks": 164,
            "history_60d": 1108, "history_120d": 1093, "history_240d": 38,
        },
        "indicator_backlog": [
            {"market": "tpex", "eligible": 21, "pending": 0, "complete": 21, "unstarted": 0},
            {"market": "twse", "eligible": 1085, "pending": 1044, "complete": 41, "unstarted": 942},
        ],
    }
    ranking = {
        "model_version": "tw-factor-ridge-1", "date": "2026-11-19",
        "eligible_universe": 153, "abstain": True,
        "live_trading_approved": False,
        "stocks": [
            {"rank": 1, "market": "twse", "stock_id": "1614",
             "name": "三洋電", "relative_model_score": 0.01,
             "raw_composite_score": 73.75, "signal_close": 32.60},
        ],
    }
    evaluation = {
        "model_version": "tw-factor-ridge-1",
        "holdout_research_gate_passed": False,
        "live_trading_approved": False,
        "holdout": {"dates": 21, "model_mean_net_excess": -.02114523},
    }
    return audit, ranking, evaluation


class FirstStageReportTests(unittest.TestCase):
    def test_report_has_live_coverage_and_explicit_abstain(self):
        audit, rank, evaluation = fixture()
        result = dashboard.build_summary(
            audit, rank, evaluation, generated_at="2026-11-20T08:00:00+00:00"
        )
        self.assertEqual(result["candidate_stocks"], 1991)
        self.assertEqual(result["stocks_with_prices"], 1968)
        self.assertEqual(result["scored_stocks"], 164)
        self.assertEqual(result["holdout_dates"], 21)
        self.assertEqual(result["score_date"], "2026-11-19")
        self.assertFalse(result["live_trading_approved"])
        self.assertTrue(result["abstain"])
        self.assertFalse(result["line_stock_gateway_enabled"])
        self.assertEqual(result["indicator_pending"], 1044)
        self.assertEqual(result["indicator_eligible"], 1106)
        self.assertEqual(result["indicator_unstarted"], 942)
        self.assertEqual(result["minimum_batches_at_20_per_market"], 53)

    def test_model_version_or_date_drift_fails_closed(self):
        audit, rank, evaluation = fixture()
        rank["date"] = "2026-11-18"
        with self.assertRaisesRegex(ValueError, "score date"):
            dashboard.build_summary(audit, rank, evaluation)
        rank["date"] = "2026-11-19"
        evaluation["model_version"] = "another-model"
        with self.assertRaisesRegex(ValueError, "versions"):
            dashboard.build_summary(audit, rank, evaluation)

    def test_gate_cannot_publish_unverified_trade_signals(self):
        audit, rank, evaluation = fixture()
        rank["abstain"] = False
        with self.assertRaisesRegex(ValueError, "abstain"):
            dashboard.build_summary(audit, rank, evaluation)
        rank["abstain"] = True
        evaluation["holdout_research_gate_passed"] = True
        with self.assertRaisesRegex(ValueError, "holdout"):
            dashboard.build_summary(audit, rank, evaluation)

    def test_empty_or_inconsistent_universe_is_rejected(self):
        audit, rank, evaluation = fixture()
        rank["stocks"] = []
        with self.assertRaisesRegex(ValueError, "No valid"):
            dashboard.build_summary(audit, rank, evaluation)
        rank["stocks"] = fixture()[1]["stocks"]
        audit["coverage"][0]["universe"] = 0
        with self.assertRaisesRegex(ValueError, "Invalid stock universe"):
            dashboard.build_summary(audit, rank, evaluation)

    def test_quality_or_date_anomaly_is_visible(self):
        audit, rank, evaluation = fixture()
        audit["quality"]["invalid_close"] = 3
        audit["latest"]["latest_price_date"] = "2026-11-20"
        report = dashboard.build_summary(audit, rank, evaluation)
        self.assertEqual(report["quality_violations"], 3)
        self.assertTrue(any("資料品質" in w for w in report["warnings"]))
        self.assertTrue(any("日期不同" in w for w in report["warnings"]))

    def test_html_sanitizes_untrusted_market_names(self):
        audit, rank, evaluation = fixture()
        rank["stocks"][0]["name"] = '<img src=x onerror="alert(1)">'
        report = dashboard.build_summary(audit, rank, evaluation)
        html = dashboard.html_report(report)
        self.assertIn("&lt;img", html)
        self.assertNotIn('<img src=x', html)
        self.assertIn("abstain=true", html)

    def test_markdown_and_html_have_readable_outputs(self):
        report = dashboard.build_summary(*fixture())
        text = dashboard.markdown_report(report)
        html = dashboard.html_report(report)
        self.assertIn("台股研究分析", text)
        self.assertIn("1968", text.replace(",", ""))
        self.assertIn("1614", html)
        self.assertIn("不是買賣建議", text)
        self.assertIn("待補", text)
        self.assertIn("1,044", text)
        self.assertIn("最少 53", html)
        self.assertIn("live_trading_approved=false", html)

    def test_missing_backlog_evidence_or_inconsistent_counts_cannot_look_complete(self):
        audit, rank, evaluation = fixture()
        del audit["indicator_backlog"]
        with self.assertRaisesRegex(ValueError, "Missing fresh indicator"):
            dashboard.build_summary(audit, rank, evaluation)
        audit, rank, evaluation = fixture()
        audit["indicator_backlog"][1]["pending"] = 0
        with self.assertRaisesRegex(ValueError, "Inconsistent indicator"):
            dashboard.build_summary(audit, rank, evaluation)

    def test_duplicate_or_negative_market_backlog_is_rejected(self):
        audit, rank, evaluation = fixture()
        audit["indicator_backlog"].append(dict(audit["indicator_backlog"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate markets"):
            dashboard.build_summary(audit, rank, evaluation)
        audit, rank, evaluation = fixture()
        audit["indicator_backlog"][1]["unstarted"] = -1
        with self.assertRaisesRegex(ValueError, "Negative"):
            dashboard.build_summary(audit, rank, evaluation)

    def test_real_model_artifacts_remain_failed_holdout(self):
        base = Path(__file__).resolve().parents[1] / "models"
        rank = json.loads((base / "tw-factor-ridge-1-ranking-snapshot.json").read_text(encoding="utf-8"))
        evaluation = json.loads((base / "tw-factor-ridge-1-evaluation.json").read_text(encoding="utf-8"))
        self.assertEqual(rank["model_version"], evaluation["model_version"])
        self.assertTrue(rank["abstain"])
        self.assertFalse(evaluation["holdout_research_gate_passed"])
        self.assertFalse(evaluation["live_trading_approved"])
