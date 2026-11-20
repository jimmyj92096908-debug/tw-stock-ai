from datetime import date

from full_market_refresh import choose_start_month, previous_month, shift_month, plan_download_windows


def test_previous_month_crosses_year_boundary():
    assert previous_month(date(2026, 1, 15)) == date(2025, 12, 1)


def test_new_stock_starts_five_years_back_in_same_month():
    assert choose_start_month(None, date(2026, 11, 18)) == date(2021, 11, 1)


def test_latest_month_is_refetched():
    assert choose_start_month(date(2026, 11, 10), date(2026, 11, 18)) == date(2026, 11, 1)


def test_old_latest_date_does_not_trigger_unbounded_backfill():
    assert choose_start_month(date(2021, 3, 12), date(2026, 11, 18)) == date(2026, 10, 1)


import unittest


class BoundedHistoryWindowsTests(unittest.TestCase):
    def setUp(self):
        self.today=date(2026,11,20)

    def test_daily_snapshot_does_not_block_older_history(self):
        stock={
            "earliest_trade_date":date(2026,11,19),
            "latest_trade_date":date(2026,11,19),
        }
        self.assertEqual(plan_download_windows(stock,self.today),[
            (date(2026,8,1),date(2026,10,1)),
            (date(2026,11,1),date(2026,11,1)),
        ])

    def test_thin_previous_month_refreshes_history_and_recent(self):
        stock={
            "earliest_trade_date":date(2026,10,30),
            "latest_trade_date":date(2026,11,19),
        }
        self.assertEqual(plan_download_windows(stock,self.today),[
            (date(2026,7,1),date(2026,9,1)),
            (date(2026,11,1),date(2026,11,1)),
        ])

    def test_stock_without_any_bar_has_bounded_initial_window(self):
        self.assertEqual(plan_download_windows({
            "earliest_trade_date":None,"latest_trade_date":None
        },self.today),[(date(2026,9,1),date(2026,11,1))])

    def test_existing_five_year_history_just_refreshes_recent_month(self):
        stock={
            "earliest_trade_date":date(2021,10,29),
            "latest_trade_date":date(2026,11,19),
        }
        self.assertEqual(plan_download_windows(stock,self.today),[
            (date(2026,11,1),date(2026,11,1))
        ])

    def test_late_quote_refreshes_previous_month_also(self):
        stock={
            "earliest_trade_date":date(2020,1,2),
            "latest_trade_date":date(2026,10,30),
        }
        self.assertEqual(plan_download_windows(stock,self.today),[
            (date(2026,10,1),date(2026,11,1))
        ])

    def test_limits_archive_window_and_calendar_year_boundary(self):
        self.assertEqual(shift_month(date(2026,1,1),-1),date(2025,12,1))
        self.assertEqual(shift_month(date(2026,12,1),1),date(2027,1,1))
        with self.assertRaisesRegex(ValueError,"archive_months"):
            plan_download_windows({},self.today,archive_months=60)
