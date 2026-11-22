"""2024 all-current-survivor MA240 read-only stream, exact source integrity."""
from datetime import date,timedelta
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock,patch

from scripts import twse_2024_full_market_ma240_readonly as m


def market_days():
    days=[]
    d=date(2024,1,2)
    while len(days)<m.EXPECTED_MARKET_DAYS:
        if d.weekday()<5:
            days.append(d)
        d+=timedelta(days=1)
    return days


def five_stock_mock():
    result=[]
    days=market_days()
    for j in range(5):
        stock=f"{1101+j:04d}"
        for i,day in enumerate(days):
            close=Decimal("50")+Decimal(j)+Decimal(i%20)/Decimal(10)
            result.append({
                "market":"twse","stock_id":stock,"trade_date":day,
                "open":close,"high":close+Decimal("1"),
                "low":close-Decimal("1"),"close":close,
                "volume":100000+i,"turnover":close*Decimal(100000+i),
                "price_change":Decimal("0.1"),"transactions":80,
                "source":m.SOURCE_TAG,
            })
    return result


class CurrentTWSEMarketReadOnlyTests(TestCase):
    def test_five_realistic_242_day_stream_and_causal_factor_safeguards(self):
        receipt=m.audit_ordered_stock_rows(iter(five_stock_mock()),minimum=5)
        self.assertEqual(receipt["actual_2024_common_market_days"],242)
        self.assertEqual(receipt["actual_current_listed_stocks_with_all_242_sessions"],5)
        self.assertEqual(receipt["total_official_price_rows_read"],1210)
        self.assertEqual(receipt["exact_ma240_prefix_parity_stock_count"],5)
        self.assertEqual(receipt["technical_smc_12_feature_prefix_checks"],5)
        self.assertEqual(len(receipt["aggregate_stock_ma_and_source_sha256"]),64)
        self.assertTrue(receipt["source_bars_present_in_neon_before_test"])
        self.assertFalse(receipt["survivorship_free_asof_market_universe"])
        self.assertFalse(receipt["dividend_adjusted_total_return_verified"])
        self.assertFalse(receipt["independent_model_alpha_validated"])
        self.assertFalse(receipt["live_trading_approved"])
        self.assertEqual(receipt["neon_price_or_derived_rows_written"],0)
        self.assertEqual(receipt["github_price_or_factor_artifacts_written"],0)
        self.assertNotIn("stock_id",receipt)
        self.assertNotIn("price",receipt.get("scope","").lower())

    def test_missing_duplicate_changed_dates_price_or_delisted_fails_closed(self):
        for bad in ("missing","duplicate","bad_source","bad_price",
                    "bad_stock","wrong_year","date_order","bad_volume"):
            rows=five_stock_mock()
            if bad=="missing":
                del rows[9]
            elif bad=="duplicate":
                rows[9]=dict(rows[8])
            elif bad=="bad_source":
                rows[9]["source"]="UNTRUSTED"
            elif bad=="bad_price":
                rows[9]["close"]=Decimal("-10")
            elif bad=="bad_stock":
                rows[9]["stock_id"]="1589"
            elif bad=="wrong_year":
                rows[9]["trade_date"]=date(2023,1,2)
            elif bad=="date_order":
                rows[0],rows[-1]=rows[-1],rows[0]
            elif bad=="bad_volume":
                rows[9]["volume"]=float(500)
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                m.audit_ordered_stock_rows(rows,minimum=5)

    def test_single_server_cursor_readonly_and_no_public_stock_output(self):
        rows=five_stock_mock()
        conn=MagicMock()
        conn.__enter__.return_value=conn
        cursor=MagicMock()
        cursor.__enter__.return_value=cursor
        cursor.fetchmany.side_effect=[rows[:800],rows[800:],[]]
        conn.cursor.return_value=cursor
        with (
            TemporaryDirectory() as td,
            patch("psycopg.connect",return_value=conn) as connected,
            patch.object(m,"audit_ordered_stock_rows",
                         side_effect=lambda source:
                         m.audit_ordered_stock_rows(source,minimum=5)),
        ):
            path=Path(td)/"aggregate-only.json"
            report=m.execute("postgresql://fake",output=path)
            self.assertEqual(report["actual_current_listed_stocks_with_all_242_sessions"],5)
            self.assertEqual(json.loads(path.read_text()),report)
            self.assertNotIn('"stock_id"',path.read_text())
            self.assertNotIn('"open"',path.read_text())
            self.assertEqual(conn.execute.call_args_list[0].args[0],
                             "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            self.assertIn("default_transaction_read_only=on",
                          connected.call_args.kwargs["options"])
            cursor.execute.assert_called_once_with(
                m.STREAM_SQL,
                (m.YEAR_START,m.YEAR_END,m.YEAR_START,m.YEAR_END),
            )

    def test_sql_exact_242_current_listed_exclusions_and_row_bounds(self):
        self.assertIn("official_current_listed",m.STREAM_SQL)
        self.assertIn("model_stock_exclusions",m.STREAM_SQL)
        self.assertIn("p.stock_id<>'1589'",m.STREAM_SQL)
        self.assertIn("HAVING COUNT(*) = 242",m.STREAM_SQL)
        self.assertIn("ORDER BY p.stock_id,p.trade_date",m.STREAM_SQL)
        for token in ("INSERT INTO","UPDATE ","DELETE FROM","TRUNCATE ","DROP "):
            self.assertNotIn(token,m.STREAM_SQL.upper())
        self.assertLessEqual(m.MAX_TOTAL_ROWS,250000)
        self.assertEqual(m.MIN_FULL_STOCKS,800)
        self.assertEqual(m.FEATURE_SPOTCHECK_STOCKS,5)
        with self.assertRaises(ValueError):
            m.audit_ordered_stock_rows(five_stock_mock())
