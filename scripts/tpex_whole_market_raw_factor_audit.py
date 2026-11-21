"""All-current-TPEx-source-stock RAW technical/SMC feature reproducibility.

Read a bounded last 320 ACTUAL trading bars per eligible issuer, calculate
the *existing* raw technical & SMC indicators in memory, no factor table
materialization, no model release and no inference about delisted issuers.

No backfilled source retrieved_at vintage proof, cash total return or historical
independent held-out model alpha is implied by passing this audit.
"""
from __future__ import annotations

from collections import Counter,defaultdict
from datetime import date,datetime,timezone
from hashlib import sha256
import argparse,json,os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from src.raw_factor_feature_bridge import (
    FEATURE_NAMES,VERSION,MIN_WARMUP_SESSIONS,build_research_features
)

MAX_STOCKS=900
BARS_PER_STOCK=320
PAGE_SIZE=20
MAX_PAGES=45
MAX_PREFIX_TESTS=20
SAFETY_STOP_BYTES=800_000_000

META_SQL="""SELECT
(SELECT MAX(trade_date) FROM public.daily_prices
 WHERE market='tpex' AND close>0) AS last_market_day,
pg_database_size(current_database())::bigint AS db_bytes"""
STOCK_COUNTS_SQL="""WITH raw AS (
 SELECT stock_id,
 COUNT(*) FILTER(WHERE close>0 AND volume>=0)::int AS valid_source_days,
 COUNT(*) FILTER(WHERE source NOT IN (
  'TPEX_DATED_OTC_EW','TPEX_DAILY_CLOSE_OPENAPI',
  'TPEX_TRADING_STOCK','TPEX_TRADING_STOCK_NORMALIZED'))::int AS invalid_source_tags,
 MAX(trade_date) FILTER(WHERE close>0 AND volume>=0) AS last_source_day,
 COUNT(*) FILTER(WHERE source='TPEX_TRADING_STOCK')::int AS legacy_monthly_rows,
 COUNT(*) FILTER(WHERE close IS NULL OR close<=0 OR volume IS NULL
  OR volume<0)::int AS source_nonquoted_rows
 FROM public.daily_prices WHERE market='tpex' AND trade_date<=%s
 GROUP BY stock_id
),tech AS(
 SELECT stock_id,COUNT(*)::int AS n FROM public.daily_technicals
 WHERE market='tpex' AND trade_date<=%s GROUP BY stock_id
),smc AS(
 SELECT stock_id,COUNT(*)::int AS n FROM public.daily_smc
 WHERE market='tpex' AND trade_date<=%s GROUP BY stock_id
),adjusted AS(
 SELECT stock_id,COUNT(*)::int AS n FROM public.daily_adjusted_prices
 WHERE market='tpex' AND trade_date<=%s GROUP BY stock_id
)
SELECT m.stock_id,
 COALESCE(raw.valid_source_days,0)::int AS valid_source_days,
 COALESCE(raw.invalid_source_tags,0)::int AS invalid_source_tags,
 raw.last_source_day,
 COALESCE(raw.legacy_monthly_rows,0)::int AS legacy_monthly_rows,
 COALESCE(raw.source_nonquoted_rows,0)::int AS source_nonquoted_rows,
 COALESCE(tech.n,0)::int AS persisted_technical_rows,
 COALESCE(smc.n,0)::int AS persisted_smc_rows,
 COALESCE(adjusted.n,0)::int AS persisted_adjusted_rows
FROM public.stock_master m
LEFT JOIN raw ON raw.stock_id=m.stock_id
LEFT JOIN tech ON tech.stock_id=m.stock_id
LEFT JOIN smc ON smc.stock_id=m.stock_id
LEFT JOIN adjusted ON adjusted.stock_id=m.stock_id
WHERE m.market='tpex'
ORDER BY m.stock_id"""
BARS_SQL="""SELECT b.market,b.stock_id,b.trade_date,b.open,b.high,b.low,b.close,
b.volume,b.turnover,b.price_change,b.transactions,b.source
FROM public.stock_master m
CROSS JOIN LATERAL (
 SELECT market,stock_id,trade_date,open,high,low,close,volume,
 turnover,price_change,transactions,source
 FROM public.daily_prices p
 WHERE p.market='tpex' AND p.stock_id=m.stock_id
 AND p.trade_date<=%s
 AND p.close>0 AND p.volume>=0
 ORDER BY p.trade_date DESC LIMIT %s
) b
WHERE m.market='tpex' AND m.stock_id=ANY(%s)
ORDER BY b.stock_id,b.trade_date"""

