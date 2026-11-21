"""Read-only research availability of official income, balance, revenue as-of.

No source backdate, financial ratio backtest, model update, LINE, or trades.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import sys

import psycopg
from psycopg.rows import dict_row

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.official_fundamental_pit_coverage import (
    FUNDAMENTAL_ASOF_SQL, actual_signal_cutoff, audit_report,
)

LATEST_REAL_MARKET_SQL = """
SELECT MAX(trade_date) AS day FROM public.daily_prices WHERE close>0
"""
VALID_MARKET_SESSION_SQL = """
SELECT EXISTS(SELECT 1 FROM public.daily_prices
 WHERE trade_date=%s AND close>0) AS observed
"""


def run(database_url, *, day=None, report_path=None):
    if not database_url:
        raise ValueError("An existing protected read-only Neon URL is required")
    with psycopg.connect(database_url,connect_timeout=15,row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cur.execute("SET LOCAL statement_timeout='25000ms'")
                cur.execute("SELECT clock_timestamp() AS now")
                server_now=cur.fetchone()["now"]
                cur.execute(LATEST_REAL_MARKET_SQL)
                last_day=cur.fetchone()["day"]
                selected=day or last_day
                if isinstance(selected,str):
                    selected=date.fromisoformat(selected)
                if type(selected) is not date or last_day is None or selected>last_day:
                    raise ValueError("Signal day must be an actual already observed market day")
                cutoff=actual_signal_cutoff(selected,server_now=server_now)
                cur.execute(VALID_MARKET_SESSION_SQL,(selected,))
                if cur.fetchone()["observed"] is not True:
                    raise ValueError("Cannot label weekend/holiday a genuine market signal")
                cur.execute(FUNDAMENTAL_ASOF_SQL,(cutoff,cutoff,cutoff,cutoff,cutoff,cutoff))
                rows=[dict(r) for r in cur.fetchall()]
                report=audit_report(rows,cutoff=cutoff)
                report["latest_observed_market_date"]=last_day.isoformat()
    if report_path:
        path=Path(report_path)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return report


def main():
    p=argparse.ArgumentParser(description="Real official fundamentals first-seen PIT only")
    p.add_argument("--as-of",type=date.fromisoformat,default=None)
    p.add_argument("--out",type=Path,default=Path("official-fundamental-pit-audit.json"))
    args=p.parse_args()
    report=run(os.getenv("DATABASE_URL",""),day=args.as_of,report_path=args.out)
    print(json.dumps({
        "as_of":report["as_of_taipei"],
        "full_master":report["totals"]["stock_master"],
        "first_seen_income":report["totals"]["observed_income"],
        "first_seen_balance":report["totals"]["observed_balance"],
        "first_seen_revenue":report["totals"]["observed_revenue"],
        "joint_visible":report["totals"]["all_three_sources_observed"],
        "no_backdate":report["source_dates_based_on_first_observed_at"],
        "cashflow_coverage":report["cashflow_source_verified"],
        "live_trading_approved":report["live_trading_approved"],
    },ensure_ascii=False))


if __name__=="__main__":
    main()
