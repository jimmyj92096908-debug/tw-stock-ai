"""No-storage official 2022 source-on-demand probe contract and mock source."""
from datetime import date, timedelta
from decimal import Decimal
from unittest import TestCase
from unittest.mock import MagicMock, patch
from tempfile import TemporaryDirectory
from pathlib import Path
import json

from scripts import twse_stateless_2022_source_probe as p


def rows(day, *, number=720):
    out=[]
    for code in range(1100,1100+number+1):
        sid=f"{code:04d}"
        if sid=="1589":
            continue
        out.append({
            "market":"twse", "stock_id":sid, "trade_date":day,
            "open":Decimal("100.000"), "high":Decimal("102.500"),
            "low":Decimal("99.000"), "close":Decimal("100.2500"),
            "volume":200000, "turnover":Decimal("20050000.00"),
            "transactions":150, "price_change":Decimal("0.2500"),
            "source":"TWSE_MI_INDEX_ALLBUT0999",
        })
    return out[:number]


def connection():
    obj=MagicMock()
    obj.__enter__.return_value=obj
    return obj


class TWSEStatelessSourceProofTests(TestCase):
    def test_date_and_quota_boundaries(self):
        p.validate_dates(p.DAYS,today=date(2026,11,22))
        for wrong in [
            (), (p.DAYS[0],)*2,
            (p.DAYS[1],p.DAYS[0]),
            (date(2022,1,1),),
            (date(2023,2,24),),
            p.DAYS+(date(2022,1,6),),
            (date(2022,1,3),date(2022,1,4),date(2022,1,5)),
        ]:
            with self.subTest(dates=wrong),self.assertRaises(ValueError):
                p.validate_dates(wrong,today=date(2026,11,22))
        with self.assertRaises(ValueError):
            p.validate_dates(p.DAYS,today=date(2022,1,5))

    def test_real_parser_contract_filters_current_allowed_and_exclusion(self):
        day=p.DAYS[0]
        official=rows(day)
        allowed={("twse",r["stock_id"]) for r in official}
        official.append({
            **official[0], "stock_id":"1589",
        })
        # A fabricated issuer not in today's official roster must not enter.
        official.append({**official[0],"stock_id":"9998"})
        digest=p.source_fingerprint(
            official,trade_date=day,allowed=allowed,minimum=500,
        )
        self.assertEqual(digest["validated_current_listed_source_bars"],720)
        self.assertEqual(len(digest["source_fingerprint_sha256"]),64)
        self.assertNotIn("prices",digest)
        self.assertTrue(digest["none_of_the_source_bars_persisted"])
        with self.assertRaises(ValueError):
            p.source_fingerprint(official[:300],trade_date=day,
                                 allowed=allowed,minimum=500)
        bad=rows(day)
        bad[0]["source"]="UNVERIFIED"
        with self.assertRaises(ValueError):
            p.source_fingerprint(bad,trade_date=day,
                                 allowed=allowed,minimum=500)

    def test_execute_two_official_days_with_readonly_neon_and_no_archive(self):
        roster={("twse",r["stock_id"]) for r in rows(p.DAYS[0])}
        mock_conn=connection()
        seen=[]
        def source(day):
            seen.append(day)
            return rows(day)
        with (
            TemporaryDirectory() as temp,
            patch("psycopg.connect",return_value=mock_conn) as connect,
            patch.object(p,"load_current_twse_allowed",return_value=roster),
            patch.object(p,"_processed_days",return_value=set()),
        ):
            path=Path(temp)/"aggregates-only.json"
            receipt=p.execute("postgres://fake",fetcher=source,
                              sleep_seconds=0,output_path=path)
            self.assertEqual(seen,list(p.DAYS))
            self.assertEqual(receipt["aggregate_current_eligible_source_bars"],1440)
            self.assertEqual(receipt["neon_storage_bytes_written"],0)
            self.assertFalse(receipt["complete_five_year_price_history_proven"])
            self.assertEqual(receipt["raw_ohlcv_files_or_archives_written"],0)
            self.assertFalse(receipt["model_live_trading_approved"])
            parsed=json.loads(path.read_text())
            self.assertEqual(set(parsed),set(receipt))
            self.assertNotIn("stock_id",path.read_text())
            self.assertNotIn("close",path.read_text())
            self.assertEqual(mock_conn.execute.call_args_list[0].args[0],
                             "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            self.assertIn("default_transaction_read_only=on",
                          connect.call_args.kwargs["options"])

    def test_processed_day_or_source_outage_blocks_without_output(self):
        roster={("twse",r["stock_id"]) for r in rows(p.DAYS[0])}
        conn=connection()
        with (
            patch("psycopg.connect",return_value=conn),
            patch.object(p,"load_current_twse_allowed",return_value=roster),
            patch.object(p,"_processed_days",return_value={p.DAYS[0]}),
        ):
            with self.assertRaisesRegex(ValueError,"no longer missing"):
                p.execute("fake",sleep_seconds=0,fetcher=lambda d:rows(d))
        with (
            patch("psycopg.connect",return_value=conn),
            patch.object(p,"load_current_twse_allowed",return_value=roster),
            patch.object(p,"_processed_days",return_value=set()),
        ):
            with self.assertRaisesRegex(ValueError,"valid trading day"):
                p.execute("fake",sleep_seconds=0,fetcher=lambda d:None)

    def test_proof_is_never_a_source_importer(self):
        self.assertEqual(p.MAX_DAYS,2)
        self.assertEqual(p.DAYS[0],date(2022,1,4))
        for sql_mutation in ("INSERT INTO", "UPDATE public.", "DELETE FROM",
                             "TRUNCATE public."):
            self.assertNotIn(sql_mutation,
                p.source_fingerprint.__code__.co_consts)
        self.assertIn("2022",p.__doc__)
