"""No-overwrite, independent anchor, finite budget and no-free-alpha claims."""
from datetime import date
import os
from unittest import TestCase
from unittest.mock import MagicMock, patch

from scripts import tpex_long_history_ladder as m


def official(day, close=100, code="1234"):
    return {"stock_id":code,"trade_date":day,
            "open":close,"high":close+2,"low":close-2,"close":close,
            "volume":1000,"turnover":100000,"change":0,"transactions":10,
            "source":"TPEX_TRADING_STOCK"}


class TPExBackwardHistoryCanaryTests(TestCase):
    def test_ladder_starts_before_real_earliest_observation(self):
        self.assertEqual([x.isoformat() for x in m.plan_months(
            date(2026,7,16),today=date(2026,11,21))],
            ["2026-03-01","2026-04-01","2026-05-01","2026-06-01","2026-07-01"])
        self.assertEqual([x.isoformat() for x in m.plan_months(
            date(2021,12,10),today=date(2026,11,21))],
            ["2021-11-01","2021-12-01"])
        self.assertEqual(m.plan_months(date(2021,11,20),today=date(2026,11,21)),[])
        for first,today,months in (
            (date(2026,12,1),date(2026,11,21),5),
            (date(2026,7,1),date(2026,11,21),6),
        ):
            with self.assertRaises(ValueError):
                m.plan_months(first,today=today,months=months)

    def test_source_limit_and_strict_anchored_validate(self):
        months=[date(2026,6,1),date(2026,7,1)]
        with patch.object(m.tpex_market_data,"fetch_month",side_effect=[
            [official("2026-06-12")],[official("2026-07-16")]
        ]) as source,patch.object(m.time,"sleep") as sleep:
            bars=m.official_months("1234",months,today=date(2026,11,21))
        self.assertEqual(len(bars),2)
        self.assertEqual(source.call_count,2)
        sleep.assert_called_once_with(2)
        with patch.object(m.tpex_market_data,"fetch_month",return_value=[
            official("2026-09-01")]):
            with self.assertRaisesRegex(ValueError,"mismatched"):
                m.official_months("1234",[date(2026,7,1)],today=date(2026,11,21))
        with self.assertRaises(ValueError):
            m.official_months("1234",[],today=date(2026,11,21))
        with self.assertRaises(ValueError):
            m.official_months("1234",[date(2026,7,1)]*6,today=date(2026,11,21))

    def test_anchor_requires_multiple_existing_identical_closes(self):
        conn=MagicMock()
        cur=conn.cursor.return_value.__enter__.return_value
        rows=[official("2026-07-16"),official("2026-07-17")]
        cur.fetchall.return_value=[
            {"trade_date":date(2026,7,16),"close":100},
            {"trade_date":date(2026,7,17),"close":100}]
        self.assertEqual(m.verify_existing_anchor(conn,"1234",date(2026,7,1),rows),2)
        # Regression: the live dict_row rows must match by date KEY, not dict iteration.
        self.assertNotIn("for day,close in known",
                         __import__("inspect").getsource(m.verify_existing_anchor))
        cur.fetchall.return_value=[
            {"trade_date":date(2026,7,16),"close":100}]
        with self.assertRaisesRegex(ValueError,"Insufficient"):
            m.verify_existing_anchor(conn,"1234",date(2026,7,1),rows)
        cur.fetchall.return_value=[
            {"trade_date":date(2026,7,16),"close":101},
            {"trade_date":date(2026,7,17),"close":100}]
        with self.assertRaisesRegex(ValueError,"mismatch"):
            m.verify_existing_anchor(conn,"1234",date(2026,7,1),rows)

    def test_apply_requires_separate_explicit_gate(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(PermissionError):
                m.run("protected",apply=True)
        for limit,months in ((0,5),(3,5),(2,6),(True,5),(1,0)):
            with self.assertRaises(ValueError):
                m.run("protected",limit=limit,months=months)

    def test_read_only_preview_never_calls_source_or_writer(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        stock={"market":"tpex","stock_id":"1234","valid_days":85,
               "first_observed":date(2026,7,16),"last_observed":date(2026,11,20)}
        with patch.object(m.psycopg,"connect",return_value=conn),\
             patch.object(m.existing,"_size_guard",return_value=300000000),\
             patch.object(m,"_select",return_value=[stock]),\
             patch.object(m,"official_months") as network,\
             patch.object(m.existing,"_state") as state:
            result=m.run("protected",apply=False,limit=1,today=date(2026,11,21))
        self.assertEqual(result["stocks_selected"],1)
        self.assertEqual(result["source_calls_actual"],0)
        self.assertEqual(result["new_valid_days"],0)
        self.assertFalse(result["existing_price_keys_overwritten"])
        self.assertFalse(result["complete_five_year_official_history_verified"])
        self.assertFalse(result["LINE_or_trading_enabled"])
        self.assertEqual(result["stocks"][0]["months_to_request"],
                         ["2026-03","2026-04","2026-05","2026-06","2026-07"])
        network.assert_not_called()
        state.assert_not_called()

    def test_manual_canary_insert_only_growth_and_per_stock_commit(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        conn.transaction.return_value.__enter__.return_value=conn
        stock={"market":"tpex","stock_id":"1234","valid_days":85,
               "first_observed":date(2026,7,16),"last_observed":date(2026,11,20)}
        states=[{"days":85,"first_observed":date(2026,7,16),
                 "last_observed":date(2026,11,20)},
                {"days":95,"first_observed":date(2026,6,1),
                 "last_observed":date(2026,11,20)}]
        bars=[official("2026-06-01"),official("2026-07-16")]
        with patch.dict(os.environ,{"STOCK_TPEX_LONG_HISTORY_ENABLED":"yes"}),\
             patch.object(m.psycopg,"connect",return_value=conn),\
             patch.object(m.existing,"_size_guard",return_value=300000000),\
             patch.object(m,"_select",return_value=[stock]),\
             patch.object(m,"official_months",return_value=bars) as network,\
             patch.object(m,"_stock_state",side_effect=states),\
             patch.object(m,"verify_existing_anchor",return_value=2),\
             patch.object(m.existing,"_state") as state:
            result=m.run("protected",apply=True,limit=1,today=date(2026,11,21))
        self.assertEqual(result["new_valid_days"],10)
        self.assertEqual(result["source_calls_actual"],5)
        self.assertEqual(network.call_count,2)
        self.assertEqual(network.call_args_list[0].args[1],[date(2026,7,1)])
        self.assertEqual([x.strftime("%Y-%m") for x in network.call_args_list[1].args[1]],
                         ["2026-03","2026-04","2026-05","2026-06"])
        self.assertEqual(result["stocks"][0]["status"],"new_official_history")
        conn.cursor.return_value.__enter__.return_value.executemany.assert_called_once()
        self.assertIn("DO NOTHING",m.existing.PRICE_INSERT_ONLY_SQL)
        self.assertNotIn("DO UPDATE",m.existing.PRICE_INSERT_ONLY_SQL)
        state.assert_called_once()
        self.assertEqual(state.call_args.args[2],"success")

    def test_failed_anchor_never_inserts_prices_and_is_not_success(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        stock={"market":"tpex","stock_id":"1234","valid_days":85,
               "first_observed":date(2026,7,16),"last_observed":date(2026,11,20)}
        with patch.dict(os.environ,{"STOCK_TPEX_LONG_HISTORY_ENABLED":"yes"}),\
             patch.object(m.psycopg,"connect",return_value=conn),\
             patch.object(m.existing,"_size_guard",return_value=300000000),\
             patch.object(m,"_select",return_value=[stock]),\
             patch.object(m,"official_months",return_value=[official("2026-07-16")]) as source,\
             patch.object(m,"_stock_state",return_value={"days":85,
                "first_observed":date(2026,7,16),"last_observed":date(2026,11,20)}),\
             patch.object(m,"verify_existing_anchor",side_effect=ValueError("bad-anchor")),\
             patch.object(m.existing,"_state") as state:
            result=m.run("protected",apply=True,limit=1,today=date(2026,11,21))
        self.assertEqual(result["new_valid_days"],0)
        self.assertEqual(result["stocks"][0]["status"],"failed")
        source.assert_called_once()
        conn.cursor.return_value.__enter__.return_value.executemany.assert_not_called()
        self.assertEqual(state.call_args.args[2],"failed")

    def test_candidate_source_and_storage_safety(self):
        sql=m.CANDIDATES_SQL.upper()
        self.assertIn("H.VALID_DAYS BETWEEN 60 AND 999",sql)
        self.assertIn("H.FIRST_OBSERVED>LM.LATEST_DATE-INTERVAL '5 YEARS'",sql)
        self.assertIn("ST.LAST_ATTEMPT_AT",sql)
        self.assertIn("LIMIT %S",sql)
        self.assertEqual(m.MAX_STOCKS,2)
        self.assertEqual(m.MAX_SOURCE_CALLS,10)
        self.assertEqual(m.MAX_DB_BYTES,800_000_000)
        self.assertNotIn("UPDATE PUBLIC.DAILY_PRICES",sql)
        # market_data_refresh_state has an existing constrained last_status enum.
        self.assertNotIn('long-history-success',m.run.__code__.co_consts)
        self.assertNotIn('long-history-failed',m.run.__code__.co_consts)
