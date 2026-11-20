"""Independent numerical audit of real Neon-fitted model artifacts.

Aggregated X'X and X'y are stored without raw market rows or credentials so a
separate CI run recomputes the published weights from first principles.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import unittest

import numpy as np

from src.trained_factor_model import FEATURE_NAMES, VERSION, research_rank


ROOT = Path(__file__).resolve().parents[1] / "models"


def load(filename):
    return json.loads((ROOT / filename).read_text(encoding="utf-8"))


class PublishedArtifactAcceptance(unittest.TestCase):
    def test_saved_coefficients_are_reproducible_from_independent_statistics(self):
        model = load("tw-factor-ridge-1-research.json")
        sufficient = load("tw-factor-ridge-1-training-sufficient-stats.json")
        self.assertEqual(model["version"], VERSION)
        self.assertEqual(model["feature_names"], list(FEATURE_NAMES))
        self.assertEqual(sufficient["train_days"], model["development_dates"])
        self.assertEqual(sufficient["train_rows"], model["development_rows"])
        self.assertEqual(sufficient["regularization"], model["regularization"])
        mat = np.asarray(sufficient["gram"], dtype=float)
        rhs = np.asarray(sufficient["rhs"], dtype=float)
        self.assertEqual(mat.shape, (len(FEATURE_NAMES), len(FEATURE_NAMES)))
        self.assertTrue(np.allclose(mat, mat.T, atol=1e-10))
        self.assertTrue(np.all(np.linalg.eigvalsh(mat) > 0))
        computed = np.linalg.solve(mat, rhs)
        saved = np.asarray(model["weights"], dtype=float)
        np.testing.assert_allclose(saved, computed, rtol=1e-7, atol=1e-10)
        self.assertTrue(np.all(np.isfinite(computed)))
        self.assertFalse(model["may_send_trade_signals"])
        self.assertTrue(model["holdout_previously_examined_during_model_design"])

    def test_real_holdout_failure_remains_visible_and_blocks_signals(self):
        report = load("tw-factor-ridge-1-evaluation.json")
        self.assertEqual(report["development"]["dates"], 57)
        self.assertEqual(report["holdout"]["dates"], 21)
        self.assertLess(report["holdout"]["model_mean_net_excess"], 0)
        self.assertFalse(report["holdout_research_gate_passed"])
        self.assertFalse(report["line_signal_delivery_approved"])
        self.assertFalse(report["live_trading_approved"])
        self.assertTrue(report["holdout_previously_examined_during_model_design"])
        self.assertFalse(report["holdout_is_pristine_independent_validation"])
        self.assertTrue(report["requires_new_unseen_future_holdout"])

    def test_real_latest_rankings_are_historical_and_abstain(self):
        model = load("tw-factor-ridge-1-research.json")
        snapshot = load("tw-factor-ridge-1-ranking-snapshot.json")
        self.assertEqual(snapshot["model_version"], model["version"])
        self.assertTrue(snapshot["from_saved_weights"])
        self.assertGreaterEqual(snapshot["eligible_universe"], 5)
        self.assertTrue(snapshot["abstain"])
        self.assertFalse(snapshot["live_trading_approved"])
        self.assertEqual([x["rank"] for x in snapshot["ranked"]],
                         list(range(1, len(snapshot["ranked"])+1)))
        self.assertLessEqual(len(snapshot["ranked"]), 10)
        self.assertTrue(all(math.isfinite(x["relative_model_score"])
                            for x in snapshot["ranked"]))
        self.assertNotIn("DATABASE_URL", json.dumps(model))
        self.assertNotIn("LINE_CHANNEL_SECRET", json.dumps(snapshot))

    def test_artifact_loads_for_new_score_ranking_without_trade_mode(self):
        model = load("tw-factor-ridge-1-research.json")
        current = [{
            "market": "twse", "stock_id": str(2300+i),
            "as_of_date": "2026-11-19", "stock_name": "Test",
            "total_score": 80-i, "technical_score": 70-i,
            "smc_score": 65-i, "short_term_score": 75-i,
            "swing_score": 70-i, "long_term_score": None,
            "coverage_weight": .6, "signal_close": 100,
        } for i in range(8)]
        ranked = research_rank(current, model, limit=5)
        self.assertEqual(len(ranked["stocks"]), 5)
        self.assertTrue(ranked["abstain"])
        self.assertFalse(ranked["live_trading_approved"])


if __name__ == "__main__":
    unittest.main()
