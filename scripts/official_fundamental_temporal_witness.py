"""Independent genuine-market-session PIT source anti-leakage audit.

Never infer original issuer publication time from fiscal/report-table dates.
Old snapshots first observed at an actual 2026-11-21 capture cannot be
backdated to a 2022/2025 research signal. Read-only, twice-witnessed.
"""
from __future__ import annotations
from datetime import datetime
import json
import os
from pathlib import Path
import sys

import psycopg
from psycopg.rows import dict_row

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.official_fundamental_pit_coverage import (
    FUNDAMENTAL_ASOF_SQL,actual_signal_cutoff,audit_report,TAIPEI
)

EARLIEST_SQL="""SELECT LEAST(
 (SELECT MIN(first_observed_at) FROM public.official_quarterly_income_observations),
 (SELECT MIN(first_observed_at) FROM public.official_balance_sheet_observations),
 (SELECT MIN(first_observed_at) FROM public.official_revenue_observations)
) AS earliest"""
EARLIEST_PER_SOURCE_SQL="""SELECT
 (SELECT MIN(first_observed_at) FROM public.official_quarterly_income_observations) AS income,
 (SELECT MIN(first_observed_at) FROM public.official_balance_sheet_observations) AS balance,
 (SELECT MIN(first_observed_at) FROM public.official_revenue_observations) AS revenue"""
PRE_FIRST_SOURCE_DAY_SQL="""SELECT MAX(trade_date) AS signal_day FROM public.daily_prices
WHERE trade_date<%s AND close>0"""
LATEST_REAL_DAY_SQL="""SELECT MAX(trade_date) AS signal_day FROM public.daily_prices
WHERE close>0"""

def verify_pre_first_seen(old_report,earliest,signal):
    if (not isinstance(earliest,datetime) or earliest.tzinfo is None
        or signal>=earliest.astimezone(TAIPEI)):
        raise ValueError("A genuine earlier signal cutoff must precede all archives")
    t=old_report["totals"]
    names=("observed_income","observed_balance","observed_revenue",
           "all_three_sources_observed","safe_eps_and_balance",
           "current_ratio_research_possible","debt_to_assets_research_possible")
    if any(t[k]!=0 for k in names):
        raise RuntimeError("Future-observed official fundamentals leaked into past signal")
    if not old_report["source_dates_based_on_first_observed_at"]:
        raise RuntimeError("Source visibility is not based on actual first observed time")
    if old_report["cashflow_source_verified"] or old_report["roe_verified"]:
        raise RuntimeError("Unproven fundamental factors were promoted")
    return True

def audit(url,*,report_path=None):
    if not url:
        raise ValueError("Protected existing read-only DATABASE_URL required")
    with psycopg.connect(url,connect_timeout=20,row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout='30000ms'")
        captured=conn.execute(EARLIEST_PER_SOURCE_SQL).fetchone()
        seen=dict(captured)
        if any(v is None or v.tzinfo is None for v in seen.values()):
            raise RuntimeError("Missing actual first-observed official fundamental source")
        earliest=min(seen.values())
        dbnow=conn.execute("SELECT clock_timestamp() AS db_now").fetchone()["db_now"]
        pre_date=conn.execute(PRE_FIRST_SOURCE_DAY_SQL,(
            earliest.astimezone(TAIPEI).date(),)).fetchone()["signal_day"]
        last_date=conn.execute(LATEST_REAL_DAY_SQL).fetchone()["signal_day"]
        if pre_date is None or last_date is None:
            raise RuntimeError("No genuine earlier or latest market signal session")
        old_cutoff=actual_signal_cutoff(pre_date,server_now=dbnow)
        current_cutoff=actual_signal_cutoff(last_date,server_now=dbnow)
        if old_cutoff>=earliest.astimezone(TAIPEI):
            raise RuntimeError("Past fundamental witness not earlier than first seen")
        def at_cutoff(day):
            rows=conn.execute(FUNDAMENTAL_ASOF_SQL,(day,)*6).fetchall()
            return audit_report([dict(v) for v in rows],cutoff=day)
        historical=at_cutoff(old_cutoff)
        current=at_cutoff(current_cutoff)
        verify_pre_first_seen(historical,earliest,old_cutoff)
    result={
      "schema_version":1,
      "scope":"TWSE_TPEX_OFFICIAL_FUNDAMENTALS_FIRST_OBSERVED_TEMPORAL_WITNESS",
      "first_observed_by_source_utc":{k:v.isoformat() for k,v in seen.items()},
      "historical_signal_cutoff":old_cutoff.isoformat(),
      "latest_actual_market_signal_cutoff":current_cutoff.isoformat(),
      "past_snapshot_joint_visible":historical["totals"]["all_three_sources_observed"],
      "past_snapshot_observed_income":historical["totals"]["observed_income"],
      "past_snapshot_observed_balance":historical["totals"]["observed_balance"],
      "past_snapshot_observed_revenue":historical["totals"]["observed_revenue"],
      "latest_snapshot_joint_visible":current["totals"]["all_three_sources_observed"],
      "historical_before_first_seen_vintage_leakage_zero":True,
      "archive_first_observed_cutoff_enforced":True,
      "issuer_original_publication_timestamp_independently_verified":False,
      "historical_retroactive_fundamental_backtest_approved":False,
      "new_model_features_or_predictions_applied":False,
      "database_writes":False,"LINE_messages_sent":False,
      "trading_approved":False,"paid_services_requested":False
    }
    if report_path:
        p=Path(report_path)
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return result

def main():
    import argparse
    p=argparse.ArgumentParser(description="Read-only historical official first-seen fundamental leakage witness")
    p.add_argument("--report",type=Path,default=Path("official-pit-temporal-witness.json"))
    args=p.parse_args()
    v=audit(os.getenv("DATABASE_URL",""),report_path=args.report)
    print(json.dumps(v,ensure_ascii=False))

if __name__=="__main__":
    main()
