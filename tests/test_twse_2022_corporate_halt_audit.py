"""Synthetic offline tests for historical 2327 and 2603 reduction trading halts."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.twse_2022_corporate_halt_audit import (
    EXPECTED_HALT_SESSIONS, classify,
)


def synthetic_report():
    details = [{
        "stock_id": sid,
        "missing_observed_trade_day_count": len(days),
        "missing_observed_trade_dates": list(days),
        "source_refetch_or_neon_write_authorized": False,
    } for sid, days in EXPECTED_HALT_SESSIONS.items()]
    return {
        "schema_version": 1,
        "scope": "TWSE_2022_LOCAL_AES_EXISTING_NEON_READONLY_FROZEN20_FACTOR_RESEARCH",
        "live_model_release_decision": "BLOCKED",
        "neon_transaction_mode": "READ_ONLY",
        "neon_write_operations": 0,
        "line_messages_sent": 0,
        "complete_five_year_history_verified": False,
        "dividends_splits_or_total_return_adjusted": False,
        "sma240_stock_day_gap_diagnostics_available": True,
        "unique_observed_2022_source_sessions": 246,
        "missing_sma240_stock_count": 2,
        "frozen_current_research_stock_count": 20,
        "frozen_stocks_with_complete_last_240_source_sessions": 18,
        "missing_sma240_stock_day_details": details,
    }


class OfflineCashReductionHaltTests(unittest.TestCase):
    def test_fourteen_dates_are_known_halts_but_sma240_is_not_unblocked(self):
        result = classify(synthetic_report())
        self.assertEqual(result["known_cash_reduction_stock_halt_days"], 14)
        self.assertEqual(result["stock_ids_with_known_cash_reduction_halts"],
                         ["2327", "2603"])
        self.assertEqual(result["unknown_stock_day_count"], 0)
        self.assertTrue(result["all_reported_gap_dates_explained_by_known_halts"])
        self.assertEqual(result["source_sma240_complete_stock_count_unchanged"], 18)
        self.assertEqual(result["source_sma240_incomplete_stock_count_unchanged"], 2)
        self.assertFalse(result["sma240_recomputed"])
        self.assertFalse(result["cash_reduction_and_total_return_price_adjustment_performed"])
        self.assertEqual(result["live_model_release_decision"], "BLOCKED")
        self.assertEqual(result["neon_writes"], 0)
        self.assertEqual(result["line_messages_sent"], 0)
        self.assertTrue(all(not e["synthetic_price_or_market_bar_created"]
                            for e in result["classified_halt_stock_day_details"]))

    def test_unmatched_day_is_not_relabelled_as_halt(self):
        report = synthetic_report()
        gap = report["missing_sma240_stock_day_details"][0]
        gap["missing_observed_trade_dates"].append("2022-10-19")
        gap["missing_observed_trade_day_count"] += 1
        result = classify(report)
        self.assertEqual(result["known_cash_reduction_stock_halt_days"], 14)
        self.assertEqual(result["unknown_stock_day_count"], 1)
        self.assertEqual(result["unknown_stock_days"][0]["trade_date"], "2022-10-19")
        self.assertFalse(result["all_reported_gap_dates_explained_by_known_halts"])

    def test_mid_autumn_exchange_holiday_is_not_stock_specific_halt(self):
        report = synthetic_report()
        gap = report["missing_sma240_stock_day_details"][1]
        gap["missing_observed_trade_dates"].append("2022-09-09")
        gap["missing_observed_trade_day_count"] += 1
        result = classify(report)
        self.assertEqual(result["known_cash_reduction_stock_halt_days"], 14)
        self.assertEqual(result["unknown_stock_day_count"], 1)
        self.assertEqual(result["unknown_stock_days"][0]["trade_date"], "2022-09-09")

    def test_invalid_release_write_corporate_action_or_calendar_proof_refused(self):
        for key, val in (
            ("scope", "UNVERIFIED"), ("neon_write_operations", 1),
            ("line_messages_sent", 2),
            ("live_model_release_decision", "APPROVED"),
            ("dividends_splits_or_total_return_adjusted", True),
            ("sma240_stock_day_gap_diagnostics_available", False),
            ("unique_observed_2022_source_sessions", 239),
        ):
            report = synthetic_report()
            report[key] = val
            with self.assertRaises(ValueError, msg=key):
                classify(report)

    def test_1589_duplicates_and_out_of_year_rejected(self):
        report = synthetic_report()
        report["missing_sma240_stock_day_details"][0]["stock_id"] = "1589"
        with self.assertRaises(ValueError):
            classify(report)
        report = synthetic_report()
        gap = report["missing_sma240_stock_day_details"][0]
        gap["missing_observed_trade_dates"].append("2022-10-20")
        gap["missing_observed_trade_day_count"] += 1
        with self.assertRaises(ValueError):
            classify(report)
        report = synthetic_report()
        gap = report["missing_sma240_stock_day_details"][0]
        gap["missing_observed_trade_dates"].append("2023-01-03")
        gap["missing_observed_trade_day_count"] += 1
        with self.assertRaises(ValueError):
            classify(report)

    def test_cli_keeps_report_private_no_overwrite(self):
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source-evidence.json"
            target = Path(temp) / "classified-evidence.json"
            source.write_text(json.dumps(synthetic_report()), encoding="utf-8")
            cmd = [
                sys.executable, "-m", "scripts.twse_2022_corporate_halt_audit",
                "--in", str(source), "--out", str(target),
            ]
            first = subprocess.run(cmd, cwd=repo_root, capture_output=True,
                                   text=True, timeout=20)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn("KNOWN_2022_CASH_REDUCTION_HALT_AUDIT_PASS", first.stdout)
            self.assertTrue(target.is_file())
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))
                             ["known_cash_reduction_stock_halt_days"], 14)
            second = subprocess.run(cmd, cwd=repo_root, capture_output=True,
                                    text=True, timeout=20)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))
                             ["neon_writes"], 0)


if __name__ == "__main__":
    unittest.main()
