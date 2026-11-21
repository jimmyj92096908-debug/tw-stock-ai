"""Two-stage postflight TPEx derived-only history repair; NEVER daily_prices.

Manual preview by default. Apply only under BOTH source writer lock and existing
indicator mutex after the five-year official raw-price campaign is finished.
Resumable per stock; raw price aggregate fingerprint unchanged before/after.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
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
from tpex_stale_factor_refresh import (
    choose,raw_proof,verify_derived,verify_latest_score,
    STAMP_VERIFIED_SCORE_SQL,
)
from twse_240_release_gate import snapshot as release_snapshot

MAX_STOCKS=3
MAX_EXAMINED=20
MAX_BATCH_RAW_ROWS=5000
MAX_PER_STOCK_ROWS=1600
SAFETY_STOP_BYTES=800_000_000
MIN_FREE_BUFFER=40_000_000
# Worst-case per-source-row extra bytes when fully upserting 3 derived tables.
# Larger than currently observed aggregate physical per-day footprint.
GUARDED_REWRITE_BYTES_PER_RAW_ROW=3000
MIN_OFFICIAL_DATED_DAYS=100
MIN_ELIGIBLE_STOCKS=700
SIZE_SQL="SELECT pg_database_size(current_database())::bigint AS bytes"

def space_safe(bytes_used,raw_rows):
    if (type(bytes_used) is not int or bytes_used<1 or
        type(raw_rows) is not int or raw_rows<1 or raw_rows>MAX_BATCH_RAW_ROWS):
        raise ValueError("Unverifiable source size or bounded derived-write volume")
    return bytes_used+MIN_FREE_BUFFER+raw_rows*GUARDED_REWRITE_BYTES_PER_RAW_ROW<SAFETY_STOP_BYTES

def select_budgeted(candidates,limit=MAX_STOCKS):
    if type(limit) is not int or not 1<=limit<=MAX_STOCKS:
        raise ValueError("Bounded TPEx derived target limit must be 1..3")
    if not isinstance(candidates,list) or len(candidates)>MAX_EXAMINED:
        raise RuntimeError("Unverifiable bounded factor backlog")
    accepted=[]
    count=0
    seen=set()
    for s in candidates:
        sid=s.get("stock_id")
        rows=s.get("price_rows")
        valid=s.get("valid_days")
        if (not isinstance(sid,str) or not sid.isdigit() or
            type(rows) is not int or type(valid) is not int or
            rows<60 or valid<60 or valid>rows or sid in seen):
            raise ValueError("Invalid TPEx stock candidate or duplicate")
        seen.add(sid)
        if rows>MAX_PER_STOCK_ROWS or count+rows>MAX_BATCH_RAW_ROWS:
            continue
        if len(accepted)>=limit:
            break
        if not s.get("last_valid") or not s.get("last_source_write"):
            # Source provenance is mandatory for real repair.
            continue
        accepted.append(s)
        count+=rows
    return accepted,count

def preflight(gate):
    keys=("tpex_source_days","tpex_eligible","database_bytes",
          "bad_legacy_volume","bad_legacy_turnover")
    if not isinstance(gate,dict) or any(type(gate.get(k)) is not int for k in keys):
        raise ValueError("Source and raw-unit quality proof is missing")
    if (gate["tpex_source_days"]<MIN_OFFICIAL_DATED_DAYS or
        gate["tpex_eligible"]<MIN_ELIGIBLE_STOCKS or
        gate["bad_legacy_volume"]!=0 or gate["bad_legacy_turnover"]!=0 or
        gate["database_bytes"]>=SAFETY_STOP_BYTES-MIN_FREE_BUFFER):
        raise RuntimeError("Source cohort, source units or Neon Free headroom failed")
    # DO NOT gate on latest matched==eligible, since missing latest score is
    # exactly one reason for targeted recomputation.
    return True

def size(conn):
    with conn.cursor() as cur:
        cur.execute(SIZE_SQL)
        value=cur.fetchone()["bytes"]
    if type(value) is not int or value<0:
        raise ValueError("Neon size value invalid")
    return value

def save(path,report):
    if path is not None:
        target=Path(path)
        target.parent.mkdir(parents=True,exist_ok=True)
        temp=target.with_suffix(target.suffix+".tmp")
        temp.write_text(json.dumps(report,ensure_ascii=False,default=str,indent=2)+"\n",encoding="utf-8")
        temp.replace(target)

def execute(url,*,apply=False,limit=MAX_STOCKS,report_path=None):
    if not url:
        raise ValueError("Existing protected DATABASE_URL is required")
    if type(limit) is not int or not 1<=limit<=MAX_STOCKS:
        raise ValueError("Strict TPEx derived batch limit 1..3")
    if apply and any(os.environ.get(flag)!="yes" for flag in (
        "STOCK_TPEX_POSTFLIGHT_DERIVED_ENABLED",
        "STOCK_INDICATOR_CATCHUP_WRITE_ENABLED",
        "STOCK_TPEX_STALE_SCORE_WRITE_ENABLED"
    )):
        raise PermissionError("Three explicit derived-and-score-only write gates required")
    gate=release_snapshot(url)
    preflight(gate)
    report={
        "schema_version":1,"scope":"TPEX_FIVE_YEAR_DERIVED_ONLY_SMALL_BATCH",
        "checked_at_utc":datetime.now(timezone.utc).isoformat(),
        "apply":bool(apply),"source_days":gate["tpex_source_days"],
        "eligible_stocks":gate["tpex_eligible"],
        "stock_limit":limit,"examined_limit":MAX_EXAMINED,
        "raw_price_keys_modified":False,"raw_price_values_modified":False,
        "LINE_messages_sent":False,"trading_enabled":False,
        "paid_plan_requested":False,"complete":False,
        "selected_stocks":[],"repaired_stocks":[]
    }
    save(report_path,report)
    options=None if apply else "-c default_transaction_read_only=on"
    with psycopg.connect(url,connect_timeout=20,row_factory=dict_row,
                         options=options) as conn:
        # Read-only preview and preflight share exactly the same source chooser.
        pending=choose(conn,limit=MAX_EXAMINED)
        selected,rows=select_budgeted(pending,limit)
        bytes_before=size(conn)
        if selected and not space_safe(bytes_before,rows):
            raise RuntimeError("Projected derived upsert would violate Free 800MB guard")
        report["selected_stocks"]=[{"stock_id":s["stock_id"],
                                    "raw_price_days":s["price_rows"],
                                    "last_valid":s["last_valid"]}
                                   for s in selected]
        report["selected_raw_days"]=rows
        report["estimated_buffer_bytes"]=rows*GUARDED_REWRITE_BYTES_PER_RAW_ROW
        report["db_bytes_before"]=bytes_before
        report["candidate_backlog_first_window"]=len(pending)
        report["canary_preview_passes_guards"]=bool(selected and
                                                    space_safe(bytes_before,rows))
        save(report_path,report)
        if not apply:
            return report
        # All actual writes are disabled on preview, and manual workflow
        # dispatch MUST serialize against both running source and score jobs.
        conn.commit()
        for stock in selected:
            sid=stock["stock_id"]
            current=size(conn)
            if not space_safe(current,stock["price_rows"]):
                raise RuntimeError("No safe free-capacity margin for selected stock")
            before=raw_proof(conn,sid)
            conn.commit()
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("SET LOCAL statement_timeout='120000ms'")
                adj=build_adjusted(conn,"tpex",sid)
                tech=build_technicals(conn,"tpex",sid)
                smc=build_smc(conn,"tpex",sid)
                if min(adj,tech,smc)<stock["price_rows"]:
                    raise RuntimeError("Missing historical dated source-derived rows")
                verify_derived(conn,stock)
            conn.commit()
            # Composite calculator reuses a separate existing audited connection.
            scored=calculate_all(url,stocks=[("tpex",sid)],missing_only=False)
            if scored!=1:
                raise RuntimeError("Expected exactly one stock-scoped research score")
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(STAMP_VERIFIED_SCORE_SQL,(sid,stock["last_valid"]))
                verify_latest_score(conn,stock)
            conn.commit()
            after=raw_proof(conn,sid)
            if before!=after:
                raise RuntimeError("Source OHLCV fingerprint changed; refuse completion")
            after_bytes=size(conn)
            if after_bytes>=SAFETY_STOP_BYTES-MIN_FREE_BUFFER:
                raise RuntimeError("Neon Free headroom fell below minimum post-stock margin")
            conn.commit()
            report["repaired_stocks"].append({
                "stock_id":sid,"raw_price_days":before["rows"],
                "adjusted_rows":adj,"technical_rows":tech,
                "smc_rows":smc,"latest_score_recomputed":True,
                "source_fingerprint_unchanged":True,
                "database_bytes_after":after_bytes
            })
            save(report_path,report)
    report["complete"]=bool(not pending)
    report["global_historical_factor_100_percent_verified"]=False
    report["five_year_per_stock_source_verified"]=False
    save(report_path,report)
    return report

def main():
    p=argparse.ArgumentParser(description="Manual gated source-safe TPEx derived batches")
    p.add_argument("--apply",action="store_true")
    p.add_argument("--limit",type=int,default=MAX_STOCKS)
    p.add_argument("--report",type=Path,default=Path("tpex-derived-postflight.json"))
    args=p.parse_args()
    r=execute(os.getenv("DATABASE_URL",""),apply=args.apply,
              limit=args.limit,report_path=args.report)
    print(json.dumps({
        "scope":r["scope"],"apply":r["apply"],
        "selected_stocks":len(r["selected_stocks"]),
        "repaired_stocks":len(r["repaired_stocks"]),
        "raw_price_keys_modified":False,"orders_enabled":False,
        "LINE_messages_sent":False
    },ensure_ascii=False))

if __name__=="__main__":
    main()
