"""Tests for new-history-only composite inserts and bounded same-date audit."""
from __future__ import annotations

from datetime import date
import os
import unittest
from unittest import TestCase
from unittest.mock import MagicMock,patch

from scripts import new_eligible_score_followon as follow
from src import composite_score


def missing(stock="3523",market="tpex",n=90):
    return {
        "market":market,"stock_id":stock,"valid_days":n,
        "latest_close":date(2026,11,20),
        "has_tech":False,"has_smc":False,"has_score":False,
    }


BASELINE={"price_rows":198000,"latest_price_date":date(2026,11,20),
          "database_bytes":231000000}


class NewEligibleFollowonTests(TestCase):
    def test_candidate_query_only_selects_real_recent_sixty_session_unscored(self):
        q=follow.MISSING_SQL.lower()
        self.assertIn("p.valid_days>=60",q)
        self.assertIn("p.stock_id<>'1808'",q)
        self.assertIn("interval '7 days'",q)
        self.assertIn("not (has_tech and has_smc and has_score)",q)
        self.assertIn("c.total_score is not null",q)
        self.assertNotIn("insert into",q)
        self.assertEqual(follow.MAX_STOCKS,5)

    def test_no_write_without_opt_in(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(PermissionError):
                follow.execute("not-a-real-db",apply=True)
        for count in (0,6,True):
            with self.assertRaises(ValueError):
                follow.execute("not-a-real-db",limit=count)

    def test_bounded_dry_run_returns_missing_only_without_tech_or_score_calls(self):
        mock_conn=MagicMock()
        mock_conn.__enter__.return_value=mock_conn
        with patch.object(follow.psycopg,"connect",return_value=mock_conn),\
             patch.object(follow,"verified_baseline",return_value=BASELINE),\
             patch.object(follow,"candidates",return_value=[missing()]),\
             patch.object(follow,"build_adjusted_stock") as adj,\
             patch.object(follow,"calculate_all") as calc:
            out=follow.execute("protected",apply=False)
        self.assertEqual(len(out["selected"]),1)
        self.assertFalse(out["complete"])
        self.assertFalse(out["raw_prices_modified"])
        self.assertFalse(out["existing_composite_rows_overwritten"])
        adj.assert_not_called()
        calc.assert_not_called()

    def test_new_two_stock_history_is_scored_only_for_those_symbols(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        stocks=[missing("3523"),missing("3632",n=82)]
        with patch.dict(os.environ,{"STOCK_NEW_ELIGIBLE_SCORE_WRITE_ENABLED":"yes"}),\
             patch.object(follow.psycopg,"connect",return_value=conn),\
             patch.object(follow,"verified_baseline",return_value=BASELINE),\
             patch.object(follow,"candidates",return_value=stocks),\
             patch.object(follow,"build_adjusted_stock",return_value=90) as adj,\
             patch.object(follow,"build_technicals",return_value=90) as tech,\
             patch.object(follow,"build_smc",return_value=90) as smc,\
             patch.object(follow,"recheck",return_value={
                 "n":90,"d":date(2026,11,20),
                 "adj":True,"tech":True,"smc":True,"score":True,
             }),\
             patch.object(follow,"calculate_all",return_value=2) as calc:
            out=follow.execute("protected",apply=True,limit=2)
        self.assertTrue(out["complete"])
        self.assertEqual(out["indicator_stocks_computed"],2)
        self.assertEqual(out["new_composite_rows"],2)
        self.assertEqual(adj.call_count,2)
        self.assertEqual(tech.call_count,2)
        self.assertEqual(smc.call_count,2)
        calc.assert_called_once_with("protected",stocks=[
            ("tpex","3523"),("tpex","3632")],missing_only=True)

    def test_existing_latest_indicator_skips_unnecessary_indicator_updates(self):
        item={**missing("3523"),"has_tech":True,"has_smc":True}
        conn=MagicMock()
        conn.__enter__.return_value=conn
        with patch.dict(os.environ,{"STOCK_NEW_ELIGIBLE_SCORE_WRITE_ENABLED":"yes"}),\
             patch.object(follow.psycopg,"connect",return_value=conn),\
             patch.object(follow,"verified_baseline",return_value=BASELINE),\
             patch.object(follow,"candidates",return_value=[item]),\
             patch.object(follow,"build_adjusted_stock") as adj,\
             patch.object(follow,"recheck",return_value={
                 "n":90,"d":date(2026,11,20),
                 "adj":True,"tech":True,"smc":True,"score":True,
             }),\
             patch.object(follow,"calculate_all",return_value=1):
            out=follow.execute("protected",apply=True)
        adj.assert_not_called()
        self.assertTrue(out["complete"])
        self.assertEqual(out["indicator_stocks_computed"],0)

    def test_incomplete_final_score_fails_closed(self):
        item={**missing("3523"),"has_tech":True,"has_smc":True}
        conn=MagicMock()
        conn.__enter__.return_value=conn
        with patch.dict(os.environ,{"STOCK_NEW_ELIGIBLE_SCORE_WRITE_ENABLED":"yes"}),\
             patch.object(follow.psycopg,"connect",return_value=conn),\
             patch.object(follow,"verified_baseline",return_value=BASELINE),\
             patch.object(follow,"candidates",return_value=[item]),\
             patch.object(follow,"recheck",return_value={
                 "n":90,"d":date(2026,11,20),
                 "adj":True,"tech":True,"smc":True,"score":False,
             }),\
             patch.object(follow,"calculate_all",return_value=0):
            with self.assertRaisesRegex(RuntimeError,"Not all selected"):
                follow.execute("protected",apply=True)

    def test_rejects_source_row_regression_and_storage_limit(self):
        with self.assertRaisesRegex(RuntimeError,"stop line"):
            conn=MagicMock()
            cursor=conn.cursor.return_value.__enter__.return_value
            cursor.fetchone.return_value={
                **BASELINE,"database_bytes":800000000
            }
            follow.verified_baseline(conn)
        for field,value in (("price_rows",None),("latest_price_date",None)):
            conn=MagicMock()
            cursor=conn.cursor.return_value.__enter__.return_value
            cursor.fetchone.return_value={**BASELINE,field:value}
            with self.assertRaises(RuntimeError):
                follow.verified_baseline(conn)
        conn=MagicMock()
        cursor=conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value={"n":10,"d":date(2026,11,20)}
        with self.assertRaisesRegex(RuntimeError,"history changed"):
            follow.recheck(conn,missing())


class CompositeBoundedModeTests(TestCase):
    def test_rejects_unbounded_or_invalid_missing_only_scoring(self):
        with self.assertRaisesRegex(ValueError,"bounded explicit"):
            composite_score.calculate_all("unused",missing_only=True)
        for keys in ([],[("twse","1808")],[("tpex","3523")]*2,
                     [("tpex","3523")]*11,[("unknown","3523")]):
            with self.subTest(keys=keys):
                with self.assertRaises(ValueError):
                    composite_score.calculate_all("unused",stocks=keys,missing_only=True)

    def test_explicit_missing_only_scoring_preserves_existing_composite(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        cursor=conn.cursor.return_value.__enter__.return_value
        # tr: date,close, nine MA windows, rsi, volume MA5, volume MA20
        tr=(date(2026,11,20),100,
            100,100,100,100,100,100,100,100,100,
            50,1000,1000)
        smc=(1,False,False,False,False,False,False,None,None)
        cursor.fetchone.side_effect=[tr,smc,None,("3523",)]
        with patch.object(composite_score.psycopg,"connect",return_value=conn):
            result=composite_score.calculate_all(
                "protected",stocks=[("tpex","3523")],missing_only=True)
        self.assertEqual(result,1)
        sqls=[str(call.args[0]) for call in cursor.execute.call_args_list]
        self.assertEqual(len(sqls),4)
        self.assertIn("DO NOTHING RETURNING stock_id",sqls[-1])
        self.assertNotIn("DO UPDATE",sqls[-1])
        self.assertNotIn("SCORABLE_STOCKS_SQL",str(sqls))


if __name__=="__main__":
    import unittest
    unittest.main()
