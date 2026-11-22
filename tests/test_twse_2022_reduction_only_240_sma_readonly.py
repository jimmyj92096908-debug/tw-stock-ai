"""Synthetic-only evidence gates for 2022 2327/2603 event-only SMA240."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from scripts.twse_2021_22_traded_240_warmup_readonly import (
    summarize_real_traded_warmup,
)
from scripts.twse_2022_cash_reduction_reference_readonly import (
    EVENTS, prove_cash_reduction_references,
)
from scripts.twse_2022_reduction_only_240_sma_readonly import (
    SMA_SCOPE, calculate_event_only_sma240,
)
from tests.test_twse_2021_22_traded_240_warmup_readonly import input_fixture


def make_input():
    report, days, old_dates, new_dates = input_fixture()
    old = {sid: {
        d: Decimal("300") if sid == "2327" else Decimal("85")
        for d in old_dates[sid]
    } for sid in ("2327", "2603")}
    new = {sid: {
        d: (Decimal("270") if d <= EVENTS[sid]["last_old_trade"]
            else Decimal("340")) if sid == "2327" else
           (Decimal("85") if d <= EVENTS[sid]["last_old_trade"]
            else Decimal("179"))
        for d in new_dates[sid]
    } for sid in ("2327", "2603")}
    new["2327"][date(2022, 10, 19)] = Decimal("268")
    new["2603"][date(2022, 9, 6)] = Decimal("80.8")
    warmup = summarize_real_traded_warmup(
        report, dict(report), days,
        set(old_dates["2327"]), # same 28 verified market dates
        {sid: set(bars) for sid, bars in old.items()},
        {sid: set(bars) for sid, bars in new.items()},
    )
    close_witness = {
        (sid, d): new[sid][d]
        for sid, ev in EVENTS.items()
        for d in (ev["last_old_trade"], ev["first_new_trade"])
    }
    reference = prove_cash_reduction_references(
        report, dict(report), days, close_witness)
    return report, days, old, new, warmup, reference


def calculate(fix):
    report, market, old, new, warmup, reference = fix
    return calculate_event_only_sma240(
        report, dict(report), warmup, reference,
        set(old["2327"]), set(market), old, new)


class ReductionOnlySMA240OfflineTests(unittest.TestCase):
    def test_both_stocks_real_240_closes_cash_rebased_with_no_fake_halt(self):
        result = calculate(make_input())
        self.assertEqual(result["scope"], SMA_SCOPE)
        self.assertEqual(result["event_only_240_sma_stock_count"], 2)
        self.assertEqual(result["source_2022_frozen20_market_session_sma240_unchanged"], 18)
        self.assertEqual(result["real_2022_capital_reduction_halt_days_left_without_price"], 14)
        self.assertEqual(result["production_neon_writes"], 0)
        self.assertEqual(result["line_messages_sent"], 0)
        self.assertEqual(result["live_model_release_decision"], "BLOCKED")
        self.assertFalse(result["private_raw_or_adjusted_sma_values_emitted"])
        self.assertFalse(result["complete_all_corporate_actions_adjusted"])
        self.assertFalse(result["walkforward_total_return_alpha_or_deployment_proven"])
        entries = result["stock_capital_reduction_only_research_witnesses"]
        self.assertEqual([x["stock_id"] for x in entries], ["2327", "2603"])
        for row in entries:
            self.assertEqual(row["last240_real_traded_days"], 240)
            self.assertEqual(row["last240_first_real_stock_session"], "2021-12-30")
            self.assertEqual(row["capital_reduction_halt_market_days_not_synthesized"], 7)
            self.assertTrue(row["2022_cash_reduction_only_decimal_sma240_computed_in_ram"])
            self.assertGreater(row["event_only_pre_reduction_stock_bars_rebased"], 0)
            self.assertGreater(row["post_reduction_real_traded_stock_bars"], 0)
            self.assertEqual(row["event_only_pre_reduction_stock_bars_rebased"] +
                             row["post_reduction_real_traded_stock_bars"], 240)
            self.assertFalse(row["all_other_dividends_and_splits_adjusted"])
            self.assertFalse(row["sma_value_or_adjusted_daily_prices_written_to_disk"])

    def test_one_missing_2021_price_fails_even_with_2022_full(self):
        fix = make_input()
        d = max(fix[2]["2327"])
        del fix[2]["2327"][d]
        with self.assertRaises(ValueError):
            calculate(fix)

    def test_halt_day_fake_close_rejected(self):
        fix = make_input()
        fix[3]["2603"][date(2022, 9, 7)] = Decimal("81")
        with self.assertRaises(ValueError):
            calculate(fix)

    def test_wrong_2022_old_close_does_not_masquerade_adjustment(self):
        fix = make_input()
        fix[3]["2327"][date(2022, 10, 19)] = Decimal("267")
        with self.assertRaises(ValueError):
            calculate(fix)

    def test_source_report_drift_fails_closed(self):
        fix = make_input()
        changed = dict(fix[0], **{"neon_write_operations": 1})
        with self.assertRaisesRegex(ValueError, "drifted"):
            calculate_event_only_sma240(
                fix[0], changed, fix[4], fix[5], set(fix[2]["2327"]),
                set(fix[1]), fix[2], fix[3])

    def test_2021_traded_240_proof_must_equal_current_raw_series(self):
        fix = make_input()
        fix[4]["stock_traded_day_research_warmup_proofs"][0][
            "last240_earliest_real_trading_date"] = "2022-01-01"
        with self.assertRaisesRegex(ValueError, "warmup proof drifted"):
            calculate(fix)

    def test_event_reference_proof_must_equal_recomputed_theory(self):
        fix = make_input()
        fix[5]["stock_action_research_witnesses"][1][
            "theoretical_exchange_reference_price_parity_within_0_01"] = False
        with self.assertRaisesRegex(ValueError, "reference evidence drifted"):
            calculate(fix)

    def test_unannounced_capital_terms_refused_not_fitted_to_prices(self):
        fix = make_input()
        ev = dict(EVENTS["2327"], new_shares_per_old=Decimal("0.8"))
        with patch.dict(EVENTS, {"2327": ev}):
            with self.assertRaises(ValueError):
                calculate(fix)

    def test_non_decimal_close_and_future_bar_refused(self):
        fix = make_input()
        fix[2]["2327"][date(2021, 12, 30)] = 300.0
        with self.assertRaisesRegex(ValueError, "Unverified"):
            calculate(fix)
        fix = make_input()
        fix[3]["2603"][date(2023, 1, 3)] = Decimal("190")
        with self.assertRaises(ValueError):
            calculate(fix)

    def test_help_runs_without_neon_or_owner_key(self):
        env = os.environ.copy()
        env.pop("DATABASE_URL", None)
        env.pop("STOCK_ARCHIVE_KEY_HEX", None)
        env.pop("PYTHONPATH", None)
        repo = Path(__file__).resolve().parents[1]
        run = subprocess.run(
            [sys.executable, "-m",
             "scripts.twse_2022_reduction_only_240_sma_readonly", "--help"],
            cwd=repo, env=env, capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("--warmup-report", run.stdout)
        self.assertIn("--reference-report", run.stdout)


if __name__ == "__main__":
    unittest.main()
