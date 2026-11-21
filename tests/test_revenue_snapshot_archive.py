"""TWSE/TPEx monthly revenue first-observed-at ingestion contracts."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os
import unittest
from unittest.mock import MagicMock,patch

from src import official_revenue_archive as archive
from scripts import capture_official_revenue as capture


def row(stock="2330",revenue="123,456",month="11510",table="1151117",yoy="18.25"):
    return {"公司代號":stock,"資料年月":month,"出表日期":table,
            "營業收入-當月營收":revenue,
            "營業收入-去年同月增減(%)":yoy}


AT="2026-11-21T17:30:00+08:00"


class RevenueParserTests(unittest.TestCase):
    def test_bounded_official_source_period_is_not_release_timestamp(self):
        out=archive.parse_snapshot("twse",[row()],observed_at=AT)
        self.assertEqual(len(out),1)
        x=out[0]
        self.assertEqual(x["market"],"twse")
        self.assertEqual(x["period_end"],"2026-10-31")
        self.assertEqual(x["official_table_date"],"2026-11-17")
        self.assertEqual(x["first_observed_at"],AT)
        self.assertEqual(x["reported_revenue_thousands_ntd"],"123456")
        self.assertEqual(x["reported_yoy_pct"],"18.25")
        self.assertEqual(len(x["payload_sha256"]),64)
        self.assertEqual(x["source_url"],archive.SOURCES["twse"])
        self.assertNotIn("published_at",x)
        self.assertEqual(archive.parse_snapshot("tpex",[row("3523")],observed_at=AT)[0]["market"],"tpex")

    def test_asof_never_backdates_when_official_row_was_first_seen_later(self):
        evidence=archive.parse_snapshot("twse",[row()],observed_at=AT)
        before=archive.asof_archive(evidence,market="twse",stock_id="2330",
                                   signal_cutoff="2026-11-21T13:30:00+08:00")
        after=archive.asof_archive(evidence,market="twse",stock_id="2330",
                                  signal_cutoff="2026-11-23T13:30:00+08:00")
        self.assertIsNone(before["revenue"])
        self.assertFalse(before["metric_covered"])
        self.assertTrue(after["metric_covered"])
        self.assertEqual(after["revenue"]["reported_revenue_thousands_ntd"],"123456")
        self.assertFalse(after["publication_timestamp_known"])
        self.assertFalse(after["trading_approved"])

    def test_revisions_append_and_later_captures_never_rewrite_old_vintage(self):
        versions=archive.parse_snapshot("twse",[row()],observed_at=AT)
        versions+=archive.parse_snapshot("twse",[row(revenue="130000")],
                                         observed_at="2026-11-23T17:00:00+08:00")
        earlier=archive.asof_archive(versions,market="twse",stock_id="2330",
                                    signal_cutoff="2026-11-23T13:30:00+08:00")
        later=archive.asof_archive(versions,market="twse",stock_id="2330",
                                  signal_cutoff="2026-11-24T13:30:00+08:00")
        self.assertEqual(earlier["revenue"]["reported_revenue_thousands_ntd"],"123456")
        self.assertEqual(later["revenue"]["reported_revenue_thousands_ntd"],"130000")
        self.assertNotEqual(versions[0]["payload_sha256"],versions[1]["payload_sha256"])

    def test_official_extreme_yoy_is_suppressed_not_fabricated_or_import_blocked(self):
        # Real official OpenAPI can report extreme % changes near a zero
        # base. Retain actual monthly revenue, never use that YoY as a factor.
        out=archive.parse_snapshot("twse",[row(yoy="123,456,789.00")],observed_at=AT)
        self.assertEqual(len(out),1)
        self.assertIsNone(out[0]["reported_yoy_pct"])
        self.assertTrue(out[0]["official_yoy_outlier_suppressed"])
        self.assertEqual(out[0]["reported_revenue_thousands_ntd"],"123456")
        normal=archive.parse_snapshot("twse",[row(yoy="18.25")],observed_at=AT)
        self.assertFalse(normal[0]["official_yoy_outlier_suppressed"])
        self.assertNotEqual(normal[0]["payload_sha256"],out[0]["payload_sha256"])

    def test_rejects_fabrication_invalid_dates_missing_official_fields_and_duplicates(self):
        cases=[
            [row(table="1151122")],
            [row(month="11512")],
            [row(revenue="not real")],
            [row(revenue="Infinity")],
            [row(revenue=True)],
            [row(),row()],
            [{"公司代號":"2330"}],
        ]
        for rows in cases:
            with self.subTest(rows=rows):
                with self.assertRaises((ValueError,KeyError)):
                    archive.parse_snapshot("twse",rows,observed_at=AT)
        with self.assertRaises(ValueError):
            archive.parse_snapshot("tpex",[],observed_at=AT)
        with self.assertRaises(ValueError):
            archive.parse_snapshot("twse",[row()]*2501,observed_at=AT)
        with self.assertRaises(ValueError):
            archive.parse_snapshot("twse",[row()],observed_at="2026-11-21T15:00:00")
        with self.assertRaises(ValueError):
            archive.asof_archive([],market="twse",stock_id="2330",
                                 signal_cutoff="2026-11-23T14:00:00+08:00")

    def test_source_uses_only_fixed_https_endpoints_and_size_limit(self):
        response=MagicMock(status_code=200,url=archive.SOURCES["twse"],content=b"[]")
        response.json.return_value=[row()]
        session=MagicMock()
        session.get.return_value=response
        records=capture.fetch_market("twse",observed_at=AT,session=session)
        self.assertEqual(len(records),1)
        self.assertEqual(session.get.call_args.kwargs["allow_redirects"],False)
        self.assertEqual(session.get.call_args.kwargs["timeout"],(10,25))
        response.url="http://untrusted.invalid"
        with self.assertRaises(RuntimeError):
            capture.fetch_market("twse",observed_at=AT,session=session)
        response.url=archive.SOURCES["twse"]
        response.content=b"x"*(capture.MAX_SOURCE_BYTES+1)
        with self.assertRaises(RuntimeError):
            capture.fetch_market("twse",observed_at=AT,session=session)

    def test_write_gate_and_source_only_dryrun(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(PermissionError):
                capture.capture("fake",apply=True)
        with patch.object(capture,"fetch_market",return_value=archive.parse_snapshot(
                "twse",[row()],observed_at=AT)), \
             patch.object(capture.psycopg,"connect") as db:
            output=capture.capture("",apply=False,observed_at=AT)
            self.assertFalse(output["persisted"])
            self.assertEqual(output["inserted"],0)
            self.assertFalse(output["exact_release_timestamp_known"])
            self.assertTrue(output["historical_before_first_capture_not_inferred"])
            db.assert_not_called()
        with patch.dict(os.environ,{"STOCK_OFFICIAL_REVENUE_ARCHIVE_WRITE":"yes"}):
            with self.assertRaises(ValueError):
                capture.capture("fake",apply=True,observed_at=AT)

    def test_archive_ddl_and_insert_strictly_append_only_for_known_issuers(self):
        sql=capture.INSERT_SQL.upper()
        ddl=(Path(__file__).resolve().parents[1]/
             "sql/official_revenue_observation_schema.sql").read_text(encoding="utf-8").upper()
        self.assertIn("ON CONFLICT (MARKET,STOCK_ID,PERIOD_END,PAYLOAD_SHA256) DO NOTHING",sql)
        self.assertIn("EXISTS(SELECT 1 FROM PUBLIC.STOCK_MASTER",sql)
        self.assertIn("FIRST_OBSERVED_AT",sql)
        self.assertIn("%(MARKET)S::TEXT",sql)
        self.assertIn("%(STOCK_ID)S::VARCHAR(6)",sql)
        self.assertIn("%(PERIOD_END)S::DATE",sql)
        self.assertIn("%(FIRST_OBSERVED_AT)S::TIMESTAMPTZ",sql)
        self.assertIn("PRIMARY KEY (MARKET,STOCK_ID,PERIOD_END,PAYLOAD_SHA256)",ddl)
        for forbidden in ("DO UPDATE","DELETE FROM","TRUNCATE","DROP TABLE"):
            self.assertNotIn(forbidden,sql)


if __name__=="__main__":
    unittest.main()
