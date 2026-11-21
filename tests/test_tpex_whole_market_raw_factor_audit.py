"""Whole-current-TPEx raw source -> in-memory technical/SMC audit regressions."""
from datetime import date,timedelta
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock,patch

from scripts import tpex_whole_market_raw_factor_audit as m
from src.raw_factor_feature_bridge import FEATURE_NAMES,build_research_features

ROOT=Path(__file__).resolve().parents[1]

def raw(sid,*,n=320,first=date(2025,1,1)):
    rows=[]
    for i in range(n):
        x=40+i*.05+(i%7)*.3
        rows.append({
            "market":"tpex","stock_id":sid,
            "trade_date":first+timedelta(days=i),
            "open":x-.3,"high":x+1.0,"low":x-1.0,"close":x,
            "volume":1000+i*3,"turnover":int((1000+i*3)*x),
            "source":"TPEX_DATED_OTC_EW"})
    return rows

def master(*,day,active=("1742","1777")):
    result=[]
    for i in range(898):
        sid=str(1000+i)
        valid=320 if sid in active else 18
        result.append({"stock_id":sid,"valid_source_days":valid,
            "invalid_source_tags":0,"last_source_day":day,
            "legacy_monthly_rows":0,"source_nonquoted_rows":0,
            "persisted_technical_rows":19,
            "persisted_smc_rows":19,
            "persisted_adjusted_rows":19})
    return result

