"""Historical TPEx investible-universe evidence audit, strictly READ ONLY.

A current stock_master + today's backfilled raw price rows CANNOT establish
who was listed/delisted/tradable on every historical signal date. In particular,
an earliest observed price day is not an IPO effective date.
"""
from __future__ import annotations
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import psycopg
from psycopg.rows import dict_row

CURRENT_STOCK_COLUMNS_SQL="""SELECT column_name FROM information_schema.columns
WHERE table_schema='public' AND table_name='stock_master'
ORDER BY ordinal_position"""
HISTORY_SUMMARY_SQL="""WITH p AS (
 SELECT stock_id,MIN(trade_date) AS first_observed,
 MAX(trade_date) AS last_observed,COUNT(*)::int AS n
 FROM public.daily_prices WHERE market='tpex' AND close>0 AND volume>=0
 GROUP BY stock_id
),m AS (
 SELECT stock_id FROM public.stock_master WHERE market='tpex'
),latest AS(
 SELECT MAX(last_observed) AS latest_day FROM p
)
SELECT
 (SELECT COUNT(*)::int FROM m) AS current_master,
 (SELECT COUNT(*)::int FROM p) AS observed_price_stocks,
 COUNT(*) FILTER(WHERE p.stock_id IS NULL)::int AS current_master_no_price,
 (SELECT COUNT(*)::int FROM p
  LEFT JOIN m ON m.stock_id=p.stock_id
  WHERE m.stock_id IS NULL) AS price_stocks_not_in_current_master,
 COUNT(*) FILTER(WHERE p.first_observed>=latest.latest_day-interval '3 years')::int
  AS first_seen_last_three_years_NOT_VERIFIED_IPO,
 COUNT(*) FILTER(WHERE p.n>=1000)::int AS current_master_1000_price_rows,
 latest.latest_day AS last_real_market_day
FROM m LEFT JOIN p ON p.stock_id=m.stock_id CROSS JOIN latest
GROUP BY latest.latest_day"""
NONMASTER_SAMPLE_SQL="""WITH src AS(
 SELECT stock_id,MIN(trade_date) first_price_day,
 MAX(trade_date) last_price_day,COUNT(*)::int rows
 FROM public.daily_prices
 WHERE market='tpex' AND close>0 AND volume>=0
 GROUP BY stock_id
)
SELECT p.stock_id,p.first_price_day,p.last_price_day,p.rows
FROM src p LEFT JOIN public.stock_master m
ON m.market='tpex' AND m.stock_id=p.stock_id
WHERE m.stock_id IS NULL ORDER BY p.stock_id LIMIT 20"""
# The actual production stock_master has ONLY market,stock_id,stock_name,
# industry,updated_at (the last update date is NOT listing effective date).
REQUIRED_LISTING_FIELDS=frozenset({"listing_effective_date","delisting_effective_date"})

