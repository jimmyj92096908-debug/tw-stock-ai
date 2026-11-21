"""Guarded one-time TWSE long-horizon date backfill toward five-year source and 240-session research.

Uses existing independently dated official MI_INDEX importer and tracked
progress. Only missing price PKs are inserted, never updates raw prices,
creates fake holidays, publishes LINE messages or enables trading.
Default preview runs SELECT only; applying requires two explicit gates.
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from twse_dated_history import run as source_run, has_source_write_budget

MAX_ROUNDS = 14
MAX_DAYS_PER_ROUND = 8
MAX_DATABASE_BYTES = 800_000_000
LOOKBACK_DAYS = 1830

STATE_SQL = """
SELECT count(*)::bigint AS raw_twse_rows,
       count(*) FILTER(WHERE close IS NOT NULL)::bigint AS valid_twse_rows,
       count(*) FILTER(WHERE source='TWSE_MI_INDEX_ALLBUT0999')::bigint AS source_rows,
       count(DISTINCT trade_date)
           FILTER(WHERE source='TWSE_MI_INDEX_ALLBUT0999')::int AS source_days,
       (SELECT pg_database_size(current_database())::bigint) AS database_bytes
FROM public.daily_prices
WHERE market='twse'
"""


def snapshot(url):
    if not url:
        raise ValueError("Protected DATABASE_URL required")
    with psycopg.connect(url, connect_timeout=20, row_factory=dict_row) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        result = dict(conn.execute(STATE_SQL).fetchone())
    for key in ("raw_twse_rows","valid_twse_rows","source_rows",
                "source_days","database_bytes"):
        if type(result.get(key)) is not int or result[key] < 0:
            raise RuntimeError("Unverifiable TWSE snapshot count")
    if result["database_bytes"] >= MAX_DATABASE_BYTES:
        raise RuntimeError("Free Neon storage guard reached")
    if result["valid_twse_rows"] > result["raw_twse_rows"] or (
        result["source_rows"] > result["raw_twse_rows"]):
        raise RuntimeError("Invalid TWSE snapshot subset")
    return result


def save(path, evidence):
    if not path:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    temp.replace(path)


def inspect_batch(rows, *, already_seen):
    if len(rows) > MAX_DAYS_PER_ROUND:
        raise RuntimeError("Unexpected unbounded TWSE source batch")
    seen = set()
    inserted = 0
    for row in rows:
        day = row["trade_date"]
        if (not isinstance(day,str) or day in seen or day in already_seen
                or row["status"] not in ("imported","closed")
                or not isinstance(row["qualified"],int)
                or not isinstance(row["inserted"],int)
                or not 0 <= row["inserted"] <= row["qualified"] <= 1500):
            raise RuntimeError("Unverified TWSE source date batch evidence")
        seen.add(day)
        inserted += row["inserted"]
    return inserted, seen


def execute(url, *, apply=False, max_rounds=MAX_ROUNDS, report_path=None):
    if type(max_rounds) is not int or not 0 <= max_rounds <= MAX_ROUNDS:
        raise ValueError("Unsafe TWSE long-history batch count")
    if apply and (
        max_rounds < 1 or
        os.environ.get("STOCK_TWSE_LONG_HISTORY_CAMPAIGN_ENABLED") != "yes" or
        os.environ.get("STOCK_TWSE_HISTORY_WRITE_ENABLED") != "yes"
    ):
        raise ValueError("Two explicit verified TWSE source write gates required")
    initial = snapshot(url)
    report = {
        "schema_version":1,
        "scope":"TWSE_DATE_VERIFIED_LONG_HORIZON_RESEARCH_ONLY",
        "created_utc":datetime.now(timezone.utc).isoformat(),
        "baseline":initial,"latest":initial,"batches":[],
        "raw_prices_overwritten":False,"line_messages_sent":False,
        "trading_enabled":False,"paid_upgrade_requested":False,
        "finished":False,"capacity_guard_blocked":False,
    }
    save(report_path,report)
    if not apply:
        return report
    if initial["source_days"] < 100:
        raise RuntimeError("Insufficient known TWSE official dated history")

    previous=initial
    seen=set()
    empty_batches=0
    for number in range(1,max_rounds+1):
        if not has_source_write_budget(previous["database_bytes"], days=MAX_DAYS_PER_ROUND):
            report["capacity_guard_blocked"]=True
            report["finished"]=False
            save(report_path,report)
            raise RuntimeError("TWSE source campaign blocked by Neon Free maintenance reserve")
        result=source_run(url,apply=True,batch_days=MAX_DAYS_PER_ROUND,
                          lookback_days=LOOKBACK_DAYS,pause_seconds=2)
        if not result:
            report["finished"]=True
            save(report_path,report)
            break
        inserted,dates=inspect_batch(result,already_seen=seen)
        seen.update(dates)
        current=snapshot(url)
        if current["valid_twse_rows"]-previous["valid_twse_rows"] != inserted:
            raise RuntimeError("Official TWSE inserted-row reconciliation failed")
        if (current["raw_twse_rows"]<previous["raw_twse_rows"] or
            current["source_rows"]<previous["source_rows"] or
            current["source_days"]<previous["source_days"]):
            raise RuntimeError("TWSE history regressed during backfill")
        empty_batches=empty_batches+1 if inserted==0 else 0
        report["batches"].append({
            "round":number, "dates":len(result),
            "official_qualified_sum":sum(x["qualified"] for x in result),
            "new_valid_bars":inserted,
            "closed_sessions":sum(x["status"]=="closed" for x in result),
            "source_days_after":current["source_days"],
        })
        report["latest"]=current
        save(report_path,report)
        if empty_batches>=2:
            raise RuntimeError("Repeated zero-insert TWSE source days; investigate official session")
        previous=current
    else:
        # The capped batch is exhausted, not the rolling five-year backlog.
        # Only an empty source selection proves every eligible date was examined.
        report["finished"]=False
    save(report_path,report)
    return report


def main():
    parser=argparse.ArgumentParser(description="Bounded no-overwrite TWSE historical source campaign")
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--max-rounds",type=int,default=MAX_ROUNDS)
    parser.add_argument("--report",type=Path,default=Path("twse-long-history-evidence.json"))
    args=parser.parse_args()
    report=execute(os.environ.get("DATABASE_URL",""),apply=args.apply,
                   max_rounds=args.max_rounds,report_path=args.report)
    print(json.dumps({
        "scope":report["scope"],"rounds":len(report["batches"]),
        "new_valid_bars":sum(x["new_valid_bars"] for x in report["batches"]),
        "source_days":report["latest"]["source_days"],
        "finished":report["finished"],
        "trading_enabled":False,"line_messages_sent":False,
    },ensure_ascii=False))


if __name__=="__main__":
    main()
