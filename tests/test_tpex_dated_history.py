"""Offline safety tests for bounded TPEx historical whole-market importer."""
from datetime import date
from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch
from contextlib import nullcontext

from src import tpex_dated_history as history


DAY = date(2026, 11, 18)


class FakeCursor:
    def __init__(self, records=()):
        self.records = list(records)
        self.calls = []
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def execute(self, sql, params=()):
        self.calls.append((sql, params))
    def fetchall(self):
        return self.records


class FakeConnection:
    def __init__(self, records=()):
        self.cursor_obj = FakeCursor(records)
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def cursor(self):
        return self.cursor_obj


class TPExDatedHistoryTests(TestCase):
    def test_choose_only_sparse_date_anchored_weekdays(self):
        today = date(2026, 11, 21)
        fake = FakeConnection([(date(2026,11,20), 850),
                               (date(2026,11,19), 800),
                               (date(2026,11,18), 57),
                               (date(2026,11,17), 58),
                               (date(2026,11,16), 60)])
        days = history.choose_days(fake, today=today, universe=900,
                                   batch_days=2, lookback=7)
        self.assertEqual([d["trade_date"] for d in days],
                         [date(2026,11,18), date(2026,11,17)])

    def test_same_day_close_cross_check_passes_and_fails_closed(self):
        existing = [("1000", Decimal("100")), ("1001", Decimal("101"))]
        bars = [{"market":"tpex", "stock_id":str(1000+i),
                 "trade_date":DAY, "close":Decimal(100+i)}
                for i in range(12)]
        fake = FakeConnection([(str(1000+i), Decimal(100+i)) for i in range(12)])
        proof = history.verify_source_date(fake, DAY, bars)
        self.assertEqual(proof["matched"], 12)
        self.assertEqual(proof["mismatched"], 0)

        fake_bad = FakeConnection([(str(1000+i), Decimal(200+i)) for i in range(12)])
        with self.assertRaisesRegex(ValueError, "source date/close mismatch"):
            history.verify_source_date(fake_bad, DAY, bars)
        few = FakeConnection(existing)
        with self.assertRaisesRegex(ValueError, "Insufficient"):
            history.verify_source_date(few, DAY, bars)

    def test_default_dry_run_never_fetches_or_writes(self):
        fake = FakeConnection()
        with (
            patch.object(history.psycopg, "connect", return_value=fake),
            patch.object(history, "load_allowed", return_value={("tpex",str(x)) for x in range(1000,1900)}),
            patch.object(history, "choose_days", return_value=[{"trade_date":DAY,"old_valid_rows":57}]),
            patch.object(history, "fetch_day", side_effect=AssertionError("No HTTP")) as fetch,
            patch.object(history, "write_missing", side_effect=AssertionError("No writes")) as write,
        ):
            result = history.run("postgresql://fake", apply=False)
        self.assertEqual(result[0]["status"], "dry-run")
        fetch.assert_not_called()
        write.assert_not_called()

    def test_apply_requires_environment_gate_before_connect(self):
        with patch.dict(history.os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "write gate"):
                history.run("postgresql://fake", apply=True)
        for batch in (0, 5, 200):
            with self.assertRaisesRegex(ValueError, "bounds"):
                history.run("postgresql://fake", batch_days=batch)

    def test_source_verify_precedes_any_insert(self):
        fake = FakeConnection()
        day = {"trade_date": DAY, "old_valid_rows":57}
        stocks = {("tpex",str(x)) for x in range(1000,1900)}
        bars = [{"market":"tpex","stock_id":str(x),"trade_date":DAY}
                for x in range(1000,1900)]
        with (
            patch.dict(history.os.environ, {"STOCK_TPEX_DATED_HISTORY_WRITE_ENABLED":"yes"}),
            patch.object(history.psycopg, "connect", return_value=fake),
            patch.object(history, "load_allowed", return_value=stocks),
            patch.object(history, "choose_days", return_value=[day]),
            patch.object(history, "fetch_day", return_value={"bars":bars}),
            patch.object(history, "select_candidates", return_value=bars),
            patch.object(history, "verify_source_date", side_effect=ValueError("untrusted day")),
            patch.object(history, "write_missing") as write,
        ):
            with self.assertRaisesRegex(ValueError, "untrusted day"):
                history.run("postgresql://fake", apply=True, pause_seconds=0)
            write.assert_not_called()

    def test_source_verified_insert_is_bounded_and_counted(self):
        fake = FakeConnection()
        day = {"trade_date": DAY, "old_valid_rows":57}
        stocks = {("tpex",str(x)) for x in range(1000,1900)}
        bars = [{"market":"tpex","stock_id":str(x),"trade_date":DAY}
                for x in range(1000,1900)]
        with (
            patch.dict(history.os.environ, {"STOCK_TPEX_DATED_HISTORY_WRITE_ENABLED":"yes"}),
            patch.object(history.psycopg, "connect", return_value=fake),
            patch.object(history, "load_allowed", return_value=stocks),
            patch.object(history, "choose_days", return_value=[day]),
            patch.object(history, "fetch_day", return_value={"bars":bars}),
            patch.object(history, "select_candidates", return_value=bars),
            patch.object(history, "verify_source_date", return_value={"compared":57,"matched":57,"mismatched":0}),
            patch.object(history, "write_missing", return_value=800) as write,
        ):
            result = history.run("postgresql://fake", apply=True, pause_seconds=0)
        self.assertEqual(result[0]["inserted"], 800)
        self.assertEqual(result[0]["status"], "imported")
        self.assertEqual(write.call_count, 1)