def classify(master,*,market_last):
    if type(market_last) is not date or not isinstance(master,list) or (
        not 700<=len(master)<=MAX_STOCKS):
        raise ValueError("Real TPEx current master cohort and latest market date required")
    names=set()
    buckets=Counter()
    candidates=[]
    for row in master:
        sid=row.get("stock_id")
        n=row.get("valid_source_days")
        latest=row.get("last_source_day")
        unknown=row.get("invalid_source_tags")
        legacy=row.get("legacy_monthly_rows")
        if (not isinstance(sid,str) or not sid.isascii() or
            len(sid)!=4 or not sid.isdigit() or sid in names or
            any(type(row.get(k)) is not int or row[k]<0 for k in (
                "valid_source_days","invalid_source_tags","legacy_monthly_rows",
                "source_nonquoted_rows",
                "persisted_technical_rows","persisted_smc_rows",
                "persisted_adjusted_rows")) or (latest is not None and type(latest) is not date)
            or (n>0 and latest is None) or (latest is not None and latest>market_last)):
            raise ValueError("Invalid official stock-master or price-source maturity rows")
        names.add(sid)
        buckets["nonquoted_original_price_rows_excluded_not_imputed"]+=row[
            "source_nonquoted_rows"]
        if n<MIN_WARMUP_SESSIONS:
            buckets["below_240_valid_days"]+=1
            continue
        if unknown:
            buckets["unknown_original_source_unit"]+=1
            continue
        if latest!=market_last:
            buckets["mature_but_not_quoted_on_market_latest_day"]+=1
        else:
            buckets["mature_and_quoted_on_latest_market_day"]+=1
        if legacy:
            buckets["mature_with_legacy_monthly_unit_rows"]+=1
        candidates.append(sid)
        for field in ("persisted_technical_rows","persisted_smc_rows",
                      "persisted_adjusted_rows"):
            if row[field]<n:
                buckets[field+"_has_fewer_rows_than_raw"]+=1
    return sorted(candidates),dict(buckets)

