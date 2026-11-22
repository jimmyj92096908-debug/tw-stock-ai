"""Validate actual no-trade release blocker for 20-stock raw Ridge research."""
from copy import deepcopy
from json import loads
from pathlib import Path
from unittest import TestCase

from scripts.twse_raw_model_release_audit import review


ROOT = Path(__file__).resolve().parents[1]
SAVED = loads((ROOT / "models/tw-factor-ridge-1-evaluation.json").read_text())


def fixture():
    p = {
        "scope": "TWSE_TWENTY_STOCK_CAUSAL_RAW_RESEARCH_ONLY",
        "included_stocks": 20, "feature_version": "tw-raw-price-asof-bridge-1",
        "source_price_rows": 8000, "accepted_whole_cohort_dates": 94,
        "dataset_sha256": "a" * 64,
        "prototype_status": "RETROSPECTIVE_EXPLORATORY_UNADJUSTED_PRICE_ONLY",
        "expanding_purged_status": "RETROSPECTIVE_EXPANDING_PURGED_RAW_ONLY",
        "nonoverlapping_holdout_windows": 2, "expanding_purged_windows": 2,
        "mean_illustrative_net_excess_vs_equal_weight": -0.01,
        "expanding_mean_net_excess_vs_equal_weight": -0.005,
        "independent_future_validation_passed": False,
        "expanding_independent_future_validation_passed": False,
        "dividend_adjusted_total_return_proven": False,
        "original_historical_exchange_universe_audited": False,
        "historical_asof_capture_vintage_proven": False,
        "live_trading_approved": False, "line_messages_sent": False,
        "neon_read_only": True, "no_derived_database_rows_written": True,
        "production_tw_factor_ridge_1_unchanged": True,
        "retrospective_test_split_previously_reviewed": True,
        "expanding_training_uses_only_mature_labels": True,
    }
    windows = [
        ("2026-09-01", "2026-09-02", "2026-09-10"),
        ("2026-09-11", "2026-09-14", "2026-09-22"),
    ]
    f = {
        "status": "RETROSPECTIVE_EXPLORATORY_UNADJUSTED_PRICE_ONLY",
        "live_trading_approved": False,
        "nonoverlap_test_windows": [
            {"signal_date": a, "entry_date": b, "exit_date": c,
             "illustrative_net_excess_vs_equal_weight": -0.01}
            for a, b, c in windows],
    }
    e = {
        "status": "RETROSPECTIVE_EXPANDING_PURGED_RAW_ONLY",
        "dataset_rows_sha256": p["dataset_sha256"], "count": 2,
        "trading_approved": False,
        "mean_illustrative_net_excess_vs_equal_weight": -0.005,
        "nonoverlap_windows": [
            {"signal_date": a, "entry_date": b, "exit_date": c,
             "last_mature_training_exit": "2026-08-29",
             "assumed_net_excess_vs_equal_weight": -0.005}
            for a, b, c in windows],
    }
    return p, f, e, deepcopy(SAVED)


class TWSEIndependentReleaseBlockerTests(TestCase):
    def test_negative_expanding_and_old_model_are_blocked(self):
        out = review(*fixture())
        self.assertEqual(out["decision"], "BLOCKED")
        self.assertEqual(out["saved_model_version"], "tw-factor-ridge-1")
        self.assertLess(out["saved_model_net_holdout_excess"], 0)
        self.assertIn("NONPOSITIVE_EXPANDING_MODEL_NET_EXCESS",
                      out["blocking_reasons"])
        self.assertIn("NONPOSITIVE_FIXED_MODEL_NET_EXCESS",
                      out["blocking_reasons"])
        self.assertIn("TOO_FEW_NONOVERLAPPING_RESEARCH_WINDOWS",
                      out["blocking_reasons"])
        self.assertFalse(out["positive_alpha_approved"])
        self.assertFalse(out["live_trading_approved"])
        self.assertFalse(out["line_signal_delivery_approved"])
        self.assertEqual(out["database_writes"], 0)

    def test_even_positive_test_scores_cannot_approve_retrospective_alpha(self):
        p, f, e, saved = fixture()
        p["mean_illustrative_net_excess_vs_equal_weight"] = 0.02
        p["expanding_mean_net_excess_vs_equal_weight"] = 0.03
        e["mean_illustrative_net_excess_vs_equal_weight"] = 0.03
        for w in f["nonoverlap_test_windows"]:
            w["illustrative_net_excess_vs_equal_weight"] = 0.02
        for w in e["nonoverlap_windows"]:
            w["assumed_net_excess_vs_equal_weight"] = 0.03
        out = review(p, f, e, saved)
        self.assertEqual(out["decision"], "BLOCKED")
        self.assertFalse(out["positive_alpha_approved"])
        self.assertIn("RETROSPECTIVE_SPLIT_NOT_PRISTINE", out["blocking_reasons"])
        self.assertIn("NO_PRECOMMITTED_INDEPENDENT_FUTURE_MODEL_VALIDATION",
                      out["blocking_reasons"])

    def test_tampering_with_future_labels_and_actual_windows_is_rejected(self):
        for bad in ("dataset", "arithmetic", "overlap", "purge", "missing_purge", "mismatched_holding_period", "approval"):
            p, f, e, saved = fixture()
            if bad == "dataset":
                e["dataset_rows_sha256"] = "b" * 64
            elif bad == "arithmetic":
                p["expanding_mean_net_excess_vs_equal_weight"] = -0.0123
            elif bad == "overlap":
                e["nonoverlap_windows"][1]["signal_date"] = "2026-09-10"
            elif bad == "purge":
                e["nonoverlap_windows"][0]["last_mature_training_exit"] = "2026-09-01"
            elif bad == "missing_purge":
                del e["nonoverlap_windows"][0]["last_mature_training_exit"]
            elif bad == "mismatched_holding_period":
                e["nonoverlap_windows"][1]["entry_date"] = "2026-09-15"
            else:
                p["live_trading_approved"] = True
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                review(p, f, e, saved)

    def test_must_keep_real_readonly_audit_in_workflow(self):
        wf = (ROOT / ".github/workflows/twse-raw-model-readonly.yml").read_text()
        self.assertIn("twse_raw_model_release_audit.py", wf)
        self.assertIn("model-release-blockers.json", wf)
        self.assertNotIn("STOCK_TWSE_HISTORY_WRITE_ENABLED", wf)
        self.assertNotIn("  schedule:", wf)
