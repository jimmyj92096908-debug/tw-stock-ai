"""No persistent derived-factor writes, and genuine first-seen PIT anti-leakage."""
from datetime import date,datetime,timedelta
import inspect
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock,patch
from zoneinfo import ZoneInfo

from scripts import tpex_on_demand_research as ondemand
from scripts import official_fundamental_temporal_witness as pit
from src.adjusted_prices import adjust_bars
from src.build_adjusted_prices import normalize_source_units
from src.technical_indicators import compute_indicators
from src.smc_indicators import compute_smc
from src.official_fundamental_pit_coverage import audit_report,actual_signal_cutoff

ROOT=Path(__file__).resolve().parents[1]

def bars(count=90, stock="5520"):
    start=date(2026,1,1)
    out=[]
    for i in range(count):
        day=start+timedelta(days=i)
        value=100+i/10
        out.append({"market":"tpex","stock_id":stock,"trade_date":day,
             "open":value-1,"high":value+2,"low":value-2,"close":value,
             "volume":1000+i,"turnover":int(value*(1000+i)),
             "price_change":0,"transactions":100,
             "source":"TPEX_DATED_OTC_EW"})
    return out

def actions(day):
    return [{"ex_date":day,"action_type":"cash_dividend","price_factor":0.95,
             "share_factor":1.0,"cash_amount":1,"stock_amount":0}]

def fake_market(market,n=1000,observed=0):
    return {"market":market,"stock_master":n,
      "observed_income":observed,"observed_balance":observed,
      "observed_revenue":observed,"quarterly_same_period":observed,
      "safe_eps_and_balance":observed,
      "debt_to_assets_research_possible":observed,
      "current_ratio_research_possible":observed,
      "all_three_sources_observed":observed,
      "accounting_identity_failures":0,
      "current_ratio_denominator_missing_or_zero":0}

