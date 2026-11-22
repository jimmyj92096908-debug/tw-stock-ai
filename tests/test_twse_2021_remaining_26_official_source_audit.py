"""Offline 26-day 2021 TWSE official source stress and read-only safety gates."""
from datetime import date
from decimal import Decimal
from unittest import TestCase
from unittest.mock import MagicMock, patch

from scripts import twse_2021_remaining_26_official_source_audit as m
from tests.test_twse_stateless_2022_source_probe import rows


def daily(day, *, limited=False, source="TWSE_MI_INDEX_ALLBUT0999"):
    items=rows(day,number=200 if limited else 720)
    items.append({**items[0],"stock_id":"2330"})
    if source!="TWSE_MI_INDEX_ALLBUT0999":
        items[0]["source"]=source
    return items


class Whole2021SourcePilotTests(TestCase):
    def setUp(self):
        self.roster={("twse",r["stock_id"]) for r in daily(m.ALL_DAYS[0])}
        self.anchors={d:Decimal("100.2500") for d in m.ALL_DAYS}

    def test_all_26_real_day_shaped_sources_validate_without_storage(self):
        fetches,pauses=[],[]
        def get(day):
            fetches.append(day)
            return daily(day)
        report=m.verify_source_batches(m.BATCHES,self.roster,self.anchors,
            fetcher=get,sleeper=pauses.append)
        self.assertEqual(len(fetches),26)
        self.assertEqual(fetches,list(m.ALL_DAYS))
        self.assertEqual(pauses,[4.0]*25)
        self.assertEqual(report["date_batches_bounded_to_max_eight"],[6,8,8,4])
        self.assertEqual(report["total_validated_official_bars"],26*721)
        self.assertEqual(report["validated_original_2330_closes"],26)
        self.assertEqual(report["existing_neon_raw_prices_written"],0)
        self.assertEqual(report["line_messages_sent"],0)
        self.assertFalse(report["live_model_deployment_allowed"])

    def test_history_mismatch_fails_closed(self):
        bad=dict(self.anchors)
        bad[m.ALL_DAYS[0]]=Decimal("89.00")
        with self.assertRaisesRegex(ValueError,"mismatch"):
            m.verify_source_batches(m.BATCHES,self.roster,bad,
                fetcher=daily,sleeper=lambda _:None)

    def test_incomplete_market_day_blocks_claim(self):
        def source(day):
            return daily(day,limited=(day==m.ALL_DAYS[0]))
        with self.assertRaises(ValueError):
            m.verify_source_batches(m.BATCHES,self.roster,self.anchors,
                fetcher=source,sleeper=lambda _:None)

    def test_wrong_source_and_missing_2330_block(self):
        with self.assertRaises(ValueError):
            m.verify_source_batches(m.BATCHES,self.roster,self.anchors,
                fetcher=lambda day:daily(day,source="UNVERIFIED"),sleeper=lambda _:None)
        with self.assertRaisesRegex(ValueError,"Not all 26"):
            m.verify_source_batches(m.BATCHES,self.roster,self.anchors,
                fetcher=lambda day:rows(day,number=720),sleeper=lambda _:None)

    def test_invalid_batch_exclusions_and_pacing_refuse_before_http(self):
        cases=[
            (tuple(reversed(m.BATCHES)),self.roster,4),
            (m.BATCHES,self.roster|{("twse","1589")},4),
            (m.BATCHES,self.roster,0),
            (m.BATCHES,set(),4),
        ]
        for batches,roster,seconds in cases:
            calls=[]
            with self.subTest(seconds=seconds,roster=len(roster)),self.assertRaises(ValueError):
                m.verify_source_batches(batches,roster,self.anchors,
                    fetcher=lambda d:calls.append(d),pause_seconds=seconds)
            self.assertEqual(calls,[])

    def test_only_four_fixed_batches_and_no_twice_validated_2021_days(self):
        self.assertEqual(tuple(len(batch) for batch in m.BATCHES),(6,8,8,4))
        self.assertEqual(m.ALL_DAYS[0],date(2021,11,23))
        self.assertEqual(m.ALL_DAYS[-1],date(2021,12,30))
        self.assertNotIn(date(2021,12,1),m.ALL_DAYS)
        self.assertNotIn(date(2021,12,2),m.ALL_DAYS)
        self.assertEqual(m.validate_fixed_batches(m.BATCHES),m.ALL_DAYS)

    def test_read_existing_original_closes_in_one_readonly_sql_snapshot(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        cur=MagicMock()
        conn.cursor.return_value.__enter__.return_value=cur
        cur.fetchall.return_value=list(self.anchors.items())
        with patch("psycopg.connect",return_value=conn) as connect:
            out=m.read_anchors("postgres://masked")
        self.assertEqual(out,self.anchors)
        self.assertNotIn("options",connect.call_args.kwargs)
        self.assertEqual(conn.execute.call_args_list[0].args[0],
                         "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        self.assertIn("SET LOCAL statement_timeout",conn.execute.call_args_list[1].args[0])
        self.assertEqual(cur.execute.call_args.args,(m.ANCHORS_SQL,(list(m.ALL_DAYS),)))
        conn.rollback.assert_called_once()
        for token in ("INSERT INTO","DELETE FROM","UPDATE PUBLIC","DROP TABLE"):
            self.assertNotIn(token,m.ANCHORS_SQL.upper())
        cur.fetchall.return_value=list(self.anchors.items())[:-1]
        with patch("psycopg.connect",return_value=conn),self.assertRaises(ValueError):
            m.read_anchors("postgres://masked")

    def test_live_runner_checks_all_four_real_calendar_batches_before_http(self):
        found=[]
        def preflight(db,*,start,end,today):
            batch=next((b for b in m.BATCHES if b[0]==start),None)
            found.append((start,end))
            return list(batch),self.roster
        with patch.object(m,"read_anchors",return_value=self.anchors),\
             patch.object(m,"preflight",side_effect=preflight):
            out=m.run("postgres://masked",today=date(2026,11,23),
                      fetcher=daily,sleeper=lambda _:None)
        self.assertEqual(len(found),4)
        self.assertEqual(out["new_official_2021_source_days_verified"],26)
        self.assertEqual(out["existing_neon_raw_prices_written"],0)

    def test_changed_calendar_blocks_before_source(self):
        def preflight(db,*,start,end,today):
            batch=next((b for b in m.BATCHES if b[0]==start),None)
            return list(batch)[1:],self.roster
        with patch.object(m,"read_anchors",return_value=self.anchors),\
             patch.object(m,"preflight",side_effect=preflight):
            with self.assertRaisesRegex(ValueError,"calendar"):
                m.run("postgres://masked",today=date(2026,11,23),
                      fetcher=lambda d:self.fail("No external source request expected"))
