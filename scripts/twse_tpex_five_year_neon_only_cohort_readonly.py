"""READ ONLY rolling-five-year current-listed TWSE + TPEx coverage baseline.

This measures only already-stored, source-tag-allowlisted Neon daily_prices.
It NEVER pretends owner-private AES archives are in Neon, that nontrading IPO
days are market missing days, or that today's survivor universe is historic PIT.
Designed to identify the largest 5Y research blocker without consuming paid
storage or changing any production data/model/LINE activity.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from current_official_listing import CURRENT_OFFICIAL_LISTED_CTE

SCOPE = "OWNER_TWSE_TPEX_NEON_ONLY_5Y_OFFICIAL_CURRENT_LISTED_SOURCE_DEPTH"
MARKETS = ("twse", "tpex")
SOURCES = {
    "twse": frozenset(("TWSE_MI_INDEX_ALLBUT0999", "TWSE_STOCK_DAY")),
    "tpex": frozenset((
        "TPEX_TRADING_STOCK", "TPEX_TRADING_STOCK_NORMALIZED",
        "TPEX_DAILY_CLOSE_OPENAPI", "TPEX_DATED_OTC_EW",
    )),
}
MAX_SNAPSHOT_BYTES = 20_000
MAX_STORAGE_FREE_STOP_BYTES = 800_000_000

# The same strict, latest 14-day official current-listing CTE used in live
# current-only research. An absence of a fresh official snapshot means
# NO eligible issuers; stock_master must not be used as a fallback.
ELIGIBLE = CURRENT_OFFICIAL_LISTED_CTE + """
, eligible AS (
 SELECT o.market, o.stock_id
 FROM official_current_listed o
 WHERE o.market IN ('twse', 'tpex')
   AND o.stock_id <> '1589'
   AND NOT EXISTS (
     SELECT 1 FROM public.model_stock_exclusions x
     WHERE x.market=o.market AND x.stock_id=o.stock_id
   )
)
"""
VALID_SOURCE = """
AND ((p.market='twse' AND p.source IN (
       'TWSE_MI_INDEX_ALLBUT0999','TWSE_STOCK_DAY'))
  OR (p.market='tpex' AND p.source IN (
       'TPEX_TRADING_STOCK','TPEX_TRADING_STOCK_NORMALIZED',
       'TPEX_DAILY_CLOSE_OPENAPI','TPEX_DATED_OTC_EW')))
"""
STOCK_SQL = ELIGIBLE + """
, per_stock AS (
 SELECT e.market,e.stock_id,
        COUNT(p.trade_date) FILTER (
          WHERE p.close>0 AND p.volume>=0)::int AS valid_days
 FROM eligible e
 LEFT JOIN public.daily_prices p
   ON p.market=e.market AND p.stock_id=e.stock_id
  AND p.trade_date >= %s AND p.trade_date < %s
  """ + VALID_SOURCE + """
 GROUP BY e.market,e.stock_id
)
SELECT market,COUNT(*)::int AS active_current_listed,
 COUNT(*) FILTER(WHERE valid_days=0)::int AS stock_days0,
 COUNT(*) FILTER(WHERE valid_days BETWEEN 1 AND 59)::int AS stock_days1_59,
 COUNT(*) FILTER(WHERE valid_days BETWEEN 60 AND 239)::int AS stock_days60_239,
 COUNT(*) FILTER(WHERE valid_days BETWEEN 240 AND 479)::int AS stock_days240_479,
 COUNT(*) FILTER(WHERE valid_days BETWEEN 480 AND 999)::int AS stock_days480_999,
 COUNT(*) FILTER(WHERE valid_days>=1000)::int AS stock_days1000_plus,
 MIN(valid_days)::int AS min_stock_valid_days,
 MAX(valid_days)::int AS max_stock_valid_days
FROM per_stock GROUP BY market ORDER BY market
"""

YEAR_SQL = ELIGIBLE + """
, observed AS (
 SELECT p.market,p.trade_date,COUNT(*)::int AS stored_valid_current_stock_bars
 FROM public.daily_prices p
 JOIN eligible e ON e.market=p.market AND e.stock_id=p.stock_id
 WHERE p.trade_date >= %s AND p.trade_date < %s
   AND p.close>0 AND p.volume>=0
   """ + VALID_SOURCE + """
 GROUP BY p.market,p.trade_date
)
SELECT market,EXTRACT(YEAR FROM trade_date)::int AS year,
 COUNT(*)::int AS neon_observed_stock_price_dates,
 COUNT(*) FILTER(WHERE stored_valid_current_stock_bars>=500)::int
   AS dates_with_500_current_stock_bars,
 SUM(stored_valid_current_stock_bars)::bigint AS stored_valid_current_stock_bars
