"""Fail-closed 241-day source budget/readonly provenance; historical dates frozen."""
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch
import json

from scripts import twse_2022_real_241_day_market_factor as m
from tests.test_twse_2022_shared_source_stream import synthetic_day, allowed_codes

CALENDAR = tuple(date.fromisoformat(x) for x in "2022-01-04 2022-01-05 2022-01-06 2022-01-07 2022-01-10 2022-01-11 2022-01-12 2022-01-13 2022-01-14 2022-01-17 2022-01-18 2022-01-19 2022-01-20 2022-01-21 2022-01-24 2022-01-25 2022-01-26 2022-02-07 2022-02-08 2022-02-09 2022-02-10 2022-02-11 2022-02-14 2022-02-15 2022-02-16 2022-02-17 2022-02-18 2022-02-21 2022-02-22 2022-02-23 2022-02-24 2022-02-25 2022-03-01 2022-03-02 2022-03-03 2022-03-04 2022-03-07 2022-03-08 2022-03-09 2022-03-10 2022-03-11 2022-03-14 2022-03-15 2022-03-16 2022-03-17 2022-03-18 2022-03-21 2022-03-22 2022-03-23 2022-03-24 2022-03-25 2022-03-28 2022-03-29 2022-03-30 2022-03-31 2022-04-01 2022-04-06 2022-04-07 2022-04-08 2022-04-11 2022-04-12 2022-04-13 2022-04-14 2022-04-15 2022-04-18 2022-04-19 2022-04-20 2022-04-21 2022-04-22 2022-04-25 2022-04-26 2022-04-27 2022-04-28 2022-04-29 2022-05-03 2022-05-04 2022-05-05 2022-05-06 2022-05-09 2022-05-10 2022-05-11 2022-05-12 2022-05-13 2022-05-16 2022-05-17 2022-05-18 2022-05-19 2022-05-20 2022-05-23 2022-05-24 2022-05-25 2022-05-26 2022-05-27 2022-05-30 2022-05-31 2022-06-01 2022-06-02 2022-06-06 2022-06-07 2022-06-08 2022-06-09 2022-06-10 2022-06-13 2022-06-14 2022-06-15 2022-06-16 2022-06-17 2022-06-20 2022-06-21 2022-06-22 2022-06-23 2022-06-24 2022-06-27 2022-06-28 2022-06-29 2022-06-30 2022-07-01 2022-07-04 2022-07-05 2022-07-06 2022-07-07 2022-07-08 2022-07-11 2022-07-12 2022-07-13 2022-07-14 2022-07-15 2022-07-18 2022-07-19 2022-07-20 2022-07-21 2022-07-22 2022-07-25 2022-07-26 2022-07-27 2022-07-28 2022-07-29 2022-08-01 2022-08-02 2022-08-03 2022-08-04 2022-08-05 2022-08-08 2022-08-09 2022-08-10 2022-08-11 2022-08-12 2022-08-15 2022-08-16 2022-08-17 2022-08-18 2022-08-19 2022-08-22 2022-08-23 2022-08-24 2022-08-25 2022-08-26 2022-08-29 2022-08-30 2022-08-31 2022-09-01 2022-09-02 2022-09-05 2022-09-06 2022-09-07 2022-09-08 2022-09-12 2022-09-13 2022-09-14 2022-09-15 2022-09-16 2022-09-19 2022-09-20 2022-09-21 2022-09-22 2022-09-23 2022-09-26 2022-09-27 2022-09-28 2022-09-29 2022-09-30 2022-10-03 2022-10-04 2022-10-05 2022-10-06 2022-10-07 2022-10-11 2022-10-12 2022-10-13 2022-10-14 2022-10-17 2022-10-18 2022-10-19 2022-10-20 2022-10-21 2022-10-24 2022-10-25 2022-10-26 2022-10-27 2022-10-28 2022-10-31 2022-11-01 2022-11-02 2022-11-03 2022-11-04 2022-11-07 2022-11-08 2022-11-09 2022-11-10 2022-11-11 2022-11-14 2022-11-15 2022-11-16 2022-11-17 2022-11-18 2022-11-21 2022-11-22 2022-11-23 2022-11-24 2022-11-25 2022-11-28 2022-11-29 2022-11-30 2022-12-01 2022-12-02 2022-12-05 2022-12-06 2022-12-07 2022-12-08 2022-12-09 2022-12-12 2022-12-13 2022-12-14 2022-12-15 2022-12-16 2022-12-19 2022-12-20 2022-12-21 2022-12-22 2022-12-23 2022-12-26".split())


def mock_conn(days=CALENDAR):
    c=MagicMock()
    c.__enter__.return_value=c
    cur=MagicMock()
    cur.__enter__.return_value=cur
    cur.fetchall.return_value=[(d,) for d in days]
    c.cursor.return_value=cur
    return c,cur


