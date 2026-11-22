"""Synthetic-only source-anchored cash-reduction parity tests; no Neon."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from scripts.twse_2022_cash_reduction_reference_readonly import (
    EVENTS, TWSE_RULE,
    economic_one_old_share_value, prove_cash_reduction_references,
    pure_reference_cash_reduction,
)
from tests.test_twse_2021_22_traded_240_warmup_readonly import input_fixture


def fixture():
    report, market, _, _ = input_fixture()
    closes = {
        ("2327", date(2022, 10, 19)): Decimal("268"),
        ("2327", date(2022, 10, 31)): Decimal("340"),
        ("2603", date(2022, 9, 6)): Decimal("80.8"),
        ("2603", date(2022, 9, 19)): Decimal("179"),
    }
    return report, market, closes


class CashReductionReferenceOfflineTests(unittest.TestCase):
    def test_contemporaneous_cash_reference_parity_and_halt_guard(self):
        report, market, closes = fixture()
        result = prove_cash_reduction_references(
            report, dict(report), set(market), closes)
        self.assertEqual(
            result["stocks_with_2022_actual_source_and_historical_reference_parity"], 2)
        self.assertEqual(result["halt_market_days_not_rewritten_as_trades"], 14)
        self.assertEqual(result["frozen20_market_day_sma240_complete_unchanged"], 18)
        self.assertEqual(result["neon_writes"], 0)
        self.assertEqual(result["line_messages_sent"], 0)
        self.assertEqual(result["live_model_release_decision"], "BLOCKED")
        for witness in result["stock_action_research_witnesses"]:
            self.assertTrue(
                witness["theoretical_exchange_reference_price_parity_within_0_01"])
            self.assertFalse(
                witness["sma240_from_corporate_action_adjusted_ohlc_completed"])
            self.assertFalse(witness["complete_total_return_and_cost_model_verified"])
        self.assertFalse(result["adjusted_daily_ma240_computed"])
        self.assertFalse(result["stock_buy_sell_execution_or_cash_settlement_verified"])

    def test_decimal_twse_reference_formula_exact_not_historical_close_guess(self):
        p2327 = pure_reference_cash_reduction(
            Decimal("268"), Decimal("2.0407502943"),
            Decimal("0.79592497057"))
        self.assertLess(abs(p2327 - Decimal("334.15")), Decimal("0.01"))
        self.assertNotEqual(p2327, Decimal("334"))  # auction tick is different
        self.assertEqual(pure_reference_cash_reduction(
            Decimal("80.8"), Decimal("6"), Decimal("0.4")),
            Decimal("187"))
        self.assertIn("twse.com.tw", TWSE_RULE)
        # Genuine portfolio economic identity is not (new_share / old_share)-1.
        self.assertEqual(economic_one_old_share_value(
            Decimal("180"), Decimal("6"), Decimal("0.4")), Decimal("78"))
        self.assertEqual(EVENTS["2603"]["cash_refund_payment"], date(2022, 9, 29))

    def test_witness_wrong_old_close_fail_closed(self):
        report, market, closes = fixture()
        closes[("2603", date(2022, 9, 6))] = Decimal("81")
        with self.assertRaisesRegex(ValueError, "contemporaneous old close"):
            prove_cash_reduction_references(report, dict(report), set(market), closes)

    def test_source_evidence_drift_must_fail(self):
        report, market, closes = fixture()
        for key, val in (
            ("private_result_fingerprint_sha256", "injected"),
            ("neon_write_operations", 1),
            ("live_model_release_decision", "APPROVED"),
        ):
            now = dict(report, **{key: val})
            with self.assertRaisesRegex(ValueError, "changed", msg=key):
                prove_cash_reduction_references(report, now, set(market), closes)

    def test_halt_day_price_must_never_count_as_trade(self):
        report, market, closes = fixture()
        closes[("2327", date(2022, 10, 20))] = Decimal("270")
        with self.assertRaisesRegex(ValueError, "halt stock-day"):
            prove_cash_reduction_references(report, dict(report), set(market), closes)

    def test_missing_resume_price_blocks_reference_audit(self):
        report, market, closes = fixture()
        del closes[("2327", date(2022, 10, 31))]
        with self.assertRaisesRegex(ValueError, "witnesses invalid"):
            prove_cash_reduction_references(report, dict(report), set(market), closes)

    def test_corrupt_refund_ratio_fails_and_no_release(self):
        report, market, closes = fixture()
        alternate = dict(EVENTS["2327"])
        alternate["cash_per_old_share"] = Decimal("2")
        with patch.dict(EVENTS, {"2327": alternate}):
            with self.assertRaisesRegex(ValueError, "capital facts"):
                prove_cash_reduction_references(
                    report, dict(report), set(market), closes)

    def test_decimal_math_fail_closed_for_invalid_inputs(self):
        for old, cash, ratio in (
            (Decimal("5"), Decimal("6"), Decimal(".4")),
            (Decimal("NaN"), Decimal("1"), Decimal(".4")),
            (Decimal("5"), Decimal("0"), Decimal("1")),
            (Decimal("5"), Decimal("-1"), Decimal(".4")),
        ):
            with self.assertRaises(ValueError):
                pure_reference_cash_reduction(old, cash, ratio)
        with self.assertRaises(ValueError):
            economic_one_old_share_value(
                Decimal("0"), Decimal("6"), Decimal(".4"))

    def test_public_no_credentials_help(self):
        repo = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env.pop("DATABASE_URL", None)
        env.pop("STOCK_ARCHIVE_KEY_HEX", None)
        env.pop("PYTHONPATH", None)
        result = subprocess.run(
            [sys.executable, "-m",
             "scripts.twse_2022_cash_reduction_reference_readonly", "--help"],
            cwd=repo, env=env, capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--source-report", result.stdout)
        self.assertIn("--archive-2022", result.stdout)


if __name__ == "__main__":
    unittest.main()