def evaluate(columns,summary,nonmaster_samples):
    if (not isinstance(columns,(tuple,list)) or not
        isinstance(summary,dict) or not isinstance(nonmaster_samples,list)):
        raise ValueError("Historical membership database evidence missing")
    column_set=set(columns)
    if not {"market","stock_id","stock_name","industry","updated_at"}.issubset(column_set):
        raise ValueError("Unexpected original stock_master schema")
    values=("current_master","observed_price_stocks","current_master_no_price",
            "price_stocks_not_in_current_master",
            "first_seen_last_three_years_NOT_VERIFIED_IPO",
            "current_master_1000_price_rows")
    if any(type(summary.get(k)) is not int or summary[k]<0 for k in values):
        raise ValueError("Invalid current stock vs source summary")
    if not 700<=summary["current_master"]<=5000:
        raise ValueError("Unexpected current source pool")
    if (summary["current_master_no_price"]>summary["current_master"] or
        summary["price_stocks_not_in_current_master"]>summary["observed_price_stocks"] or
        summary["current_master_1000_price_rows"]>summary["current_master"] or
        summary["first_seen_last_three_years_NOT_VERIFIED_IPO"]>
            summary["current_master"]):
        raise ValueError("Historically impossible source stock counts")
    if len(nonmaster_samples)>20 or any(
        not isinstance(s.get("stock_id"),str) for s in nonmaster_samples):
        raise ValueError("Non-master source sample is not bounded")
    if summary["price_stocks_not_in_current_master"]==0 and nonmaster_samples:
        raise ValueError("Source sample contradicts absent unknown member count")
    missing_cols=sorted(REQUIRED_LISTING_FIELDS-column_set)
    return {
        "scope":"TPEX_HISTORICAL_LISTING_UNIVERSE_READ_ONLY_GATE",
        "schema_version":1,
        "latest_real_price_day":str(summary["last_real_market_day"]),
        "today_master_stocks":summary["current_master"],
        "original_prices_distinct_stocks":summary["observed_price_stocks"],
        "current_master_without_saved_valid_price":summary["current_master_no_price"],
        "observed_price_stocks_not_in_today_master":
            summary["price_stocks_not_in_current_master"],
        "nonmaster_raw_price_example_count":len(nonmaster_samples),
        "nonmaster_raw_price_examples":nonmaster_samples,
        "current_master_stocks_with_1000_raw_rows":
            summary["current_master_1000_price_rows"],
        "recent_first_seen_not_proven_ipo":
            summary["first_seen_last_three_years_NOT_VERIFIED_IPO"],
        "missing_historic_listing_effective_date_fields":missing_cols,
        "current_master_updated_at_is_not_first_listing_date":True,
        "first_saved_price_is_not_exchange_ipo_date":True,
        "observed_price_stocks_not_in_today_master_is_not_a_complete_delisted_count":True,
        "original_as_of_listing_and_delisting_archive_proven":False,
        "historical_eligibility_date_by_date_verified":False,
        "historical_survivorship_free_investible_roster_approved":False,
        "backtest_exchange_wide_alpha_approved":False,
        "future_official_effective_date_archive_required":True,
        "database_writes":0,"LINE_messages_sent":False,
        "paid_services_requested":False,
    }

def require_historical_universe(report):
    if report.get("historical_survivorship_free_investible_roster_approved") is not True:
        raise PermissionError(
            "Must verify official listing/delisting effective dates and historical universe before historical strategy approval")
    return True

def inspect(url,*,report_path=None):
    if not url:
        raise ValueError("Existing protected DATABASE_URL required")
    with psycopg.connect(url,connect_timeout=20,row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout='45000ms'")
        columns=[r["column_name"] for r in
                 conn.execute(CURRENT_STOCK_COLUMNS_SQL).fetchall()]
        summary=dict(conn.execute(HISTORY_SUMMARY_SQL).fetchone())
        examples=[dict(r) for r in
                  conn.execute(NONMASTER_SAMPLE_SQL).fetchall()]
    report=evaluate(columns,summary,examples)
    report["checked_utc"]=datetime.now(timezone.utc).isoformat()
    if report_path is not None:
        target=Path(report_path)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(report,ensure_ascii=False,default=str,
                                     indent=2)+"\n",encoding="utf-8")
    return report

def main():
    import argparse
    p=argparse.ArgumentParser(description="Read-only survivorship/IPO/delisting market source evidence gate")
    p.add_argument("--report",type=Path,default=Path("tpex-historical-roster-audit.json"))
    a=p.parse_args()
    report=inspect(os.getenv("DATABASE_URL",""),report_path=a.report)
    print(json.dumps({k:report[k] for k in (
       "today_master_stocks","original_prices_distinct_stocks",
       "observed_price_stocks_not_in_today_master",
       "recent_first_seen_not_proven_ipo",
       "missing_historic_listing_effective_date_fields",
       "historical_survivorship_free_investible_roster_approved",
       "database_writes")},ensure_ascii=False))

if __name__=="__main__":
    main()
