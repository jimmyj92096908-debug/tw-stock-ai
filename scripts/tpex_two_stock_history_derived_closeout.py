"""Restore full TPEx historical-factor acceptance after the 2-stock source pilot.

Provenance-scoped DERIVED-ONLY reconciliation for 5520 and 6762.
No price INSERT/UPDATE, schema migrations, LINE or trading. One-shot opt-in.
Requires 140 newly absent official monthly adjusted rows to account for ALL
legacy unit audit errors, and restores strict 879/879 historical factor gate.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import sys

import psycopg
from psycopg.rows import dict_row

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(ROOT/"scripts"))
from build_adjusted_prices import build as build_adjusted
from calculate_technicals import calculate_stock as build_technicals
from calculate_smc import calculate_stock as build_smc
from composite_score import calculate_all
from twse_240_release_gate import snapshot
from tpex_stale_factor_refresh import (
    raw_proof,verify_derived,verify_latest_score,STAMP_VERIFIED_SCORE_SQL
)
from tpex_legacy_derived_repair import VERIFY_SQL as LEGACY_VERIFY_SQL

STOCKS=("5520","6762")
EXPECTED_INITIAL_HISTORICAL_COMPLETE=877
EXPECTED_ELIGIBLE=879
MAX_DB_BYTES=800_000_000

GLOBAL_RAW_SQL="""
SELECT COUNT(*)::bigint n,
 COALESCE(SUM(volume),0)::numeric volume_sum,
 COALESCE(SUM(turnover),0)::numeric turnover_sum,
 MIN(trade_date) first_trade_date,
 MAX(trade_date) last_trade_date
FROM public.daily_prices WHERE market='tpex'
"""
STOCK_SQL="""
SELECT COUNT(*)::int price_rows,
 COUNT(*) FILTER(WHERE source='TPEX_TRADING_STOCK')::int official_monthly_rows,
 MAX(trade_date) latest_date,MIN(trade_date) first_date
