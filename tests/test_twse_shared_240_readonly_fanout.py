"""Shared TWSE date-source fanout validates 240-session stock factors."""
from datetime import date,timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock,patch
import json

from scripts import twse_shared_240_readonly_fanout as m


def trading_days():
    result=[]
    d=date(2024,1,2)
    while len(result)<m.EXPECTED_SESSIONS:
        if d.weekday()<5:
            result.append(d)
        d+=timedelta(days=1)
    return result


def panel():
    rows=[]
    for i,d in enumerate(trading_days()):
        for j,sid in enumerate(m.COHORT):
            close=Decimal("50.00")+Decimal(j)+Decimal(i)/Decimal(100)
            rows.append({
                "market":"twse","stock_id":sid,"trade_date":d,
                "open":close,"high":close+Decimal("0.50"),
                "low":close-Decimal("0.50"),"close":close,
                "volume":100_000+i,"turnover":close*Decimal(100_000+i),
                "price_change":Decimal("0.01"),"transactions":200,
                "source":m.OFFICIAL_SOURCE,
            })
    return rows


class Shared240FactorTests(TestCase):
    def test_true_five_stock_shared_panel_and_exact_causal_bridge(self):
        report=m.audit_shared_240(panel())
        self.assertEqual(report["shared_official_market_dates"],242)
        self.assertEqual(report["source_stock_rows_consumed"],1210)
        self.assertEqual(report["current_listed_eligible_stocks_verified"],5)
        self.assertEqual(report["source_gets_or_sql_queries_for_all_stocks"],1)
        self.assertEqual(report["causal_240_session_sma_checks"],5)
        self.assertEqual(report["causal_technical_smc_vector_checks"],5)
        self.assertEqual(report["existing_raw_feature_count"],12)
        self.assertEqual(len(report["aggregate_private_source_feature_sha256"]),64)
        self.assertEqual(report["neon_price_and_derived_rows_written"],0)
        self.assertTrue(report["neon_source_is_already_saved_not_new_2022_replay"])
        self.assertFalse(report["all_market_five_year_factor_coverage_proven"])
        self.assertFalse(report["independent_future_alpha_validated"])
        self.assertFalse(report["model_live_trading_approved"])
        self.assertNotIn("stock_id",report)
        self.assertNotIn("signals",report)

    def test_missing_date_one_stock_altered_source_price_or_replay_rejected(self):
        for scenario in ("missing","wrong_source","bad_close","duplicate",
                         "wrong_stock","mixed_date","reverse"):
            p=panel()
            if scenario=="missing":
                del p[100]
            elif scenario=="wrong_source":
                p[100]["source"]="TWSE_STOCK_DAY"
            elif scenario=="bad_close":
                p[100]["close"]=Decimal("-5")
            elif scenario=="duplicate":
                p[101]=dict(p[100])
            elif scenario=="wrong_stock":
                p[100]["stock_id"]="1589"
            elif scenario=="mixed_date":
                p[100]["trade_date"]=date(2025,1,1)
            elif scenario=="reverse":
                p[0],p[1]=p[1],p[0]
            with self.subTest(case=scenario),self.assertRaises(ValueError):
                m.audit_shared_240(p)

    def test_no_future_bar_affects_previous_240_day_factor(self):
        rows=panel()
        by_stock,days=m.validate_shared_panel(rows)
        sid=m.COHORT[0]
        first=m.exact_sma240(by_stock[sid],asof=days[-2])
        by_stock[sid][-1]["close"]=Decimal("1000000")
        self.assertEqual(first,m.exact_sma240(by_stock[sid],asof=days[-2]))

    def test_single_readonly_sql_call_and_zero_output_prices(self):
        rows=panel()
        conn=MagicMock()
        conn.__enter__.return_value=conn
        conn.execute.return_value.fetchall.return_value=rows
        with TemporaryDirectory() as folder,patch("psycopg.connect",return_value=conn) as connect:
            out=Path(folder)/"aggregate.json"
            result=m.execute("postgresql://not-real",output=out)
            self.assertTrue(out.is_file())
            doc=out.read_text()
            self.assertEqual(json.loads(doc),result)
            self.assertNotIn("stock_id",doc)
            self.assertNotIn("signal_raw_close",doc)
            self.assertNotIn("1301",doc)
            self.assertIn("default_transaction_read_only=on",
                          connect.call_args.kwargs["options"])
            self.assertEqual(conn.execute.call_args_list[0].args[0],
                             "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            self.assertEqual(conn.execute.call_args_list[2].args[0],m.OFFICIAL_SQL)
            self.assertEqual(conn.execute.call_args_list[2].args[1],
                             (list(m.COHORT),m.YEAR_START,m.YEAR_END,
                              m.MAX_TOTAL_ROWS+1))
            self.assertEqual(result["line_messages_sent"],0)

    def test_no_exclusion_or_security_bypass(self):
        self.assertEqual(len(m.COHORT),5)
        self.assertEqual(len(set(m.COHORT)),5)
        self.assertNotIn("1589",m.COHORT)
        self.assertIn("official_current_listed",m.OFFICIAL_SQL)
        self.assertIn("model_stock_exclusions",m.OFFICIAL_SQL)
        self.assertIn("p.source='TWSE_MI_INDEX_ALLBUT0999'",m.OFFICIAL_SQL)
        self.assertIn("LIMIT %s",m.OFFICIAL_SQL)
        for token in ("INSERT INTO","UPDATE ","DELETE FROM","TRUNCATE ","DROP "):
            self.assertNotIn(token,m.OFFICIAL_SQL.upper())