def calculate_issuer(raw,*,sid,cutoff,do_prefix_test=False):
    if len(raw)>BARS_PER_STOCK:
        raise ValueError("Source input exceeds individual in-memory data bound")
    if not raw:
        raise ValueError("Stock source rows missing")
    latest=raw[-1]["trade_date"]
    if type(latest) is not date or latest>cutoff:
        raise ValueError("Stock latest source day not verified")
    current=build_research_features(raw,stock_id=sid,cutoff=latest,
                                    signal_dates=[latest])
    if current["included_signals"]!=1 or len(current["signals"])!=1:
        raise ValueError("Cannot calculate source-backed full 240-session feature")
    item=current["signals"][0]
    if item["as_of_date"]!=latest.isoformat() or (
        len(item["feature_vector"])!=len(FEATURE_NAMES)):
        raise RuntimeError("Raw source and feature signal dates do not agree")
    # A full original source fingerprint is used in the sample audit receipt.
    stamp=current["raw_source_fingerprint_sha256"]
    if not isinstance(stamp,str) or len(stamp)!=64:
        raise ValueError("Unreproducible daily source SHA256")
    prefix_validated=None
    if do_prefix_test:
        prior=raw[-2]["trade_date"]
        if type(prior) is not date:
            raise ValueError("Missing real previous source session")
        # Compare a prior signal with vs without a later quote. The
        # later-day quote is never allowed to affect the prior feature vector.
        complete=build_research_features(raw,stock_id=sid,cutoff=latest,
                                          signal_dates=[prior])
        before=build_research_features(raw[:-1],stock_id=sid,cutoff=prior,
                                        signal_dates=[prior])
        if (complete["included_signals"]!=1 or before["included_signals"]!=1
            or complete["signals"][0]["feature_vector"]!=
               before["signals"][0]["feature_vector"]):
            raise RuntimeError("Source technical or SMC lookahead in prior signal")
        prefix_validated=True
    return {
        "stock_id":sid,"latest_source_session":latest.isoformat(),
        "input_original_bars":len(raw),"raw_source_sha256":stamp,
        "feature_version":VERSION,"feature_names":list(FEATURE_NAMES),
        "feature_vector":item["feature_vector"],
        "prior_date_future_suffix_leakage_test_passed":prefix_validated,
        "cash_dividend_adjusted_total_return_features":False,
        "historical_first_captured_source_vintage_proven":False,
        "historical_delisted_population_proven":False,
        "existing_0_to_100_score_schema_compatible":False,
        "live_trading_approved":False,
    }

def summarize(*,market_last,db_bytes,master,candidates,buckets,results,failed,prefix_checks):
    if (not isinstance(market_last,date) or type(db_bytes) is not int
        or db_bytes<=0 or db_bytes>=SAFETY_STOP_BYTES or
        len(results)+len(failed)!=len(candidates)):
        raise ValueError("Current raw factor run does not reconcile to bounded source cohort")
    ids=[r["stock_id"] for r in results]
    if len(ids)!=len(set(ids)):
        raise ValueError("Duplicate computed stock in source research proof")
    computed_current=sum(x["latest_source_session"]==market_last.isoformat()
                         for x in results)
    if prefix_checks!=sum(x["prior_date_future_suffix_leakage_test_passed"] is True
                          for x in results):
        raise RuntimeError("True no-leakage sample tests do not reconcile")
    completed=len(results)
    return {
        "schema_version":1,"scope":"TPEX_ALL_CURRENT_MASTER_CAUSAL_RAW_FACTOR_IN_MEMORY_AUDIT",
        "cutoff_market_day":market_last.isoformat(),
        "current_master_stocks":len(master),
        "minimum_real_source_warmup_sessions":MIN_WARMUP_SESSIONS,
        "eligible_original_source_stock_count":len(candidates),
        "raw_factor_reconstructed_stock_count":completed,
        "raw_factor_failed_stock_count":len(failed),
        "stocks_with_latest_market_day_feature":computed_current,
        "historical_factor_reconstruction_is_on_demand":True,
        "no_trade_or_null_close_rows_never_invented_or_forward_filled":True,
        "persists_no_adjusted_technical_smc_daily_rows":True,
        "latest_day_stored_factors_still_may_be_stale":True,
        "source_maturity_breakdown":buckets,
        "prefix_leakage_samples_passed":prefix_checks,
        "source_calculation_errors":failed,
        "factor_version":VERSION,
        "feature_names":list(FEATURE_NAMES),
        "original_source_bars_fetched":sum(x["input_original_bars"] for x in results),
        "database_bytes":db_bytes,
        "database_hard_safety_stop_bytes":SAFETY_STOP_BYTES,
        "all_eligible_current_master_stocks_reconstructed":not failed,
        "corporate_action_disclosure_vintage_verified":False,
        "features_are_dividend_adjusted_total_return":False,
        "delisted_and_suspended_historic_universe_proven":False,
        "old_ridge_scored_feature_schema_compatible":False,
        "pristine_holdout_model_alpha_proven":False,
        "model_or_LINE_live_trading_approved":False,
        "database_writes":0,
        "additional_paid_services_required":False,
    }

