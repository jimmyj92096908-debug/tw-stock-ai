"""Independent acceptance tests for the *trained* model and its research gate."""
from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from src import trained_factor_model as model
from scripts import trained_factor_pipeline as cli


SPLIT = date(2026, 10, 1)


def sample(*, negative_holdout=False):
    rows = []
    for first, count in ((date(2026, 8, 1), 30), (SPLIT, 15)):
        for i in range(count):
            day = first + timedelta(days=i)
            for j in range(10):
                ret = (5 - j) / 100
                if first == SPLIT and negative_holdout:
                    ret = -ret
                rows.append({
                    "market": "twse", "stock_id": str(1300+j),
                    "as_of_date": day,
                    "total_score": 95-5*j,
                    "technical_score": 90-4*j,
                    "smc_score": 80-3*j,
                    "short_term_score": 85-4*j,
                    "swing_score": 75-2*j,
                    "long_term_score": None,  # Missing data is explicit.
                    "coverage_weight": 0.60,
                    "adjusted_close": 100.0,
                    "entry_close": 100.0,
                    "exit_close": 100*(1+ret),
                    "exit_date": day+timedelta(days=10),
                })
    return rows


class TrainedModelContracts(unittest.TestCase):
    def test_model_trains_and_fits_only_development(self):
        data = sample()
        artifact, report = model.train_and_verify(data, holdout_start=SPLIT)
        self.assertEqual(artifact["version"], model.VERSION)
        self.assertEqual(artifact["development_dates"], 30)
        self.assertEqual(artifact["development_rows"], 300)
        self.assertEqual(len(artifact["weights"]), len(model.FEATURE_NAMES))
        self.assertEqual(report["holdout"]["dates"], 15)
        self.assertEqual(report["development"]["dates"], 30)
        self.assertFalse(report["live_trading_approved"])
        self.assertFalse(artifact["may_send_trade_signals"])

    def test_holdout_label_changes_cannot_retrain_artifact(self):
        good, good_report = model.train_and_verify(sample(), holdout_start=SPLIT)
        bad, bad_report = model.train_and_verify(sample(negative_holdout=True), holdout_start=SPLIT)
        self.assertEqual(good, bad)  # SHA and coefficients identical.
        self.assertNotEqual(good_report["holdout"], bad_report["holdout"])
        self.assertFalse(bad_report["holdout_research_gate_passed"])
        self.assertFalse(bad_report["line_signal_delivery_approved"])

    def test_input_row_order_cannot_influence_weights_or_audit(self):
        rows = sample()
        a, audit_a = model.train_and_verify(rows, holdout_start=SPLIT)
        b, audit_b = model.train_and_verify(list(reversed(rows)), holdout_start=SPLIT)
        self.assertEqual(a, b)
        self.assertEqual(audit_a, audit_b)

    def test_missing_future_label_disqualifies_whole_day(self):
        rows = sample()
        for r in rows:
            if r["as_of_date"] == SPLIT and r["stock_id"] == "1300":
                r["exit_close"] = None
        _, audit = model.train_and_verify(rows, holdout_start=SPLIT)
        self.assertEqual(audit["holdout"]["dates"], 14)
        self.assertEqual(audit["exclusions"]["skipped_dates"]["incomplete_forward"], 1)

    def test_training_period_must_be_purged_before_holdout(self):
        rows = sample()
        day = date(2026, 9, 30)
        rows.extend({
            **r, "as_of_date": day, "exit_date": date(2026, 10, 8)
        } for r in sample()[:10])
        _, audit = model.train_and_verify(rows, holdout_start=SPLIT)
        self.assertEqual(audit["exclusions"]["skipped_dates"]["split_embargo"], 1)

    def test_low_coverage_or_missing_adjusted_signal_never_imputed(self):
        rows = sample()
        rows[0]["coverage_weight"] = 0.35
        rows[1]["adjusted_close"] = None
        groups, invalid = model.groups_from_rows(rows, holdout_start=SPLIT)
        self.assertEqual(invalid["excluded"]["bad_signal"], 1)
        self.assertEqual(invalid["excluded"]["missing_adjusted_signal"], 1)
        self.assertEqual(len(groups["development"]), 30)

    def test_training_requires_actual_history(self):
        with self.assertRaisesRegex(ValueError, "Not enough"):
            model.train_and_verify(sample()[:10], holdout_start=SPLIT)

    def test_artifact_reproduces_ranking_but_never_trade_signal(self):
        artifact, _ = model.train_and_verify(sample(), holdout_start=SPLIT)
        today = date(2026, 11, 19)
        snapshot = [{
            **r, "as_of_date": today, "stock_name": "testing",
            "signal_close": 100.0
        } for r in sample()[:10]]
        output = model.research_rank(snapshot, artifact, limit=3)
        self.assertEqual(len(output["stocks"]), 3)
        self.assertEqual(output["stocks"][0]["stock_id"], "1300")
        self.assertTrue(output["abstain"])
        self.assertFalse(output["live_trading_approved"])
        self.assertNotIn("buy", json.dumps(output).lower())

    def test_reject_mismatched_or_tampered_artifact(self):
        artifact, _ = model.train_and_verify(sample(), holdout_start=SPLIT)
        with self.assertRaisesRegex(ValueError, "mismatched"):
            model.research_rank([], {**artifact, "feature_names": []})
        with self.assertRaisesRegex(ValueError, "coefficients"):
            model.research_rank([], {**artifact, "weights": [1, 2]})

    def test_sql_contract_reads_real_bars_without_future_features(self):
        query = model.TRAINING_SQL
        self.assertIn("LEAD(a.close,6)", query)
        self.assertIn("LEAD(p.trade_date,6)", query)
        self.assertIn("LEAD(p.trade_date,1)", query)
        self.assertIn("p.entry_date", query)
        self.assertIn("p.trade_date=s.as_of_date", query)
        self.assertIn("LEFT JOIN public.daily_adjusted_prices", query)
        self.assertNotIn("INSERT INTO", query)
        self.assertNotIn("UPDATE ", query)
        self.assertIn("SET TRANSACTION READ ONLY", Path(cli.__file__).read_text())

    def test_end_to_end_local_artifacts_and_research_output(self):
        data = sample()
        with TemporaryDirectory() as tmp:
            artifact_path = Path(tmp) / "model.json"
            report_path = Path(tmp) / "report.json"
            rank_path = Path(tmp) / "rank.json"
            with patch.object(cli, "read_only_rows", return_value=data):
                result = cli.execute_train(
                    "fake-readonly-url", start=date(2026, 8, 1),
                    holdout_start=SPLIT, end=date(2026, 11, 19),
                    model_out=artifact_path, report_out=report_path,
                )
            self.assertEqual(result["trained_development_days"], 30)
            fitted = json.loads(artifact_path.read_text())
            self.assertEqual(fitted["version"], model.VERSION)
            self.assertIn("holdout", json.loads(report_path.read_text()))
            snapshot = [{
                **r, "as_of_date": date(2026, 11, 19),
                "stock_name": "testing", "signal_close": 100.0
            } for r in data[:10]]
            with patch.object(cli, "read_only_rows", return_value=snapshot):
                output = cli.execute_rank(
                    "fake-readonly-url", model_path=artifact_path,
                    output=rank_path, limit=10,
                )
            self.assertEqual(output["ranked"], 10)
            self.assertTrue(json.loads(rank_path.read_text())["abstain"])


if __name__ == "__main__":
    unittest.main()
