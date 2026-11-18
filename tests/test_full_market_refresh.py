from datetime import date

from full_market_refresh import choose_start_month, previous_month


def test_previous_month_crosses_year_boundary():
    assert previous_month(date(2026, 1, 15)) == date(2025, 12, 1)


def test_new_stock_starts_from_previous_month():
    assert choose_start_month(None, date(2026, 11, 18)) == date(2026, 10, 1)


def test_latest_month_is_refetched():
    assert choose_start_month(date(2026, 11, 10), date(2026, 11, 18)) == date(2026, 11, 1)


def test_old_latest_date_does_not_trigger_unbounded_backfill():
    assert choose_start_month(date(2021, 3, 12), date(2026, 11, 18)) == date(2026, 10, 1)