def inspect(url,*,report_path=None):
    if not url:
        raise ValueError("Existing protected Neon DATABASE_URL required")
    with psycopg.connect(url,connect_timeout=20,row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout='150000ms'")
        meta=dict(conn.execute(META_SQL).fetchone())
        market_last=meta.get("last_market_day")
        size=meta.get("db_bytes")
        if type(market_last) is not date or type(size) is not int or size>=SAFETY_STOP_BYTES:
            raise RuntimeError("Missing real market session or insufficient Neon free budget")
        master=[dict(r) for r in conn.execute(
            STOCK_COUNTS_SQL,(market_last,)*4).fetchall()]
        candidates,buckets=classify(master,market_last=market_last)
        if len(candidates)>MAX_STOCKS or (
            len(candidates)+buckets.get("below_240_valid_days",0)+
            buckets.get("unknown_original_source_unit",0)!=len(master)):
            raise ValueError("Candidate source cohort or excluded universe counts are incoherent")
        results=[]
        failures=[]
        prefix_checks=0
        requested=0
        for start in range(0,len(candidates),PAGE_SIZE):
            if requested>=MAX_PAGES:
                raise RuntimeError("Bounded market batch pages exceeded")
            page=candidates[start:start+PAGE_SIZE]
            requested+=1
            raw_rows=[dict(x) for x in conn.execute(
                BARS_SQL,(market_last,BARS_PER_STOCK,page)).fetchall()]
            grouped=defaultdict(list)
            for raw in raw_rows:
                if raw["stock_id"] not in page:
                    raise ValueError("Cross-issuer raw price leakage")
                grouped[raw["stock_id"]].append(raw)
            for sid in page:
                check=(len(results)+len(failures))%42==0 and (
                    prefix_checks<MAX_PREFIX_TESTS)
                try:
                    item=calculate_issuer(grouped.get(sid,[]),sid=sid,
                          cutoff=market_last,do_prefix_test=check)
                    results.append(item)
                    prefix_checks+=int(item["prior_date_future_suffix_leakage_test_passed"] is True)
                except (ValueError,RuntimeError,KeyError,TypeError,OverflowError) as exc:
                    failures.append({"stock_id":sid,"failure_type":type(exc).__name__,
                        "error_code":"SOURCE_MISSING_OR_FEATURE_REPRODUCTION_FAILED"})
    report=summarize(market_last=market_last,db_bytes=size,master=master,
                     candidates=candidates,buckets=buckets,
                     results=results,failed=failures,prefix_checks=prefix_checks)
    report["read_only_snapshot_completed_utc"]=datetime.now(timezone.utc).isoformat()
    report["per_stock_proofs"]=results
    # Do not flood GitHub logs or send any per-stock investment ranking.
    if report_path:
        target=Path(report_path)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(report,ensure_ascii=False,allow_nan=False,
                                     separators=(",",":"),default=str)+"\n",encoding="utf-8")
    return report

def main():
    p=argparse.ArgumentParser(description="All current TPEx 240+ session source to raw AI factors without persisted rows")
    p.add_argument("--report",type=Path,default=Path("tpex-all-market-raw-factor-proof.json"))
    args=p.parse_args()
    report=inspect(os.getenv("DATABASE_URL",""),report_path=args.report)
    print(json.dumps({k:report[k] for k in (
        "current_master_stocks","eligible_original_source_stock_count",
        "raw_factor_reconstructed_stock_count","raw_factor_failed_stock_count",
        "stocks_with_latest_market_day_feature","prefix_leakage_samples_passed",
        "original_source_bars_fetched","database_writes",
        "pristine_holdout_model_alpha_proven")},ensure_ascii=False))
    if report["raw_factor_failed_stock_count"] or not report["prefix_leakage_samples_passed"]:
        raise SystemExit("Fail closed: source or formula maturity audit incomplete")

if __name__=="__main__":
    main()
