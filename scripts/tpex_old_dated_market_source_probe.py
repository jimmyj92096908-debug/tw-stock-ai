"""Two-date read-only TPEx historical MARKET-WIDE official source probe.

Probe actual old official requested days against ≥10 independently stored
same-date closes. Never INSERT/UPDATE/DELETE, never infer trading dates.
This tests feasibility of scalable multi-year source, not production approval.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from datetime import date,datetime,timezone
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

import psycopg

from official_snapshot_ingest import load_allowed,select_candidates
from tpex_dated_history import fetch_day,verify_source_date

DAYS=(date(2025,12,31),date(2022,12,30))
MAX_DATE_REQUESTS=2
MIN_INDEPENDENT_STOCKS=10
SIZE_SQL="SELECT pg_database_size(current_database())::bigint"
COUNT_SQL="""SELECT COUNT(*)::int FROM public.daily_prices
WHERE market='tpex' AND trade_date=%s AND close>0 AND volume>=0"""


def source_day_evidence(conn,day,fetcher=fetch_day):
    if day not in DAYS:
        raise ValueError("Unknown unapproved fixed official source date")
    with conn.cursor() as cur:
        cur.execute(COUNT_SQL,(day,))
        existing=cur.fetchone()[0]
    if existing<MIN_INDEPENDENT_STOCKS:
        raise ValueError("Fewer than ten independently stored old TPEx stock closes")
    official=fetcher(day)
    allowed=load_allowed(conn)
    required=max(500,int(sum(1 for m,sid in allowed if m=="tpex")*.6))
    qualified=select_candidates(official["bars"],allowed,minimum=required)
    proof=verify_source_date(conn,day,qualified)
    return {"date":day.isoformat(),"stored_independent_closes":existing,
            "qualified_official_market_stocks":len(qualified),
            "same_date_compared":proof["compared"],
            "exact_matching_closes":proof["matched"],
            "different_closes":proof["mismatched"],
            "source_verified":proof["compared"]>=10 and
                proof["matched"]*100>=98*proof["compared"]}


def run(url,*,report_path=None,fetcher=fetch_day):
    if not url:
        raise ValueError("Existing protected read-only DATABASE_URL required")
    if len(DAYS)!=MAX_DATE_REQUESTS:
        raise ValueError("Unsafe unbounded historical source date requests")
    with psycopg.connect(url,connect_timeout=15,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        conn.execute("SET LOCAL statement_timeout='20000ms'")
        with conn.cursor() as cur:
            cur.execute(SIZE_SQL)
            db_bytes=cur.fetchone()[0]
        if db_bytes>=800_000_000:
            raise RuntimeError("Free Neon capacity guard; refusing even probe")
        results=[]
        for day in DAYS:
            try:
                entry=source_day_evidence(conn,day,fetcher=fetcher)
                entry["status"]="verified" if entry["source_verified"] else "rejected"
            except Exception as exc:
                # Keep a self-contained safe source-quality failure record.
                entry={"date":day.isoformat(),"status":"rejected",
                       "error_type":type(exc).__name__,"source_verified":False}
            results.append(entry)
    report={"schema_version":1,"created_utc":datetime.now(timezone.utc).isoformat(),
            "scope":"TPEX_TWO_OLD_DATED_OFFICIAL_MARKET_READ_ONLY",
            "official_dates_requested":len(results),
            "max_date_requests":MAX_DATE_REQUESTS,
            "database_bytes_before":db_bytes,
            "database_read_only":True,
            "raw_prices_modified":False,"factor_scores_modified":False,
            "LINE_messages_sent":False,"trading_enabled":False,
            "paid_upgrade_requested":False,
            "all_old_dates_verified":all(x.get("source_verified",False) for x in results),
            "results":results}
    if report_path:
        output=Path(report_path)
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return report


def main():
    import argparse
    cli=argparse.ArgumentParser(description="Read-only TPEx old dated market-wide source probe")
    cli.add_argument("--report",type=Path,default=Path("tpex-old-dated-market-source-proof.json"))
    a=cli.parse_args()
    x=run(os.getenv("DATABASE_URL",""),report_path=a.report)
    print(json.dumps(x,ensure_ascii=False))
    # Reject a false-green provenance conclusion; preserve the artifact.
    if not x["all_old_dates_verified"]:
        raise SystemExit("Old historical market-wide TPEx source NOT fully verified")


if __name__=="__main__":
    main()