class WholeMarketSourceFactorTests(TestCase):
    def test_stable_full_universe_maturity_and_derived_deficit_are_separate(self):
        day=raw("1742")[-1]["trade_date"]
        table=master(day=day)
        candidates,buckets=m.classify(table,market_last=day)
        self.assertEqual(candidates,["1742","1777"])
        self.assertEqual(buckets["below_240_valid_days"],896)
        self.assertEqual(buckets["mature_and_quoted_on_latest_market_day"],2)
        self.assertEqual(buckets["persisted_smc_rows_has_fewer_rows_than_raw"],2)
        self.assertEqual(buckets["persisted_adjusted_rows_has_fewer_rows_than_raw"],2)
        bad=[dict(x) for x in table]
        bad[0]["stock_id"]=bad[1]["stock_id"]
        with self.assertRaises(ValueError):
            m.classify(bad,market_last=day)
        bad=[dict(x) for x in table]
        bad[0]["invalid_source_tags"]=-1
        with self.assertRaises(ValueError):
            m.classify(bad,market_last=day)
        extra=[dict(x) for x in table]
        extra[0]["source_nonquoted_rows"]=10
        _,count=m.classify(extra,market_last=day)
        self.assertEqual(count["nonquoted_original_price_rows_excluded_not_imputed"],10)

    def test_raw_factor_matches_existing_core_and_is_causal_on_prior_day(self):
        p=raw("1742")
        end=p[-1]["trade_date"]
        output=m.calculate_issuer(p,sid="1742",cutoff=end,do_prefix_test=True)
        earlier=m.calculate_issuer(p[:-1],sid="1742",
                                   cutoff=p[-2]["trade_date"],do_prefix_test=False)
        direct=build_research_features(p,stock_id="1742",cutoff=end,
                                      signal_dates=[end])["signals"][0]
        self.assertEqual(output["feature_vector"],direct["feature_vector"])
        self.assertEqual(output["feature_names"],list(FEATURE_NAMES))
        self.assertEqual(len(output["raw_source_sha256"]),64)
        self.assertTrue(output["prior_date_future_suffix_leakage_test_passed"])
        self.assertNotEqual(output["raw_source_sha256"],earlier["raw_source_sha256"])
        self.assertFalse(output["cash_dividend_adjusted_total_return_features"])
        self.assertFalse(output["existing_0_to_100_score_schema_compatible"])
        self.assertFalse(output["live_trading_approved"])
        corrupted=raw("1742")
        corrupted[-1]["source"]="UNKNOWN_SCRAPER"
        with self.assertRaises(ValueError):
            m.calculate_issuer(corrupted,sid="1742",cutoff=end)
        with self.assertRaises(ValueError):
            m.calculate_issuer(p,sid="1742",cutoff=p[-2]["trade_date"])

    def test_whole_market_readonly_candidate_pagination_and_disclosures(self):
        histories={sid:raw(sid) for sid in ("1742","1777")}
        day=histories["1742"][-1]["trade_date"]
        records=master(day=day)
        conn=MagicMock()
        conn.__enter__.return_value=conn
        def dispatch(sql,params=None):
            result=MagicMock()
            if sql==m.META_SQL:
                result.fetchone.return_value={
                    "last_market_day":day,"db_bytes":529465344}
            if sql==m.STOCK_COUNTS_SQL:
                self.assertEqual(params,(day,day,day,day))
                result.fetchall.return_value=records
            if sql==m.BARS_SQL:
                self.assertEqual(params[:2],(day,m.BARS_PER_STOCK))
                result.fetchall.return_value=[
                    x for sid in params[2] for x in histories[sid]]
            return result
        conn.execute.side_effect=dispatch
        with patch.object(m.psycopg,"connect",return_value=conn) as c:
            report=m.inspect("existing-protected-url")
        self.assertEqual(report["current_master_stocks"],898)
        self.assertEqual(report["eligible_original_source_stock_count"],2)
        self.assertEqual(report["raw_factor_reconstructed_stock_count"],2)
        self.assertEqual(report["raw_factor_failed_stock_count"],0)
        self.assertEqual(report["stocks_with_latest_market_day_feature"],2)
        self.assertEqual(report["prefix_leakage_samples_passed"],1)
        self.assertEqual(report["original_source_bars_fetched"],640)
        self.assertEqual(report["database_writes"],0)
        self.assertFalse(report["pristine_holdout_model_alpha_proven"])
        self.assertFalse(report["model_or_LINE_live_trading_approved"])
        self.assertTrue(report["all_eligible_current_master_stocks_reconstructed"])
        self.assertIn("default_transaction_read_only=on",
                      c.call_args.kwargs["options"])
        self.assertIn("REPEATABLE READ READ ONLY",
                      conn.execute.call_args_list[0].args[0])
        self.assertIn("AND p.close>0 AND p.volume>=0",m.BARS_SQL)
        self.assertTrue(report["no_trade_or_null_close_rows_never_invented_or_forward_filled"])
        self.assertEqual(
            len([x for x in conn.execute.call_args_list if x.args[0]==m.BARS_SQL]),1)
        for sql in (m.META_SQL,m.STOCK_COUNTS_SQL,m.BARS_SQL):
            self.assertNotIn("UPDATE public.",sql.upper())
            self.assertNotIn("INSERT INTO",sql.upper())
            self.assertNotIn("DELETE FROM",sql.upper())

    def test_ledger_keeps_bad_source_stock_in_failure_not_silent_exclusion(self):
        day=raw("1742")[-1]["trade_date"]
        records=master(day=day)
        conn=MagicMock()
        conn.__enter__.return_value=conn
        def dispatch(sql,params=None):
            result=MagicMock()
            if sql==m.META_SQL:
                result.fetchone.return_value={"last_market_day":day,
                                              "db_bytes":529465344}
            elif sql==m.STOCK_COUNTS_SQL:
                result.fetchall.return_value=records
            elif sql==m.BARS_SQL:
                all_rows=[]
                for sid in params[2]:
                    values=raw(sid)
                    if sid=="1777":
                        values[-1]["source"]="UNVERIFIED_SOURCE"
                    all_rows.extend(values)
                result.fetchall.return_value=all_rows
            return result
        conn.execute.side_effect=dispatch
        with patch.object(m.psycopg,"connect",return_value=conn):
            evidence=m.inspect("existing-protected-url")
        self.assertEqual(evidence["raw_factor_reconstructed_stock_count"],1)
        self.assertEqual(evidence["raw_factor_failed_stock_count"],1)
        self.assertFalse(evidence["all_eligible_current_master_stocks_reconstructed"])
        self.assertEqual(evidence["source_calculation_errors"][0]["stock_id"],"1777")

    def test_one_shot_real_neon_run_has_no_paid_cron_or_writes(self):
        w=(ROOT/".github/workflows/tpex-whole-market-raw-factor-validation.yml").read_text()
        self.assertIn("  push:",w)
        self.assertIn("  workflow_dispatch:",w)
        self.assertIn(".github/tpex-whole-market-raw-factor-one-shot-20261121.txt",w)
        self.assertIn("git diff --name-only --diff-filter=A HEAD^ HEAD",w)
        self.assertIn("tpex_whole_market_raw_factor_audit.py",w)
        self.assertNotIn("  schedule:",w)
        self.assertNotIn("STOCK_TPEX_DATED_HISTORY_WRITE_ENABLED",w)
        self.assertNotIn("LINE_CHANNEL_ACCESS_TOKEN",w)
        self.assertNotIn("--apply",w)
