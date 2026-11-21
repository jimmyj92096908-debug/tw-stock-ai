"""No-network unit tests of bounded dated official TWSE historical snapshots."""
import os
import unittest
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from src import twse_dated_history as history
from tests.test_official_market_feed import FakeSession, twse_payload


class FakeCursor:
    def __init__(self):
        self.statements=[]
        self.response=None

    def __enter__(self):
        return self

    def __exit__(self,*_):
        return False

    def execute(self,sql,params=None):
        self.statements.append((sql,params))
        self.response=sql

    def fetchone(self):
        return (None,)

    def fetchall(self):
        return []


class Transaction:
    def __enter__(self):
        return self
    def __exit__(self,*_):
        return False


class FakeConnection:
    def __init__(self):
        self.cur=FakeCursor()
    def __enter__(self):
        return self
    def __exit__(self,*_):
        return False
    def cursor(self):
        return self.cur
    def transaction(self):
        return Transaction()


class DateHistoryTests(unittest.TestCase):
    def test_bounded_weekdays_and_progress_advance(self):
        today=date(2026,11,20) # Friday
        selected=history.schedule_dates(today=today,already=set(),batch_days=6)
        self.assertEqual(selected[0],date(2026,11,19))
        self.assertEqual(len(selected),6)
        self.assertTrue(all(d.weekday()<5 and d<today for d in selected))
        next_six=history.schedule_dates(today=today,already=set(selected),batch_days=6)
        self.assertEqual(len(set(selected+next_six)),12)
        for limit in (0,9,-1,100):
            with self.assertRaisesRegex(ValueError,"batch_days"):
                history.schedule_dates(today=today,already=set(),batch_days=limit)
        for horizon in (0,6,1831,10000):
            with self.assertRaisesRegex(ValueError,"lookback_days"):
                history.schedule_dates(today=today,already=set(),lookback_days=horizon)
        self.assertEqual(
            history.schedule_dates(today=today,already=set(selected),
                                   batch_days=6,lookback_days=7),
            [],
        )

    def test_source_parsing_rejects_wrong_exchange_date(self):
        good=FakeSession(twse_payload())
        bars=history.fetch_official_day(date(2026,11,19),session=good)
        self.assertEqual(len(bars),1)
        self.assertEqual(bars[0]["stock_id"],"2330")
        self.assertEqual(good.calls[0][1]["params"]["date"],"20261119")
        self.assertEqual(good.calls[0][1]["params"]["type"],"ALLBUT0999")
        wrong=FakeSession(twse_payload(title="115年11月18日 每日收盤行情"))
        with self.assertRaisesRegex(ValueError,"different trade date"):
            history.fetch_official_day(date(2026,11,19),session=wrong)
        holiday=FakeSession({"stat":"很抱歉，沒有符合條件的資料!"})
        self.assertIsNone(history.fetch_official_day(date(2026,11,19),session=holiday))
        server_error=FakeSession({"stat":"資料維護中"})
        with self.assertRaisesRegex(ValueError,"recognized"):
            history.fetch_official_day(date(2026,11,19),session=server_error)
        with self.assertRaisesRegex(ValueError,"Unexpected"):
            history.fetch_official_day(date(2026,11,19),session=FakeSession([]))

    def test_dry_run_has_no_schema_or_price_writes_and_uses_official_coverage(self):
        fake=FakeConnection()
        prices=[{
            "market":"twse","stock_id":str(i),"trade_date":date(2026,11,19),
            "close":Decimal("100")
        } for i in range(1000,1800)]
        allowed={("twse",str(i)) for i in range(1000,1800)}
        with (
            patch.object(history.psycopg,"connect",return_value=fake),
            patch.object(history,"load_current_twse_allowed",return_value=allowed),
            patch.object(history,"fetch_official_day",return_value=prices) as source,
            patch.object(history,"write_missing",side_effect=AssertionError("wrote in dry run")),
            patch.object(history,"_record_day",side_effect=AssertionError("wrote progress")),
        ):
            results=history.run("postgresql://fake",today=date(2026,11,20),
                                batch_days=2,lookback_days=7,pause_seconds=0)
        self.assertEqual(len(results),2)
        self.assertTrue(all(x["status"]=="dry-run" for x in results))
        self.assertEqual([x["qualified"] for x in results],[800,800])
        self.assertEqual(source.call_count,2)
        self.assertEqual(len(fake.cur.statements),1)
        self.assertNotIn("CREATE TABLE",fake.cur.statements[0][0])

    def test_requires_explicit_apply_gate_even_before_database_connection(self):
        with patch.dict(os.environ,{"STOCK_TWSE_HISTORY_WRITE_ENABLED":""}):
            with self.assertRaisesRegex(ValueError,"opt-in"):
                history.run("postgresql://fake",apply=True)
        with self.assertRaisesRegex(ValueError,"DATABASE_URL"):
            history.run("")
        with self.assertRaisesRegex(ValueError,"batch_days"):
            history.run("postgresql://fake",batch_days=9)
        self.assertIn("ON CONFLICT (trade_date) DO UPDATE",history.UPSERT_PROGRESS)
        self.assertIn("trade_date DATE PRIMARY KEY",history.CREATE_PROGRESS)

    def test_successful_apply_marks_only_validated_days(self):
        fake=FakeConnection()
        allowed={("twse",str(i)) for i in range(1000,1800)}
        prices=[{"market":"twse","stock_id":str(i),"trade_date":date(2026,11,19),
                 "close":Decimal("100")} for i in range(1000,1800)]
        calls=[]
        with (
            patch.dict(os.environ,{"STOCK_TWSE_HISTORY_WRITE_ENABLED":"yes"}),
            patch.object(history.psycopg,"connect",return_value=fake),
            patch.object(history,"load_current_twse_allowed",return_value=allowed),
            patch.object(history,"fetch_official_day",side_effect=[prices,None]),
            patch.object(history,"write_missing",return_value=799) as write,
            patch.object(history,"_record_day",side_effect=lambda *x: calls.append(x)),
        ):
            results=history.run("postgresql://fake",apply=True,
                                today=date(2026,11,20),batch_days=2,
                                lookback_days=7,pause_seconds=0)
        self.assertEqual([x["status"] for x in results],["imported","closed"])
        self.assertEqual([x["inserted"] for x in results],[799,0])
        write.assert_called_once()
        self.assertEqual(calls[0][2:],("imported",800,799))
        self.assertEqual(calls[1][2:],("closed",0,0))
        self.assertTrue(any("CREATE TABLE" in s for s,_ in fake.cur.statements))

    def test_no_partial_or_stale_source_coverage_is_imported(self):
        fake=FakeConnection()
        allowed={("twse",str(i)) for i in range(1000,2000)}
        limited=[{"market":"twse","stock_id":str(i),"trade_date":date(2026,11,19)}
                 for i in range(1000,1050)]
        with (
            patch.object(history.psycopg,"connect",return_value=fake),
            patch.object(history,"load_current_twse_allowed",return_value=allowed),
            patch.object(history,"fetch_official_day",return_value=limited),
            patch.object(history,"write_missing",side_effect=AssertionError("partial import")),
        ):
            with self.assertRaisesRegex(ValueError,"covered only"):
                history.run("postgresql://fake",today=date(2026,11,20),
                            batch_days=1,pause_seconds=0)


if __name__=="__main__":
    unittest.main()