FROM observed GROUP BY market,EXTRACT(YEAR FROM trade_date)
ORDER BY market,year
"""
META_SQL = "SELECT pg_database_size(current_database())::bigint AS bytes"


def five_year_window(today):
    if type(today) is not date:
        raise ValueError("Authenticated Taiwan date required")
    try:
        start = today.replace(year=today.year-5)
    except ValueError:
        start = today.replace(year=today.year-5,day=28)
    if start >= today or today.year < 2026:
        raise ValueError("Only actual rolling-five-year dates supported")
    # Exclude current incomplete/live day entirely; archive data is not
    # reclassified as a verified market holiday for any missing dates.
    return start, today


def evaluate(stock_rows, year_rows, metadata, *, start, end):
    if (type(start) is not date or type(end) is not date or
            not start < end or end.year-start.year not in (5, 6)):
        raise ValueError("Actual bounded rolling five-year dates required")
    if (not isinstance(stock_rows,list) or len(stock_rows)!=2 or
            not isinstance(year_rows,list) or not isinstance(metadata,dict)):
        raise ValueError("Both official current-listed markets and real Neon required")
    if type(metadata.get("bytes")) is not int or metadata["bytes"]<=0:
        raise ValueError("No authenticated Neon database storage evidence")
    bucket_keys = (
        "stock_days0","stock_days1_59","stock_days60_239",
        "stock_days240_479","stock_days480_999","stock_days1000_plus",
    )
    stocks = {}
    for r in stock_rows:
        if (not isinstance(r,dict) or r.get("market") not in MARKETS
                or r["market"] in stocks
                or type(r.get("active_current_listed")) is not int
                or r["active_current_listed"]<700
                or any(type(r.get(k)) is not int or r[k]<0 for k in bucket_keys)
                or sum(r[k] for k in bucket_keys)!=r["active_current_listed"]
                or type(r.get("min_stock_valid_days")) is not int
                or type(r.get("max_stock_valid_days")) is not int
                or not 0 <= r["min_stock_valid_days"] <=
                           r["max_stock_valid_days"] <= 1550):
            raise ValueError("Missing or stale official current-listed/stock-depth audit")
        stocks[r["market"]] = {
            "official_current_listed_stocks_excluding_1589": r["active_current_listed"],
            "per_stock_5year_neon_valid_days_distribution": {
                k: r[k] for k in bucket_keys
            },
            "minimum_neon_valid_stock_days": r["min_stock_valid_days"],
            "maximum_neon_valid_stock_days": r["max_stock_valid_days"],
            "with_at_least_240_valid_stored_days": sum(r[k] for k in bucket_keys[3:]),
            "with_at_least_1000_valid_stored_days": r["stock_days1000_plus"],
        }
    if set(stocks)!=set(MARKETS):
        raise ValueError("A stale issuer snapshot cannot be silently accepted")
    seen = set()
    years = {market: [] for market in MARKETS}
    for row in year_rows:
        if (not isinstance(row,dict) or row.get("market") not in MARKETS
                or type(row.get("year")) is not int
                or (row["market"],row["year"]) in seen
                or not start.year<=row["year"]<=end.year
                or any(type(row.get(k)) is not int or row[k] < 0 for k in (
                    "neon_observed_stock_price_dates",
                    "dates_with_500_current_stock_bars",
                    "stored_valid_current_stock_bars",
                ))
                or not 0 <= row["dates_with_500_current_stock_bars"]
                           <= row["neon_observed_stock_price_dates"] <= 366
                or row["stored_valid_current_stock_bars"] <
                    row["neon_observed_stock_price_dates"]
                or row["stored_valid_current_stock_bars"] >
                    row["neon_observed_stock_price_dates"] *
                    stocks[row["market"]]["official_current_listed_stocks_excluding_1589"]):
            raise ValueError("Invalid duplicate or impossible source year market counts")
        seen.add((row["market"],row["year"]))
        years[row["market"]].append({
            "year": row["year"],
            "days_with_any_neon_eligible_source_bars":
                row["neon_observed_stock_price_dates"],
            "days_with_at_least_500_eligible_source_bars":
                row["dates_with_500_current_stock_bars"],
            "neon_stored_valid_source_stock_bars":
                row["stored_valid_current_stock_bars"],
        })
    for m in MARKETS:
        existing = {y["year"] for y in years[m]}
        for y in range(start.year,end.year+1):
            if y not in existing:
                years[m].append({
                    "year": y,
                    "days_with_any_neon_eligible_source_bars": 0,
                    "days_with_at_least_500_eligible_source_bars": 0,
                    "neon_stored_valid_source_stock_bars": 0,
                })
        years[m].sort(key=lambda r:r["year"])
        stocks[m]["yearly_neon_source_observations"] = years[m]
    return {
        "schema_version": 1,
        "scope": SCOPE,
        "window_start_inclusive": start.isoformat(),
        "window_end_exclusive": end.isoformat(),
        "current_listed_issuers_only_not_historical_pit_membership": True,
        "excludes_owner_private_aes_and_non_neon_source_history": True,
        "neon_stock_date_counts_are_not_complete_official_market_calendar": True,
        "valid_price_definition": "known_source_tag,close_positive,volume_nonnegative",
        "market": stocks,
        "database_bytes": metadata["bytes"],
        "free_storage_internal_stop_bytes": MAX_STORAGE_FREE_STOP_BYTES,
        "internal_stop_threshold_reached":
            metadata["bytes"] >= MAX_STORAGE_FREE_STOP_BYTES,
        "owner_aes_2021_2022_source_not_included": True,
        "five_year_history_completed": False,
        "historical_dividends_splits_total_return_verified": False,
        "historical_asof_listing_membership_proven": False,
        "walkforward_future_holdout_validated": False,
        "model_release": "BLOCKED",
        "production_neon_writes": 0,
        "line_messages_sent": 0,
        "paid_upgrade_requested": False,
    }


def capture(url, *, start, end):
    if not url or not url.startswith(("postgres://","postgresql://")):
        raise ValueError("Existing private Neon database URL required")
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(url,connect_timeout=15,row_factory=dict_row) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '60000ms'")
        rows=[dict(r) for r in conn.execute(STOCK_SQL,(start,end)).fetchall()]
        years=[dict(r) for r in conn.execute(YEAR_SQL,(start,end)).fetchall()]
        meta=dict(conn.execute(META_SQL).fetchone())
        conn.rollback()
    return rows,years,meta


def main():
    p=argparse.ArgumentParser(
        description="READ ONLY TWSE+TPEx five-year current-listed research coverage")
    p.add_argument("--out",required=True)
    args=p.parse_args()
    try:
        today=datetime.now(ZoneInfo("Asia/Taipei")).date()
        start,end=five_year_window(today)
        rows,years,meta=capture(os.environ.get("DATABASE_URL",""),
                                start=start,end=end)
        report=evaluate(rows,years,meta,start=start,end=end)
        out=Path(args.out).expanduser()
        if (out.is_symlink() or
                any((parent/".git").exists()
                    for parent in (out.parent.resolve(),*out.parent.resolve().parents))
                or not out.parent.is_dir()):
            raise ValueError("Owner report must be in existing non-Git folder")
        with out.open("x",encoding="utf-8") as fp:
            payload=json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n"
            if len(payload.encode("utf-8"))>MAX_SNAPSHOT_BYTES:
                raise ValueError("Aggregate five-year report exceeds privacy budget")
            fp.write(payload)
        print(json.dumps({
            "status":"TWSE_TPEX_FIVE_YEAR_NEON_ONLY_COHORT_BASELINE_PASS",
            "neon_only_current_eligible_issuer_count":sum(
                v["official_current_listed_stocks_excluding_1589"]
                for v in report["market"].values()),
            "neon_only_stocks_at_least_1000_sessions": {
                k:v["with_at_least_1000_valid_stored_days"]
                for k,v in report["market"].items()
            },
            "owner_private_aes_source_included":False,
            "full_five_year_data_complete":False,
            "neon_writes":0,
            "line_messages_sent":0,
            "model_release":"BLOCKED",
        },ensure_ascii=False))
    except Exception:
        raise SystemExit(
            "Private read-only five-year Neon coverage snapshot FAILED; "
            "no database writes, LINE messages or credentials printed") from None


if __name__=="__main__":
    main()
