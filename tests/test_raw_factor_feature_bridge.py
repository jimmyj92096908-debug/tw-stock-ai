"""Causal raw market features are formula-reproduced, not existing Ridge scores."""
from __future__ import annotations

from datetime import date,timedelta
import math
from unittest import TestCase
from unittest.mock import MagicMock,patch

from src.raw_factor_feature_bridge import (
    build_research_features,validate_source,MIN_WARMUP_SESSIONS,
    OFFICIAL_SOURCE_TAGS,FEATURE_NAMES
)
from scripts import tpex_raw_feature_preview as live

def bars(n=320,*,stock="5520"):
    start=date(2025,1,2)
    output=[]
    for i in range(n):
        day=start+timedelta(days=i)
        # never fabricate weekends in *production*. These unit fixture dates
        # are synthetic and do not assert that a particular day was traded.
        close=100+0.1*i+math.sin(i/7)
        high=close+2
        low=close-2
        output.append({
          "market":"tpex","stock_id":stock,"trade_date":day,
          "open":close-0.4,"high":high,"low":low,"close":close,
          "volume":1000+i*4,"turnover":int(close*(1000+i*4)),
          "price_change":None,"transactions":100,
          "source":"TPEX_DATED_OTC_EW"
        })
    return output

class CausalRawFactorBridgeTests(TestCase):
    def test_real_source_indicator_equivalence_with_and_without_future_suffix(self):
        rows=bars()
        asof=rows[-1]["trade_date"]
        first_signal=rows[270]["trade_date"]
        report=build_research_features(rows,stock_id="5520",cutoff=asof,
            signal_dates=[first_signal,rows[-1]["trade_date"]])
        prefix=build_research_features(rows[:271],stock_id="5520",cutoff=first_signal,
                                      signal_dates=[first_signal])
        self.assertEqual(report["included_signals"],2)
        self.assertEqual(prefix["included_signals"],1)
        self.assertEqual(report["signals"][0]["feature_vector"],
                         prefix["signals"][0]["feature_vector"])
        self.assertEqual(len(FEATURE_NAMES),len(report["signals"][0]["feature_vector"]))
        self.assertTrue(report["causal_raw_price_calculators_reused"])
        self.assertTrue(report["corporate_actions_not_applied_to_features"])
        self.assertTrue(report["incompatible_with_existing_composite_score_ridge_feature_schema"])
        self.assertFalse(report["holdout_independently_verified"])
        self.assertFalse(report["source_capture_vintage_at_old_signals_independently_proven"])
        self.assertFalse(report["live_trading_approved"])
        self.assertEqual(report["database_write_operations"],0)
        self.assertEqual(report["signals"][0]["source_session_index"],270)
        self.assertFalse(report["signals"][0]["label_or_forward_price_observed"])

    def test_all_raw_volume_sources_preserve_relative_volume_with_verified_normalization(self):
        data=bars()
        sample=build_research_features(data,stock_id="5520",cutoff=data[-1]["trade_date"],
                 signal_dates=[data[-1]["trade_date"]])
        for p in data:
            p["source"]="TPEX_TRADING_STOCK"
            p["volume"]/=1000
            p["turnover"]/=1000
        normalized=build_research_features(data,stock_id="5520",
                cutoff=data[-1]["trade_date"],
                signal_dates=[data[-1]["trade_date"]])
        assert "TPEX_TRADING_STOCK" in OFFICIAL_SOURCE_TAGS
        self.assertAlmostEqual(sample["signals"][0]["feature_vector"][6],
                               normalized["signals"][0]["feature_vector"][6],places=9)

    def test_missing_sessions_excluded_not_imputed(self):
        data=bars()
        report=build_research_features(data,stock_id="5520",cutoff=data[-1]["trade_date"],
                 signal_dates=[data[200]["trade_date"],date(2025,1,1)])
        self.assertEqual(report["included_signals"],0)
        self.assertEqual(len(report["excluded_signal_days"]),2)
        self.assertEqual(
          {p["reason"] for p in report["excluded_signal_days"]},
          {"insufficient_real_warmup_sessions","not_a_real_saved_stock_trading_session"})

    def test_bad_origins_and_future_prices_never_admitted(self):
        data=bars()
        cutoff=data[-1]["trade_date"]
        for corrupted in (
           data+[dict(data[-1])],
           data[:-1]+[{**data[-1],"trade_date":cutoff+timedelta(days=1)}],
           [dict(data[0],stock_id="9999")]+data[1:],
           [dict(data[0],source="SCRAPED_UNKNOWN")]+data[1:],
           [dict(data[0],close=float("nan"))]+data[1:],
           [dict(data[0],high=10)]+data[1:],
           [dict(data[0],volume=-1)]+data[1:],
        ):
            with self.subTest(corrupted=corrupted[0]),self.assertRaises(ValueError):
                validate_source(corrupted,stock_id="5520",cutoff=cutoff)
        for codes in (["9999"],[cutoff,cutoff],[cutoff+timedelta(days=1)]):
            with self.assertRaises(ValueError):
                build_research_features(data,stock_id="5520",cutoff=cutoff,signal_dates=codes)
        with self.assertRaises(ValueError):
            build_research_features(bars(1601),stock_id="5520",
                                    cutoff=date(2030,1,1),signal_dates=[cutoff])
        with self.assertRaises(ValueError):
            build_research_features(data,stock_id="1808",cutoff=cutoff,signal_dates=[cutoff])

    def test_official_twse_source_recalculates_causally_without_writing(self):
        data=[dict(item,market="twse",stock_id="2330",
                   source="TWSE_MI_INDEX_ALLBUT0999") for item in bars(320)]
        cutoff=data[-1]["trade_date"]
        first=data[270]["trade_date"]
        full=build_research_features(data,stock_id="2330",market="twse",
                                     cutoff=cutoff,signal_dates=[first,cutoff])
        truncated=build_research_features(data[:271],stock_id="2330",market="twse",
                                          cutoff=first,signal_dates=[first])
        self.assertEqual(full["market"],"twse")
        self.assertEqual(full["signals"][0]["market"],"twse")
        self.assertEqual(full["included_signals"],2)
        self.assertEqual(full["signals"][0]["feature_vector"],
                         truncated["signals"][0]["feature_vector"])
        self.assertEqual(full["database_write_operations"],0)
        self.assertFalse(full["holdout_independently_verified"])
        self.assertFalse(full["live_trading_approved"])
        for wrong in (
            [dict(data[0],source="TPEX_DATED_OTC_EW")]+data[1:],
            [dict(data[0],market="tpex")]+data[1:],
        ):
            with self.assertRaises(ValueError):
                build_research_features(wrong,stock_id="2330",market="twse",
                                        cutoff=cutoff,signal_dates=[cutoff])
        with self.assertRaises(ValueError):
            build_research_features(data,stock_id="2330",market="fake",
                                    cutoff=cutoff,signal_dates=[cutoff])

    def test_readonly_neon_adapter_uses_most_recent_not_earliest_limit(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        data=bars()
        signals=[r["trade_date"] for r in data[-3:]]
        def dispatch(sql,*params):
            result=MagicMock()
            if sql==live.MASTER_SQL:
                result.fetchone.return_value={"in_current_master":True}
            if sql==live.LAST_SOURCE_SQL:
                result.fetchall.return_value=data
            if sql==live.SIGNAL_SQL:
                result.fetchall.return_value=[
                    {"trade_date":d} for d in reversed(signals)]
            return result
        conn.execute.side_effect=dispatch
        with patch.object(live.psycopg,"connect",return_value=conn) as connected:
            result=live.preview("protected",stock_id="5520",cutoff=data[-1]["trade_date"])
        self.assertEqual(result["included_signals"],3)
        self.assertIn("default_transaction_read_only=on",connected.call_args.kwargs["options"])
        self.assertIn("REPEATABLE READ READ ONLY",conn.execute.call_args_list[0].args[0])
        self.assertIn("ORDER BY trade_date DESC LIMIT %s",live.LAST_SOURCE_SQL)
        self.assertIn("ORDER BY trade_date",live.LAST_SOURCE_SQL)
        self.assertNotIn("UPDATE",live.LAST_SOURCE_SQL.upper())
        self.assertNotIn("INSERT",live.LAST_SOURCE_SQL.upper())
        with self.assertRaises(ValueError):
            live.preview("",stock_id="5520",cutoff=data[-1]["trade_date"])