class TPExOnDemandNoStorageTests(TestCase):
    def test_same_calculators_and_full_vintage_scope_explicit(self):
        source=bars(90)
        action=actions(source[42]["trade_date"])
        out=ondemand.evaluate(source,action,stock_id="5520",
                              cutoff=source[-1]["trade_date"],limit=3)
        adjusted=adjust_bars(normalize_source_units(source,"tpex"),action)
        t=compute_indicators(adjusted)
        s=compute_smc(adjusted)
        self.assertEqual(out["source_rows"],90)
        self.assertEqual(out["returned_rows"],3)
        self.assertEqual(out["latest_indicators"]["technical"]["rsi14"],t[-1]["rsi14"])
        self.assertEqual(out["latest_indicators"]["technical"]["ma55"],t[-1]["ma55"])
        self.assertEqual(out["latest_indicators"]["smc"]["trend_direction"],s[-1]["trend_direction"])
        self.assertEqual(out["latest_indicators"]["adjusted_close"],adjusted[-1]["close"])
        self.assertFalse(out["database_writes"])
        self.assertEqual(out["permanent_derived_rows_created"],0)
        self.assertFalse(out["corporate_action_publication_vintage_proven"])
        self.assertFalse(out["historical_backtest_or_alpha_approved"])
        self.assertFalse(out["trading_approved"])
        self.assertEqual(source[0]["close"],100)  # Original input not mutated.

    def test_strict_stock_session_and_corporate_action_cutoff(self):
        source=bars(25)
        last=source[-1]["trade_date"]
        for invalid in (source+[source[-1]],source[:-1]+[{**source[-1],"trade_date":last+timedelta(days=1)}],
                        [{**source[0],"stock_id":"9999"}]+source[1:]):
            with self.assertRaises(ValueError):
                ondemand.evaluate(invalid,[],stock_id="5520",cutoff=last)
        with self.assertRaises(ValueError):
            ondemand.evaluate(source,actions(last+timedelta(days=1)),stock_id="5520",cutoff=last)
        for limit in (0,21,True):
            with self.assertRaises(ValueError):
                ondemand.evaluate(source,[],stock_id="5520",cutoff=last,limit=limit)
        with self.assertRaises(ValueError):
            ondemand.evaluate(bars(1601),[],stock_id="5520",cutoff=date(2030,1,1))
        with self.assertRaises(ValueError):
            ondemand.run("",stock_id="5520",cutoff=last)

    def test_readonly_raw_and_verified_corporate_action_queries_only(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        source=bars(30)
        def query(sql,args=None):
            val=MagicMock()
            if sql==ondemand.STOCK_SQL:
                val.fetchone.return_value={"listed_in_current_master":True}
            elif sql==ondemand.PRICE_SQL:
                val.fetchall.return_value=source
            elif sql==ondemand.ACTION_SQL:
                val.fetchall.return_value=[]
            return val
        conn.execute.side_effect=query
        with patch.object(ondemand.psycopg,"connect",return_value=conn) as connect:
            x=ondemand.run("protected",stock_id="5520",
                           cutoff=source[-1]["trade_date"],limit=1)
        self.assertEqual(x["source_rows"],30)
        self.assertEqual(x["returned_rows"],1)
        self.assertIn("default_transaction_read_only=on",connect.call_args.kwargs["options"])
        self.assertIn("READ ONLY",conn.execute.call_args_list[0].args[0])
        for sql in (ondemand.PRICE_SQL,ondemand.ACTION_SQL):
            self.assertIn("<=%s",sql)
            self.assertTrue(sql.upper().lstrip().startswith("SELECT"))
        self.assertNotIn("INSERT INTO",inspect.getsource(ondemand))
        self.assertNotIn("UPDATE public.daily_prices",inspect.getsource(ondemand))

class FundamentalLiveTemporalAuditTests(TestCase):
    def test_mature_past_market_signal_never_has_future_first_observed(self):
        cutoff=actual_signal_cutoff("2026-11-20",server_now=datetime(
            2026,11,21,23,tzinfo=ZoneInfo("Asia/Taipei")))
        first=datetime(2026,11,21,14,5,tzinfo=ZoneInfo("Asia/Taipei"))
        original=audit_report([fake_market("twse"),fake_market("tpex")],cutoff=cutoff)
        self.assertTrue(pit.verify_pre_first_seen(original,first,cutoff))
        leaked=audit_report([fake_market("twse",observed=1),fake_market("tpex")],
                             cutoff=cutoff)
        with self.assertRaises(RuntimeError):
            pit.verify_pre_first_seen(leaked,first,cutoff)
        with self.assertRaises(ValueError):
            pit.verify_pre_first_seen(original,first,first)
        self.assertFalse(original["issuer_original_publication_time_known"])
        self.assertFalse(original["live_trading_approved"])

    def test_empty_source_or_missing_real_session_is_not_pit_certified(self):
        with self.assertRaises(ValueError):
            pit.audit("")
        self.assertIn("first_observed_at",pit.EARLIEST_SQL)
        self.assertIn("first_observed_at",pit.EARLIEST_PER_SOURCE_SQL)
        self.assertIn("trade_date<%s",pit.PRE_FIRST_SOURCE_DAY_SQL)
        self.assertIn("first_observed_at<=%s::timestamptz",pit.FUNDAMENTAL_ASOF_SQL)
        self.assertNotIn("UPDATE",pit.PRE_FIRST_SOURCE_DAY_SQL.upper())

    def test_no_paid_writes_and_workflow_automatic_after_monthly_archive(self):
        wf=(ROOT/".github/workflows/tpex-five-year-free-research-audits.yml").read_text()
        marker=".github/tpex-free-on-demand-pit-audit-20261121.txt"
        self.assertIn("  workflow_run:",wf)
        self.assertIn("Official Monthly Revenue First-Seen Archive (Research Only)",wf)
        self.assertIn("  push:",wf)
        self.assertIn(marker,wf)
        self.assertIn(".github/tpex-free-on-demand-pit-audit-v2-20261121.txt",wf)
        self.assertIn("for attempt in 1 2 3",wf)
        self.assertIn("if [ \"$attempt\" -eq 3 ]",wf)
        self.assertIn("sleep 5",wf)
        self.assertIn("git diff --name-only --diff-filter=A HEAD^ HEAD",wf)
        self.assertNotIn("  schedule:",wf)
        self.assertNotIn("STOCK_TPEX_DATED_HISTORY_WRITE_ENABLED",wf)
        self.assertNotIn("STOCK_OFFICIAL_REVENUE_ARCHIVE_WRITE",wf)
        self.assertIn("tpex_on_demand_research.py",wf)
        self.assertIn("official_fundamental_temporal_witness.py",wf)
        self.assertNotIn("--apply",wf)