class Real241DaySourceSafetyTests(TestCase):
    def test_historical_exact_date_sha_blocks_missing_or_altered_sessions(self):
        self.assertEqual(len(CALENDAR), 241)
        self.assertEqual(m.verify_source_date_calendar(CALENDAR), CALENDAR)
        self.assertEqual(CALENDAR[0],date(2022,1,4))
        self.assertEqual(CALENDAR[-1],date(2022,12,26))
        for bad in (
            CALENDAR[:-1],
            CALENDAR[::-1],
            CALENDAR[:10]+(CALENDAR[9],)+CALENDAR[11:],
            CALENDAR[:10]+(date(2022,1,15),)+CALENDAR[11:],
            CALENDAR[:10]+(date(2022,1,18),)+CALENDAR[11:],
            CALENDAR+(date(2022,12,27),),
        ):
            with self.subTest(bad_size=len(bad)), self.assertRaises(ValueError):
                m.verify_source_date_calendar(bad)

    def test_241_real_request_preflight_and_causal_factor_flags(self):
        c,cur=mock_conn()
        seen=[]
        pauses=[]
        def get(day):
            seen.append(day)
            return synthetic_day(day)
        with (
            TemporaryDirectory() as td,
            patch("psycopg.connect",return_value=c) as conn,
            patch.object(m,"load_current_twse_allowed",return_value=allowed_codes()),
            patch.object(m,"_processed_days",return_value=set()),
        ):
            out=Path(td)/"aggregate.json"
            result=m.execute("postgresql://synthetic",fetcher=get,
                             sleeper=pauses.append,output=out)
            self.assertEqual(seen,list(CALENDAR))
            self.assertEqual(len(pauses),240)
            self.assertEqual(set(pauses),{4.0})
            self.assertEqual(result["actual_official_http_requests"],241)
            self.assertEqual(result["maximum_official_http_requests"],241)
            self.assertEqual(result["authentic_source_days_evaluated"],241)
            self.assertTrue(result["real_2022_241_session_source_replayed"])
            self.assertFalse(result["synthetic_full_241_session_stress_verified"])
            self.assertEqual(result["stock_ma240_passes"],650)
            self.assertEqual(result["technical_smc_240_prefix_checks"],5)
            self.assertTrue(result["real_current_survivor_2022_ma240_source_feasibility"])
            self.assertFalse(result["independent_forward_cost_stressed_model_alpha_validated"])
            self.assertFalse(result["current_issuer_survivorship_unbiased"])
            self.assertFalse(result["model_retraining_and_live_signals_approved"])
            self.assertEqual(result["neon_rows_written"],0)
            self.assertEqual(result["line_messages_sent"],0)
            self.assertEqual(json.loads(out.read_text()),result)
            self.assertNotIn('"stock_id"',out.read_text())
            self.assertNotIn('"close"',out.read_text())
            self.assertIn("default_transaction_read_only=on",
                          conn.call_args.kwargs["options"])
            cur.execute.assert_called_once_with(
                m.REFERENCE_CALENDAR_SQL, (m.EARLIEST,m.LATEST,242))

    def test_source_failure_stops_not_retries_and_produces_no_success_output(self):
        c,_=mock_conn()
        seen=[]
        with (
            TemporaryDirectory() as td,
            patch("psycopg.connect",return_value=c),
            patch.object(m,"load_current_twse_allowed",return_value=allowed_codes()),
            patch.object(m,"_processed_days",return_value=set()),
        ):
            target=Path(td)/"no-success.json"
            def fail(day):
                seen.append(day)
                return None if day==CALENDAR[4] else synthetic_day(day)
            with self.assertRaises(ValueError):
                m.execute("fake",fetcher=fail,sleeper=lambda _:None,output=target)
            self.assertEqual(seen,list(CALENDAR[:5]))
            self.assertFalse(target.exists())

    def test_missing_calendar_existing_receipt_or_excluded_roster_never_gets(self):
        for variant in ("calendar","receipt","roster"):
            c,_=mock_conn(CALENDAR[:-1] if variant=="calendar" else CALENDAR)
            seen=[]
            with (
                patch("psycopg.connect",return_value=c),
                patch.object(m,"load_current_twse_allowed",
                             return_value=allowed_codes()|{("twse","1589")}
                             if variant=="roster" else allowed_codes()),
                patch.object(m,"_processed_days",
                             return_value={CALENDAR[5]} if variant=="receipt"
                             else set()),
            ):
                with self.subTest(variant=variant),self.assertRaises(ValueError):
                    m.execute("fake",fetcher=lambda day:seen.append(day))
            self.assertEqual(seen,[])
