"""Independent read-only TPEx five-year ANCHORABLE market-date acceptance.

This cannot certify that every eligible stock traded for five years. It only
measures official dated all-market rows for previously observed TPEx sessions,
and flags derived factor staleness separately. Never writes or triggers trades.
"""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from scripts.tpex_five_year_market_backfill import floor_five_years,MAX_DB_BYTES
from scripts.twse_240_release_gate import snapshot

MIN_FULL_MARKET_ROWS=500
MIN_ANCHORED_SESSIONS=1100

SESSION_SQL="""
SELECT trade_date,
 COUNT(*) FILTER(WHERE close>0 AND volume>=0)::int AS valid_rows,
 COUNT(*) FILTER(WHERE close>0 AND volume>=0
 AND source='TPEX_DATED_OTC_EW')::int AS official_dated_rows,
 COUNT(*) FILTER(WHERE close>0 AND volume>=0
 AND source='TPEX_DAILY_CLOSE_OPENAPI')::int AS official_openapi_rows
FROM public.daily_prices
WHERE market='tpex' AND trade_date>=%s AND trade_date<=%s
GROUP BY trade_date ORDER BY trade_date
"""
SCOPE_SQL="""
SELECT MAX(trade_date) AS latest
FROM public.daily_prices
WHERE market='tpex' AND close>0
"""

def classify(rows):
    if not rows or len({x["trade_date"] for x in rows})!=len(rows):
        raise ValueError("Missing or duplicate historical market sessions")
    expected=[r for r in rows if r["valid_rows"]>=10]
    succeeded=[r for r in expected
       if max(r["official_dated_rows"],r["official_openapi_rows"])>=MIN_FULL_MARKET_ROWS]
    incomplete=[r["trade_date"].isoformat() for r in expected
       if max(r["official_dated_rows"],r["official_openapi_rows"])<MIN_FULL_MARKET_ROWS]
    return {"independent_anchored_dates":len(expected),
            "verified_official_full_market_dates":len(succeeded),
            "unverified_anchored_dates":len(incomplete),
            "recent_missing_date_examples":incomplete[-12:],
            "source_market_date_coverage_percent":round(
                100*len(succeeded)/len(expected),2) if expected else 0.0,
            "previously_observed_no_anchor":len(rows)-len(expected)}

def inspect(url,*,report_path=None):
    if not url:
        raise ValueError("Existing protected DATABASE_URL is required")
    state=snapshot(url)
    with psycopg.connect(url,connect_timeout=20,row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout='30000ms'")
        latest=conn.execute(SCOPE_SQL).fetchone()["latest"]
        if not latest:
            raise RuntimeError("No known official TPEx dated stock sessions")
        floor=floor_five_years(latest)
        rows=conn.execute(SESSION_SQL,(floor,latest)).fetchall()
    data=classify(rows)
    verdict=(
        data["independent_anchored_dates"]>=MIN_ANCHORED_SESSIONS and
        data["unverified_anchored_dates"]==0 and
        state["database_bytes"]<MAX_DB_BYTES and
        state["bad_legacy_volume"]==0 and
        state["bad_legacy_turnover"]==0
    )
    result={
       "schema_version":1,"scope":"TPEX_FIVE_YEAR_INDEPENDENT_KNOWN_MARKET_DATE_AUDIT",
       "checked_utc":datetime.now(ZoneInfo("UTC")).isoformat(),
       "latest_session":latest.isoformat(),"five_year_start":floor.isoformat(),
       **data,
       "all_known_anchored_market_dates_covered":verdict,
       "full_five_year_stock_by_stock_listing_history_verified":False,
       "historical_factor_stocks_current":state["tpex_historical_factors_current"],
       "historical_factor_stocks_eligible":state["tpex_eligible"],
       "historical_factors_fresh":state["tpex_historical_factors_current"]==state["tpex_eligible"],
       "bad_adjusted_source_volume_rows":state["bad_legacy_volume"],
       "bad_adjusted_source_turnover_rows":state["bad_legacy_turnover"],
       "database_bytes":state["database_bytes"],"database_safe_stop_bytes":MAX_DB_BYTES,
       "database_read_only":True,"raw_prices_modified":False,
       "LINE_messages_sent":False,"orders_enabled":False,"paid_upgrade_requested":False
    }
    if report_path:
        path=Path(report_path)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return result

def main():
    import argparse
    cli=argparse.ArgumentParser(description="Read-only 5-year TPEx market session source acceptance")
    cli.add_argument("--report",type=Path,default=Path("tpex-five-year-official-source-audit.json"))
    args=cli.parse_args()
    result=inspect(os.getenv("DATABASE_URL",""),report_path=args.report)
    print(json.dumps(result,ensure_ascii=False))
    if not result["all_known_anchored_market_dates_covered"]:
        raise SystemExit("TPEx five-year official anchored date-source audit incomplete")

if __name__=="__main__":
    main()
