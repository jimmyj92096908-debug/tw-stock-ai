"""Fixed 48 real 2022 date source replay: failure and request safety tests."""
from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

from scripts import twse_2022_48day_real_source_pilot as p
from tests.test_twse_2022_shared_source_stream import (
    allowed_codes, synthetic_day,
)

DATE_TEXT = """2022-01-04 2022-01-05 2022-01-06 2022-01-07 2022-01-10
2022-01-11 2022-01-12 2022-01-13 2022-01-14 2022-01-17
2022-01-18 2022-01-19 2022-01-20 2022-01-21 2022-01-24
2022-01-25 2022-01-26 2022-02-07 2022-02-08 2022-02-09
2022-02-10 2022-02-11 2022-02-14 2022-02-15 2022-02-16
2022-02-17 2022-02-18 2022-02-21 2022-02-22 2022-02-23
2022-02-24 2022-02-25 2022-03-01 2022-03-02 2022-03-03
2022-03-04 2022-03-07 2022-03-08 2022-03-09 2022-03-10
2022-03-11 2022-03-14 2022-03-15 2022-03-16 2022-03-17
2022-03-18 2022-03-21 2022-03-22"""
DATES = tuple(date.fromisoformat(x) for x in DATE_TEXT.split())


def fake_connection(days=DATES):
    conn=MagicMock()
    conn.__enter__.return_value=conn
    cur=MagicMock()
    cur.__enter__.return_value=cur
    cur.fetchall.return_value=[(x,) for x in days]
    conn.cursor.return_value=cur
    return conn,cur


class FortyEightDayRealSourceTests(TestCase):
    def test_frozen_actual_exchange_calendar_holidays_and_budget(self):
        self.assertEqual(len(DATES),p.PILOT_DAYS)
        self.assertEqual(p.validate_48_date_calendar(DATES),DATES)
        self.assertIn(date(2022,2,7),DATES)
        self.assertNotIn(date(2022,2,28),DATES)
        self.assertEqual(p.PAUSE_SECONDS,4.0)
        for invalid in (
            DATES[:-1],
            DATES + (date(2022,3,23),),
            DATES[::-1],
            DATES[:20]+(date(2022,1,31),)+DATES[21:],
            DATES[:20]+(DATES[19],)+DATES[21:],
            DATES[1:]+(date(2022,3,23),),
        ):
            with self.subTest(bad=invalid[:2]),self.assertRaises(ValueError):
                p.validate_48_date_calendar(invalid)

    def test_one_readonly_roster_query_and_exactly_forty_eight_bounded_gets(self):
        conn,cur=fake_connection()
        calls=[]
        pauses=[]
        with (
            TemporaryDirectory() as folder,
            patch("psycopg.connect",return_value=conn) as connected,
            patch.object(p,"load_current_twse_allowed",return_value=allowed_codes()),
            patch.object(p,"_processed_days",return_value=set()),
        ):
            path=Path(folder)/"aggregate-only.json"
            report=p.execute(
                "postgresql://fake",
                fetcher=lambda d:(calls.append(d) or synthetic_day(d)),
                sleeper=pauses.append,output=path,
            )
            self.assertEqual(calls,list(DATES))
            self.assertEqual(len(pauses),47)
            self.assertEqual(set(pauses),{4.0})
            self.assertEqual(report["actual_official_http_requests"],48)
            self.assertEqual(report["maximum_official_http_requests"],48)
            self.assertEqual(report["authentic_source_days_evaluated"],48)
            self.assertEqual(report["complete_common_stock_cohort"],650)
            self.assertEqual(report["stock_ma240_passes"],0)
            self.assertTrue(report["no_240_session_real_market_factor_claim"])
            self.assertEqual(report["raw_price_or_factor_rows_persisted"],0)
            self.assertEqual(report["neon_rows_written"],0)
            self.assertEqual(report["line_messages_sent"],0)
            self.assertFalse(report["live_trading_approved"])
            content=path.read_text()
            self.assertEqual(json.loads(content),report)
            self.assertNotIn('"stock_id"',content)
            self.assertNotIn('"close"',content)
            self.assertNotIn('"2330"',content)
            cur.execute.assert_called_once_with(
                p.REFERENCE_CALENDAR_SQL,
                (p.FIRST_DAY,p.LAST_DAY,p.PILOT_DAYS+1),
            )
            self.assertEqual(conn.execute.call_args_list[0].args[0],
                             "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            self.assertIn("default_transaction_read_only=on",
                          connected.call_args.kwargs["options"])

    def test_preflight_import_receipt_roster_and_calendar_refuse_before_http(self):
        for problem in ("receipt","roster","calendar"):
            seen=[]
            conn,cur=fake_connection(
                DATES[:-1] if problem=="calendar" else DATES
            )
            with (
                patch("psycopg.connect",return_value=conn),
                patch.object(p,"load_current_twse_allowed",
                             return_value=({("twse","1589")}|allowed_codes())
                             if problem=="roster" else allowed_codes()),
                patch.object(p,"_processed_days",
                             return_value={DATES[4]} if problem=="receipt"
                             else set()),
            ):
                with self.subTest(problem=problem),self.assertRaises(ValueError):
                    p.execute("fake",fetcher=lambda d:seen.append(d))
            self.assertEqual(seen,[])

    def test_one_untrusted_official_day_fails_closed_not_retried(self):
        seen=[]
        conn,cur=fake_connection()
        def broken(day):
            seen.append(day)
            if day==DATES[3]:
                return None
            return synthetic_day(day)
        with (
            TemporaryDirectory() as td,
            patch("psycopg.connect",return_value=conn),
            patch.object(p,"load_current_twse_allowed",return_value=allowed_codes()),
            patch.object(p,"_processed_days",return_value=set()),
        ):
            output=Path(td)/"never-created.json"
            with self.assertRaises(ValueError):
                p.execute("fake",fetcher=broken,sleeper=lambda _:None,output=output)
            self.assertEqual(seen,list(DATES[:4]))
            self.assertFalse(output.exists())
