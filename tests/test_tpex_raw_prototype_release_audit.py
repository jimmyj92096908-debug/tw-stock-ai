"""Release gates never translate retrospective raw-price research into approval."""
from copy import deepcopy
from json import loads
from pathlib import Path
from unittest import TestCase

from scripts import tpex_raw_prototype_release_audit as m

ROOT=Path(__file__).resolve().parents[1]

def old():
    return loads((ROOT/"models/tw-factor-ridge-1-evaluation.json").read_text())

def new():
    return {
        "scope":"TPEX_RAW_ONLY_IN_MEMORY_MODEL_INPUT_AND_UNADJUSTED_PROTOTYPE",
        "feature_version":"tw-raw-price-asof-bridge-1",
        "prototype_status":"RETROSPECTIVE_EXPLORATORY_UNADJUSTED_PRICE_ONLY",
        "holdout_independent_windows":2,
        "purged_exploratory_development_dates":28,
        "included_stocks":6,
        "accepted_full_cohort_dates":44,
        "model_release_approved":False,
        "live_trading_approved":False,
        "line_trade_signals_approved":False,
        "database_read_only":True,
        "no_new_persistent_factor_rows":True,
        "raw_return_labels_adjusted_for_dividends":False,
        "future_source_capture_vintage_independently_audited":False,
        "historical_issuer_listing_universe_audited":False,
    }

def prototype():
    return {
        "status":"RETROSPECTIVE_EXPLORATORY_UNADJUSTED_PRICE_ONLY",
        "development_dates":28,
        "nonoverlap_test_windows":[
            {"signal_date":"2026-10-30","entry_date":"2026-11-02",
             "exit_date":"2026-11-09"},
            {"signal_date":"2026-11-10","entry_date":"2026-11-11",
             "exit_date":"2026-11-18"},
        ],
        "may_update_production_model_weights":False,
        "may_release_positive_alpha_or_trade_signals":False,
        "true_pristine_future_holdout":False,
        "label_adjustment_vintage_proven":False,
        "source_capture_vintage_proven":False,
        "survivorship_population_verified":False
    }

class RawPrototypeNoReleaseTests(TestCase):
    def test_live_saved_model_and_raw_experiment_both_blocked(self):
        out=m.review(new(),prototype(),old())
        self.assertEqual(out["saved_model_version"],"tw-factor-ridge-1")
        self.assertEqual(out["saved_model_release_decision"],"BLOCKED")
        self.assertLess(out["saved_model_holdout_mean_net_excess"],0)
        self.assertEqual(out["new_prototype_release_decision"],"BLOCKED")
        self.assertEqual(out["new_raw_nonoverlap_windows"],2)
        self.assertIn("FEWER_THAN_TEN_UNSEEN_NONOVERLAPPING_TEST_WINDOWS",
                      out["blocking_reasons"])
        self.assertFalse(out["may_claim_positive_alpha"])
        self.assertFalse(out["live_trading_approved"])
        self.assertFalse(out["line_signals_approved"])
        self.assertEqual(out["database_writes"],0)
        self.assertIn("沒有證明",m.markdown(out))

    def test_fake_green_claims_never_upgraded_to_trade(self):
        for field in ("model_release_approved","live_trading_approved",
                      "line_trade_signals_approved"):
            report=new()
            report[field]=True
            with self.subTest(field=field),self.assertRaises(ValueError):
                m.review(report,prototype(),old())
        for field in ("may_update_production_model_weights",
                      "may_release_positive_alpha_or_trade_signals",
                      "true_pristine_future_holdout",
                      "source_capture_vintage_proven",
                      "survivorship_population_verified",
                      "label_adjustment_vintage_proven"):
            p=prototype()
            p[field]=True
            with self.subTest(field=field),self.assertRaises(ValueError):
                m.review(new(),p,old())

    def test_no_tampered_window_count_or_time_reversal(self):
        n=new()
        n["holdout_independent_windows"]=10
        with self.assertRaises(ValueError):
            m.review(n,prototype(),old())
        p=prototype()
        p["nonoverlap_test_windows"][1]["signal_date"]="2026-11-03"
        with self.assertRaises(ValueError):
            m.review(new(),p,old())
        n=new()
        n["raw_return_labels_adjusted_for_dividends"]=True
        with self.assertRaises(ValueError):
            m.review(n,prototype(),old())

    def test_workflow_auto_generates_independent_release_blockers_no_db_mutation(self):
        w=(ROOT/".github/workflows/tpex-raw-asof-ai-research.yml").read_text()
        self.assertIn("tpex_raw_prototype_release_audit.py",w)
        self.assertIn("research-release-blockers.json",w)
        self.assertIn("models/tw-factor-ridge-1-evaluation.json",w)
        self.assertIn("git diff --name-only --diff-filter=A HEAD^ HEAD",w)
        self.assertIn(".github/tpex-raw-ai-release-blocker-audit-20261121.txt",w)
        self.assertNotIn("--apply",w)
        self.assertNotIn("  schedule:",w)
        self.assertNotIn("STOCK_TPEX_DATED_HISTORY_WRITE_ENABLED",w)
