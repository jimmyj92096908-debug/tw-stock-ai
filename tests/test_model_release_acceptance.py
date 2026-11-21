"""Model release must remain blocked by the actual negative/reused holdout."""
from __future__ import annotations
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from src.model_release_acceptance import evaluate_release
from scripts import research_model_release_audit as cli

ROOT=Path(__file__).resolve().parents[1]


class ModelReleaseGateTests(unittest.TestCase):
    def saved(self):
        return json.loads((ROOT/"models/tw-factor-ridge-1-evaluation.json").read_text(encoding="utf-8"))

    def test_actual_persisted_ridge_holdout_cannot_be_promoted(self):
        out=evaluate_release(self.saved())
        self.assertEqual(out["model_version"],"tw-factor-ridge-1")
        self.assertEqual(out["decision"],"BLOCKED")
        self.assertLess(out["saved_holdout_mean_net_excess"],0)
        self.assertIn("NEGATIVE_OR_ZERO_SAVED_NET_EXCESS",out["blocking_reasons"])
        self.assertIn("EXAMINED_HOLDOUT_NOT_INDEPENDENT",out["blocking_reasons"])
        self.assertIn("NO_VERIFIED_HISTORICAL_MATURITY_REPORT",out["blocking_reasons"])
        self.assertIn("NO_FROZEN_FORWARD_INDEPENDENT_EVALUATION",out["blocking_reasons"])
        self.assertFalse(out["live_trading_approved"])
        self.assertFalse(out["line_signal_delivery_approved"])
        self.assertFalse(out["model_weights_modified"])

    def test_actual_four_independent_windows_still_fail_even_if_scores_complete(self):
        maturity={
            "nonoverlapping_actual_holding_windows":4,
            "eligible_for_exploratory_outcome_research":False,
            "corporate_action_adjustment_vintage_verified":False,
            "market_wide_survivorship_bias_audited":False
        }
        out=evaluate_release(self.saved(),historical_label_report=maturity)
        self.assertEqual(out["historical_independent_windows"],4)
        self.assertIn("INSUFFICIENT_NONOVERLAPPING_MATURE_WINDOW_COHORT",out["blocking_reasons"])
        self.assertIn("SURVIVORSHIP_BIAS_NOT_AUDITED",out["blocking_reasons"])
        self.assertIn("ADJUSTED_PRICE_ASOF_VINTAGE_UNVERIFIED",out["blocking_reasons"])
        self.assertFalse(out["research_evaluation_quality_passed"])

    def test_cannot_release_without_precommitted_reviewed_and_cost_stress_holdout(self):
        saved=self.saved()
        saved["holdout"]["model_mean_net_excess"]=0.02
        saved["holdout"]["original_score_mean_net_excess"]=0.005
        saved["holdout_research_gate_passed"]=True
        saved["holdout_is_pristine_independent_validation"]=True
        saved["requires_new_unseen_future_holdout"]=False
        maturity={
            "nonoverlapping_actual_holding_windows":20,
            "eligible_for_exploratory_outcome_research":True,
            "corporate_action_adjustment_vintage_verified":True,
            "market_wide_survivorship_bias_audited":True,
        }
        unseen={
            "model_version":"tw-factor-ridge-1",
            "precommitted_before_labels":False,
            "independent_provenance_reviewed":False,
            "net_costs_liquidity_stress_passed":False,
            "nonoverlapping_holdout_periods_verified":False
        }
        out=evaluate_release(saved,historical_label_report=maturity,
                             independently_frozen_future_holdout=unseen)
        self.assertEqual(out["decision"],"BLOCKED")
        self.assertIn("FUTURE_EVALUATION_NOT_PRECOMMITTED",out["blocking_reasons"])
        self.assertIn("FUTURE_EVALUATION_NOT_INDEPENDENTLY_REVIEWED",out["blocking_reasons"])
        self.assertIn("REAL_COST_LIQUIDITY_STRESS_UNVERIFIED",out["blocking_reasons"])
        self.assertFalse(out["live_trading_approved"])
        # Even completely positive *submitted* evidence only permits human
        # review. It must NEVER turn on LINE or real-money orders automatically.
        unseen={k:(True if k.endswith("_verified") or k.endswith("_passed")
                   or k=="precommitted_before_labels" or k=="independent_provenance_reviewed"
                   else v) for k,v in unseen.items()}
        positive=evaluate_release(saved,historical_label_report=maturity,
                                  independently_frozen_future_holdout=unseen)
        self.assertTrue(positive["research_evaluation_quality_passed"])
        self.assertEqual(positive["decision"],"ELIGIBLE_FOR_INDEPENDENT_HUMAN_REVIEW_ONLY")
        self.assertFalse(positive["live_trading_approved"])
        self.assertFalse(positive["line_signal_delivery_approved"])

    def test_fabricated_missing_invalid_evidence_rejected(self):
        base=self.saved()
        with self.assertRaises(ValueError):
            evaluate_release({})
        with self.assertRaises(ValueError):
            evaluate_release({**base,"holdout":{**base["holdout"],"dates":True}})
        with self.assertRaises(ValueError):
            evaluate_release({**base,"holdout":{**base["holdout"],"model_mean_net_excess":float("nan")}})
        with self.assertRaises(ValueError):
            evaluate_release(base,historical_label_report={"nonoverlapping_actual_holding_windows":-1})
        with self.assertRaises(ValueError):
            evaluate_release(base,independently_frozen_future_holdout={"model_version":"different"})

    def test_offline_artifact_does_not_touch_neon_or_live_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/"release-report.json"
            with patch("sys.argv",["research_model_release_audit","--out",str(dest)]):
                cli.main()
            output=json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(output["decision"],"BLOCKED")
            self.assertFalse(output["database_writes"])
            self.assertFalse(output["live_trading_approved"])
            self.assertEqual(len(output["saved_evaluation_sha256"]),64)


if __name__=="__main__":
    unittest.main()
