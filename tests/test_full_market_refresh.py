from datetime import date

from full_market_refresh import (choose_start_month, previous_month, shift_month,
                                 plan_download_windows, classify_price_refresh,
                                 refresh_one, main)


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


class NoPriceHistoryResilienceTests(unittest.TestCase):
    """Unit tests do not use production DB or external quote endpoints."""

    def test_empty_history_is_not_a_successful_refresh(self):
        self.assertEqual(classify_price_refresh(0, None), "no_data")
        self.assertEqual(classify_price_refresh(0, date(2026, 11, 20)), "usable")
        self.assertEqual(classify_price_refresh(12, None), "invalid_import")
        self.assertEqual(classify_price_refresh(12, date(2026, 11, 20)), "usable")
        with self.assertRaises(ValueError):
            classify_price_refresh(-1, None)

    def test_refresh_empty_csv_marks_failed_and_skips_indicators(self):
        from unittest.mock import MagicMock, patch
        stock = {
            "market": "twse", "stock_id": "1589",
            "latest_trade_date": None, "earliest_trade_date": None,
        }
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value.fetchone.return_value = {"latest": None}
        with patch("full_market_refresh.market_data.download_range", return_value=0), \
             patch("pathlib.Path.exists", return_value=True), \
             patch("db_storage.upsert_csv"), \
             patch("full_market_refresh.record_attempt") as attempt:
            self.assertFalse(refresh_one(conn, stock, date(2026, 11, 20)))
        attempt.assert_called_once()
        self.assertEqual(attempt.call_args.args[3:6], ("failed", 0, None))
        self.assertIn("無有效價格資料", attempt.call_args.args[6])

    def test_reviewed_override_windows_are_used_without_changing_default_rotation(self):
        from unittest.mock import MagicMock, patch
        stock={
            "market":"twse","stock_id":"7867",
            "earliest_trade_date":date(2026,10,30),
            "latest_trade_date":date(2026,11,20)
        }
        window=[(date(2026,7,1),date(2026,11,1))]
        fake=MagicMock()
        fake.cursor.return_value.__enter__.return_value.fetchone.return_value={
            "latest":date(2026,11,20)
        }
        with patch("full_market_refresh.market_data.download_range",return_value=15) as fetch, \\
             patch("pathlib.Path.exists",return_value=True), \\
             patch("db_storage.upsert_csv"), \\
             patch("full_market_refresh.record_attempt") as attempt:
            self.assertTrue(refresh_one(fake,stock,date(2026,11,21),windows=window))
        fetch.assert_called_once_with("7867",2026,2026,7,11)
        attempt.assert_called_once()
        self.assertEqual(attempt.call_args.args[3],"success")

    def test_downloaded_but_not_imported_is_real_failure(self):
        from unittest.mock import MagicMock, patch
        stock = {
            "market": "twse", "stock_id": "1589",
            "latest_trade_date": None, "earliest_trade_date": None,
        }
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value.fetchone.return_value = {"latest": None}
        with patch("full_market_refresh.market_data.download_range", return_value=12), \
             patch("pathlib.Path.exists", return_value=True), \
             patch("db_storage.upsert_csv"), \
             patch("full_market_refresh.record_attempt") as attempt:
            with self.assertRaisesRegex(RuntimeError, "下載有資料但未成功寫入"):
                refresh_one(conn, stock, date(2026, 11, 20))
        attempt.assert_called_once()
        self.assertEqual(attempt.call_args.args[3], "failed")

    def test_main_skips_indicator_calls_for_unavailable_stock(self):
        from unittest.mock import MagicMock, patch
        stock = {"market": "twse", "stock_id": "1589"}
        conn_context = MagicMock()
        with patch.dict("os.environ", {"DATABASE_URL": "postgresql://invalid.local/test",
                                       "BATCH_SIZE": "1"}), \
             patch("full_market_refresh.stock_list.build_stock_list", return_value=[stock]), \
             patch("full_market_refresh.psycopg.connect", return_value=conn_context), \
             patch("full_market_refresh.upsert_universe"), \
             patch("full_market_refresh.select_batch", side_effect=[[stock], []]), \
             patch("full_market_refresh.refresh_one", return_value=False) as update, \
             patch("full_market_refresh.build_adjusted_stock") as adjusted, \
             patch("full_market_refresh.calculate_technical_stock") as technical, \
             patch("full_market_refresh.calculate_smc_stock") as smc:
            self.assertIsNone(main())
        update.assert_called_once()
        adjusted.assert_not_called()
        technical.assert_not_called()
        smc.assert_not_called()
