"""Offline tests: historical chip backfill never touches Neon or official APIs."""
import os
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from src import chip_history_backfill as backfill


class HistoryBackfillTests(unittest.TestCase):
    def test_preview_is_default_and_never_calls_external_fetch(self):
        conn = MagicMock()
        cursor = conn.__enter__.return_value.cursor.__enter__.return_value
        cursor.fetchall.return_value = [
            {"trade_date": date(2026, 11, 20), "has_institutional": False, "has_margin": True},
            {"trade_date": date(2026, 11, 19), "has_institutional": True, "has_margin": False},
            {"trade_date": date(2026, 11, 18), "has_institutional": False, "has_margin": False},
        ]
        with patch("src.chip_history_backfill.psycopg.connect", return_value=conn), \
             patch("src.chip_history_backfill.fetch_missing_twse") as fetch, \
             patch("src.chip_history_backfill.apply_missing") as write:
            result = backfill.run("postgresql://placeholder.invalid/chip", days=25)
        self.assertEqual(result["actual_price_sessions"], 3)
        self.assertEqual(result["missing_institutional"], 2)
        self.assertEqual(result["missing_margin"], 2)
        self.assertEqual(result["mode"], "preview")
        query, params = cursor.execute.call_args.args
        self.assertIn("FROM public.daily_prices", query)
        self.assertEqual(params, ("2330", "2330", "2330", 25))
        fetch.assert_not_called()
        write.assert_not_called()

    def test_apply_requires_explicit_second_gate_before_connecting(self):
        with patch.dict(os.environ, {"CHIP_HISTORY_WRITE_ENABLED": "no"}), \
             patch("src.chip_history_backfill.psycopg.connect") as connect:
            with self.assertRaises(PermissionError):
                backfill.run("postgresql://placeholder.invalid/chip", apply=True)
            connect.assert_not_called()

    def test_rejects_tpex_and_oversize_bounded_window(self):
        for stock_id, count in (("8937", 25), ("2330", 0), ("2330", 31)):
            with self.assertRaises(ValueError):
                backfill.validate_options(stock_id, count, False)

    def test_preflight_rejects_wrong_date_before_any_insert(self):
        day = date(2026, 11, 18)
        response = MagicMock()
        response.json.return_value = {"stat": "OK", "date": "20261119",
                                     "fields": [], "data": []}
        session = MagicMock()
        session.get.return_value = response
        with self.assertRaisesRegex(RuntimeError, "date not proven"):
            backfill.fetch_missing_twse(
                "2330", [{"date": day, "institutional_missing": True,
                          "margin_missing": False}], session=session)
        self.assertEqual(session.get.call_count, 1)

    def test_preflight_rejects_absent_tracked_stock_or_misdated_row(self):
        day = date(2026, 11, 18)
        with self.assertRaisesRegex(RuntimeError, "exactly one row"):
            backfill._official_record("twse", "2330", day, [])
        with self.assertRaisesRegex(RuntimeError, "differs"):
            backfill._official_record("twse", "2330", day, [
                {"market": "twse", "stock_id": "2330", "trade_date": "2026-11-19"}
            ])

    def test_official_date_and_target_are_preserved(self):
        day = date(2026, 11, 18)
        session = MagicMock()
        session.get.return_value.json.side_effect = [
            {"stat": "OK", "date": "20261118", "fields": [], "data": []},
            {"stat": "OK", "date": "20261118", "tables": []},
        ]
        inst = {"market": "twse", "stock_id": "2330", "trade_date": "2026-11-18",
                "total_net": 500}
        marg = {"market": "twse", "stock_id": "2330", "trade_date": "2026-11-18",
                "margin_balance": 300}
        with patch("src.chip_history_backfill.institutional_data.parse_twse",
                   return_value=[inst]), \
             patch("src.chip_history_backfill.margin_data.parse_twse",
                   return_value=[marg]):
            inst_rows, margin_rows = backfill.fetch_missing_twse(
                "2330", [{"date": day, "institutional_missing": True,
                          "margin_missing": True}], session=session)
        self.assertEqual(inst_rows, [inst])
        self.assertEqual(margin_rows, [marg])
        for call in session.get.call_args_list:
            self.assertEqual(call.kwargs["params"]["date"], "20261118")

    def test_insert_only_contract(self):
        self.assertIn("ON CONFLICT (market,stock_id,trade_date) DO NOTHING",
                      backfill.INSERT_INSTITUTIONAL)
        self.assertIn("ON CONFLICT (market,stock_id,trade_date) DO NOTHING",
                      backfill.INSERT_MARGIN)
        self.assertNotIn("DO UPDATE", backfill.INSERT_INSTITUTIONAL)
        self.assertNotIn("DO UPDATE", backfill.INSERT_MARGIN)

    def test_apply_counts_only_inserted_rows(self):
        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.rowcount = 1
        with patch.dict(os.environ, {"CHIP_HISTORY_WRITE_ENABLED": "yes"}):
            counts = backfill.apply_missing(
                conn, [{"market": "twse", "stock_id": "2330", "trade_date": "2026-11-20"}],
                [{"market": "twse", "stock_id": "2330", "trade_date": "2026-11-20"}]
            )
        self.assertEqual(counts, (1, 1))
        self.assertEqual(cursor.execute.call_count, 2)


if __name__ == "__main__":
    unittest.main()