FROM public.daily_prices
WHERE market='tpex' AND stock_id=%s
"""

def verify_scope(state,claims):
    if (state["database_bytes"]>=MAX_DB_BYTES or
        state["tpex_source_days"]<80 or
        state["tpex_eligible"]!=EXPECTED_ELIGIBLE or
        state["tpex_matched"]!=EXPECTED_ELIGIBLE or
        state["tpex_historical_factors_current"]!=EXPECTED_INITIAL_HISTORICAL_COMPLETE):
        raise RuntimeError("Unexpected TPEx 879-stock research gate or Neon free capacity")
    if len(claims)!=len(STOCKS) or {x["stock_id"] for x in claims}!=set(STOCKS):
        raise RuntimeError("Invalid fixed TPEx source cohort")
    if any(x["price_rows"]<120 or x["official_monthly_rows"]<60 or
           x["legacy_bad_volume"]<1 or x["legacy_bad_turnover"]<1
           for x in claims):
        raise RuntimeError("Verified long-history source or missing derived evidence absent")
    if (sum(x["legacy_bad_volume"] for x in claims)!=state["bad_legacy_volume"] or
        sum(x["legacy_bad_turnover"] for x in claims)!=state["bad_legacy_turnover"]):
        raise RuntimeError("Non-target TPEx raw source unit errors; stop instead of bypassing gate")
    return True


def read_evidence(url):
    gate=snapshot(url)
    with psycopg.connect(url,connect_timeout=15,row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout='20000ms'")
        global_raw=dict(conn.execute(GLOBAL_RAW_SQL).fetchone())
        claims=[]
        for sid in STOCKS:
            source=dict(conn.execute(STOCK_SQL,(sid,)).fetchone())
            legacy=dict(conn.execute(LEGACY_VERIFY_SQL,(sid,)).fetchone())
            claims.append({"stock_id":sid,**source,
                           "legacy_bad_volume":legacy["bad_volume"],
                           "legacy_bad_turnover":legacy["bad_turnover"]})
    verify_scope(gate,claims)
    return gate,claims,global_raw


def perform(url,*,apply=False,report_path=None):
    if not url:
        raise ValueError("Existing protected DATABASE_URL required")
    if apply and (
        os.getenv("STOCK_TPEX_TWO_STOCK_DERIVED_CLOSEOUT_ENABLED")!="yes" or
        os.getenv("STOCK_INDICATOR_CATCHUP_WRITE_ENABLED")!="yes" or
        os.getenv("STOCK_TPEX_STALE_SCORE_WRITE_ENABLED")!="yes"
    ):
        raise PermissionError("Three production derived-only write gates required")
    before,stocks,raw_before=read_evidence(url)
    report={
       "schema_version":1,
       "scope":"VERIFIED_TWO_STOCK_TPEX_LONG_HISTORY_DERIVED_ONLY",
       "recorded_at_utc":datetime.now(timezone.utc).isoformat(),
       "apply":bool(apply),"source_stocks":list(STOCKS),
       "initial_full_historical_factors":before["tpex_historical_factors_current"],
       "initial_legacy_source_missing_adjusted_volume":before["bad_legacy_volume"],
       "initial_legacy_source_missing_adjusted_turnover":before["bad_legacy_turnover"],
       "source_proof":[{"stock_id":x["stock_id"],"price_days":x["price_rows"],
                        "legacy_monthly_source_days":x["official_monthly_rows"],
                        "missing_derived_volume":x["legacy_bad_volume"],
                        "missing_derived_turnover":x["legacy_bad_turnover"]}
                       for x in stocks],
       "reconciled":[],"complete":False,
       "raw_prices_modified":False,"line_messages_sent":False,
       "orders_enabled":False,"paid_plan_requested":False
    }
    def persist():
        if report_path is not None:
            dest=Path(report_path)
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    persist()
    if not apply:
        return report
    with psycopg.connect(url,connect_timeout=15,row_factory=dict_row) as conn:
        for target in stocks:
            sid=target["stock_id"]
            proof_before=raw_proof(conn,sid)
            conn.commit()
            stock={"stock_id":sid,"price_rows":target["price_rows"],
                   "last_valid":target["latest_date"]}
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("SET LOCAL statement_timeout='120000ms'")
                adjusted=build_adjusted(conn,"tpex",sid)
                technical=build_technicals(conn,"tpex",sid)
                smc=build_smc(conn,"tpex",sid)
                if min(adjusted,technical,smc)<target["price_rows"]:
                    raise RuntimeError("Missing per-day adjusted/technical/SMC source history")
                verify_derived(conn,stock)
            conn.commit()
            processed=calculate_all(url,stocks=[("tpex",sid)],missing_only=False)
            if processed!=1:
                raise RuntimeError("Exactly one fixed-stock latest composite must be recalculated")
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(STAMP_VERIFIED_SCORE_SQL,(sid,target["latest_date"]))
                verify_latest_score(conn,stock)
            conn.commit()
            proof_after=raw_proof(conn,sid)
            if proof_before!=proof_after:
                raise RuntimeError("Prohibited original TPEx OHLCV source change detected")
            conn.commit()
            report["reconciled"].append({
                "stock_id":sid,"adjusted_days":adjusted,
                "technical_days":technical,"smc_days":smc,
                "latest_score_recomputed":True,
                "raw_prices_modified":False
            })
            persist()
        raw_after=dict(conn.execute(GLOBAL_RAW_SQL).fetchone())
        conn.commit()
    if raw_after!=raw_before:
        raise RuntimeError("All-TPEx raw price fingerprint changed during derived closeout")
    after=snapshot(url)
    report["final_full_historical_factors"]=after["tpex_historical_factors_current"]
    report["final_matched"]=after["tpex_matched"]
    report["final_bad_legacy_volume"]=after["bad_legacy_volume"]
    report["final_bad_legacy_turnover"]=after["bad_legacy_turnover"]
    report["complete"]=bool(
        after["tpex_historical_factors_current"]==EXPECTED_ELIGIBLE and
        after["tpex_matched"]==EXPECTED_ELIGIBLE and
        after["tpex_eligible"]==EXPECTED_ELIGIBLE and
        after["bad_legacy_volume"]==0 and after["bad_legacy_turnover"]==0 and
        after["database_bytes"]<MAX_DB_BYTES
    )
    persist()
    if not report["complete"]:
        raise RuntimeError("Fail closed: actual Neon 879/879 factor quality not restored")
    return report


def main():
    arg=argparse.ArgumentParser(description="One-shot exact two-stock TPEx derived closeout")
    arg.add_argument("--apply",action="store_true")
    arg.add_argument("--report",type=Path,default=Path("tpex-long-history-derived-closeout.json"))
    args=arg.parse_args()
    result=perform(os.getenv("DATABASE_URL",""),apply=args.apply,report_path=args.report)
    print(json.dumps({"reconciled":len(result["reconciled"]),
                      "full_history_factor_gate_restored":result["complete"],
                      "raw_prices_modified":False,"orders_enabled":False,
                      "line_messages_sent":False},ensure_ascii=False))


if __name__=="__main__":
    main()
