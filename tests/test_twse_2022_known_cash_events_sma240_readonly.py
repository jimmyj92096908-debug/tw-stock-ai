"""Synthetic-only: 2 known 2022 cash events across 240 genuine stock days."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from scripts.twse_2022_known_cash_events_sma240_readonly import (
    SCOPE, calculate_two_known_cash_events, two_known_event_price_scale,
)
from scripts.twse_2022_reduction_only_240_sma_readonly import calculate_event_only_sma240
from scripts.twse_2022_dividend_exref_readonly import (
    EVENTS as DIV_EVENTS, verify_precise_cash_reference,
)
from scripts.twse_2022_known_dividend_gap_offline import classify_historical_dividend_gaps
from tests.test_twse_2022_known_dividend_gap_offline import prior
from tests.test_twse_2022_reduction_only_240_sma_readonly import make_input


def evidence():
    original, market, bars21, bars22, warmup, reduction_ref = make_input()
    bars22["2327"][date(2022, 7, 1)] = Decimal("282")
    bars22["2327"][date(2022, 7, 4)] = Decimal("281")
    bars22["2603"][date(2022, 6, 28)] = Decimal("108.5")
    bars22["2603"][date(2022, 6, 29)] = Decimal("90.6")
    reconciled = dict(original)
    reduction_sma = calculate_event_only_sma240(
        original, reconciled, warmup, reduction_ref,
        set(bars21["2327"]), set(market), bars21, bars22)
    gaps = classify_historical_dividend_gaps(prior())
    witness = {
        (sid, d): bars22[sid][d]
        for sid, fact in DIV_EVENTS.items()
        for d in (fact["pre_ex_trade"], fact["ex_trade"])
    }
    dividend_ref = verify_precise_cash_reference(
        original, reconciled, gaps, set(market), witness)
    return (
        original, reconciled, warmup, reduction_ref, reduction_sma,
        gaps, dividend_ref, set(bars21["2327"]), set(market),
        bars21, bars22,
    )


def run(fix):
    return calculate_two_known_cash_events(*fix)


class Two2022CashEventsOfflineTests(unittest.TestCase):
    def test_both_true_stock_240_cash_ex_adjustment_is_research_only(self):
        result = run(evidence())
        self.assertEqual(result["scope"], SCOPE)
        self.assertEqual(result["two_known_cash_events_sma240_stock_count"], 2)
        self.assertEqual(result["dated_dividend_events_included"], 2)
        self.assertEqual(result["dated_capital_reduction_events_included"], 2)
        self.assertEqual(result["genuine_halt_market_days_no_fake_bars"], 14)
        self.assertEqual(result["prior_frozen20_market_day_sma240_readiness_unchanged"], 18)
        self.assertEqual(result["neon_writes"], 0)
        self.assertEqual(result["line_messages_sent"], 0)
        self.assertEqual(result["live_model_release_decision"], "BLOCKED")
        self.assertTrue(result["no_private_numeric_sma_or_raw_price_emitted"])
        self.assertFalse(result["corporate_actions_master_complete"])
        self.assertFalse(result["total_return_cash_payment_or_reinvestment_certified"])
        self.assertFalse(result["walkforward_forward_alpha_or_trading_approved"])
        entries = result["per_stock_two_known_event_research_proofs"]
        self.assertEqual([x["stock_id"] for x in entries], ["2327", "2603"])
        for row in entries:
            self.assertEqual(row["genuine_source_stock_trading_days"], 240)
            self.assertEqual(row["last240_first_stock_trade"], "2021-12-30")
            self.assertEqual(row["last240_last_stock_trade"], "2022-12-30")
            self.assertEqual(row["capital_reduction_halt_market_days_never_imputed"], 7)
            self.assertEqual(sum((
                row["pre_ex_dividend_old_share_stock_days_transformed"],
                row["between_dividend_and_capital_reduction_stock_days_transformed"],
                row["after_capital_reduction_stock_days_untouched"],
            )), 240)
            self.assertTrue(row["known_dividend_amount_lowers_cash_ex_price_scale_sma"])
            self.assertFalse(row["price_or_sma_persisted"])

    def test_event_order_and_cash_units_are_not_interchangeable(self):
        d = Decimal
        kwargs = dict(
            cash_dividend=d("17.99999637"),
            dividend_ex_date=date(2022, 6, 29),
            cash_reduction=d("6"),
            reduction_last_old_date=date(2022, 9, 6),
            reduction_resume_date=date(2022, 9, 19),
            new_shares_per_old=d(".4"),
        )
        before = two_known_event_price_scale(
            d("108.5"), date(2022, 6, 28), **kwargs)
        self.assertEqual(before, (d("108.5") - d("17.99999637") - d("6")) / d(".4"))
        self.assertEqual(two_known_event_price_scale(
            d("100"), date(2022, 6, 29), **kwargs), d("235"))
        self.assertEqual(two_known_event_price_scale(
            d("180"), date(2022, 9, 19), **kwargs), d("180"))
        with self.assertRaisesRegex(ValueError, "halt"):
            two_known_event_price_scale(
                d("80"), date(2022, 9, 7), **kwargs)
        with self.assertRaises(ValueError):
            two_known_event_price_scale(
                d("1"), date(2022, 6, 28), **kwargs)

    def test_wrong_dividend_amount_rejects_prior_event_proof(self):
        fix = evidence()
        shifted = dict(DIV_EVENTS["2327"], declared_cash_per_old_share=Decimal("10"))
        with patch.dict(DIV_EVENTS, {"2327": shifted}):
            with self.assertRaises(ValueError):
                run(fix)

    def test_forged_or_stale_prior_dividend_reference_refused(self):
        fix = list(evidence())
        fix[6]["dated_two_dividend_event_reference_parity_count"] = 1
        with self.assertRaisesRegex(ValueError, "dividend"):
            run(fix)

    def test_previously_accepted_reduction_sma_must_match_exact(self):
        fix = list(evidence())
        fix[4]["event_only_240_sma_stock_count"] = 1
        with self.assertRaisesRegex(ValueError, "reduction-only SMA report drifted"):
            run(fix)

    def test_missing_2021_bar_or_dividend_ex_day_fails_closed(self):
        fix = evidence()
        del fix[9]["2327"][date(2021, 12, 30)]
        with self.assertRaises(ValueError):
            run(fix)
        fix = evidence()
        del fix[10]["2603"][date(2022, 6, 29)]
        with self.assertRaises(ValueError):
            run(fix)

    def test_fake_halt_bar_or_future_day_is_never_included(self):
        fix = evidence()
        fix[10]["2603"][date(2022, 9, 7)] = Decimal("90")
        with self.assertRaises(ValueError):
            run(fix)
        fix = evidence()
        fix[10]["2327"][date(2023, 1, 3)] = Decimal("100")
        with self.assertRaises(ValueError):
            run(fix)

    def test_unverified_asof_timing_does_not_pass(self):
        fix = evidence()
        changed = dict(DIV_EVENTS["2603"], payout_scheduled=date(2022, 9, 30))
        with patch.dict(DIV_EVENTS, {"2603": changed}):
            with self.assertRaisesRegex(ValueError, "entitlement or settlement order"):
                run(fix)

    def test_pre_2022_event_backfill_does_not_create_stored_total_return(self):
        run_result = run(evidence())
        for s in (
            "raw_close", "calculated_sma240", "adjusted_close",
            "private_cash_adjustment_delta",
        ):
            self.assertNotIn(s, str(run_result).lower())
        self.assertFalse(run_result["historical_listing_membership_or_capture_vintage_certified"])
        self.assertFalse(run_result["adjustment_covers_all_historical_dividends"])

    def test_help_works_with_neon_uri_and_aes_key_removed(self):
        root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        for key in ("DATABASE_URL", "STOCK_ARCHIVE_KEY_HEX", "PYTHONPATH"):
            env.pop(key, None)
        r = subprocess.run(
            [sys.executable, "-m",
             "scripts.twse_2022_known_cash_events_sma240_readonly", "--help"],
            cwd=root, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--dividend-reference-report", r.stdout)
        self.assertIn("--reduction-sma-report", r.stdout)


if __name__ == "__main__":
    unittest.main()
