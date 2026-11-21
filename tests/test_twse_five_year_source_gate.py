"""Offline safety tests for strict five-year TWSE active-only source gate."""
from unittest import TestCase

from scripts import twse_five_year_source_gate as gate
from src import twse_dated_history as history


def evidence(**overrides):
    return {
        "database_bytes": 530_000_000,
        "active_twse": 1092,
        "verified_source_days": 137,
        "missing_weekdays": 1160,
        **overrides,
    }


class TWSEFiveYearSourceGateTests(TestCase):
    def test_active_source_and_capacity_are_all_required(self):
        self.assertTrue(gate.decide(evidence()))
        for changes in (
            {"database_bytes": 800_000_000},
            {"database_bytes": 745_000_000},
            {"active_twse": 699},
            {"verified_source_days": 99},
            {"missing_weekdays": 0},
        ):
            self.assertFalse(gate.decide(evidence(**changes)))
        self.assertTrue(gate.decide(evidence(database_bytes=610_377_728)))
        self.assertIn("official_current_listed", gate.STATE_SQL)
        self.assertIn("14 days", gate.STATE_SQL)
        self.assertIn("twse_history_day_progress", gate.STATE_SQL)
        self.assertIn("AT TIME ZONE 'Asia/Taipei'", gate.STATE_SQL)
        self.assertNotIn("DELETE FROM", gate.STATE_SQL.upper())
        self.assertNotIn("UPDATE public.daily_prices", gate.STATE_SQL)

    def test_official_current_allowlist_is_required_by_price_importer(self):
        self.assertIn("official_current_listed", history.ACTIVE_ALLOWED_SQL)
        self.assertIn("INNER JOIN", history.ACTIVE_ALLOWED_SQL)
        self.assertIn("m.market='twse'", history.ACTIVE_ALLOWED_SQL)
        self.assertIn("ON CONFLICT (market,stock_id,trade_date) DO NOTHING",
                      __import__("src.official_snapshot_ingest", fromlist=["INSERT_MISSING_SQL"]).INSERT_MISSING_SQL)

    def test_rolling_window_never_selects_pre_five_year_date(self):
        from datetime import date
        today = date(2026, 11, 22)
        selected = history.schedule_dates(
            today=today, already=set(), batch_days=8, lookback_days=1830)
        self.assertEqual(len(selected), 8)
        self.assertTrue(all(d >= date(2021, 11, 22) for d in selected))
        self.assertEqual(history.schedule_dates(
            today=today, already=set(), batch_days=8,
            lookback_days=1830)[0], date(2026,11,20))
