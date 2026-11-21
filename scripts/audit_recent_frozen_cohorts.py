"""Evaluate at most twelve genuine frozen full-roster research days, no writes.

Use one trusted PostgreSQL REPEATABLE READ READ ONLY snapshot, the real latest
positive-close market day, and the original frozen t+1/t+6 source-label SQL.
"""
from __future__ import annotations

import argparse
from datetime import date,datetime
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.frozen_cohort_progress import DATES_SQL,MAX_DAYS,MODEL,summarize_progress
from src.research_forward_outcome import FROZEN_LABEL_SQL,assess_frozen_outcomes

LATEST_MARKET_SQL = "SELECT MAX(trade_date) AS latest FROM public.daily_prices WHERE close>0"
CLOCK_SQL = "SELECT clock_timestamp() AS db_now"


def run(url, *, limit=6, report_path=None):
    if not url:
        raise ValueError("Existing protected database URL required")
    if type(limit) is not int or not 1<=limit<=MAX_DAYS:
        raise ValueError("Bounded maximum twelve frozen cohorts required")
    with psycopg.connect(url,connect_timeout=15,row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cur.execute("SET LOCAL statement_timeout='25000ms'")
                cur.execute(CLOCK_SQL)
                database_now=cur.fetchone()["db_now"]
                cur.execute(LATEST_MARKET_SQL)
                last=cur.fetchone()["latest"]
                if (type(last) is not date or
                    last>database_now.astimezone(ZoneInfo("Asia/Taipei")).date()):
                    raise ValueError("Actual past or present official trading date required")
                cur.execute(DATES_SQL,(MODEL,last,limit))
                frozen=[r["signal_date"] for r in cur.fetchall()]
                reports=[]
                for signal_day in frozen:
                    cur.execute(FROZEN_LABEL_SQL,(MODEL,signal_day,last))
                    record=cur.fetchone()
                    if record is None:
                        raise RuntimeError("Archived immutable research cohort vanished")
                    reports.append(assess_frozen_outcomes(dict(record),cutoff=last))
                summary=summarize_progress(reports,market_date=last,limit=limit)
    if report_path:
        path=Path(report_path)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",
                        encoding="utf-8")
    return summary


def main():
    parser=argparse.ArgumentParser(description="Audit bounded prospective research-only model windows")
    parser.add_argument("--limit",type=int,default=6)
    parser.add_argument("--out",type=Path,
                        default=Path("prospective-frozen-progress-evidence.json"))
    a=parser.parse_args()
    result=run(os.getenv("DATABASE_URL",""),limit=a.limit,report_path=a.out)
    print(json.dumps({k:result[k] for k in (
        "latest_true_market_date","audited_frozen_days",
        "mature_full_cohorts","independent_nonoverlapping_complete_windows",
        "minimum_window_count_met_within_this_bounded_sample",
        "research_model_release_decision","line_signal_delivery_approved",
        "live_trading_approved"
    )},ensure_ascii=False))


if __name__=="__main__":
    main()
