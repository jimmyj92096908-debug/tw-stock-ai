"""Conservative pre-write Neon Free guard for bounded indicator recomputation.

Never writes. The existing scheduled writer must call it immediately before
computing adjusted prices, technicals and SMC. Estimates even existing rows
as rewrites (to account for PostgreSQL MVCC heap/index growth).
"""
from __future__ import annotations
import os
import psycopg
from psycopg.rows import dict_row
from batch_indicator_catchup import select_candidates, MAX_PER_MARKET

STOP_BYTES = 800_000_000
RESERVE_BYTES = 50_000_000
REWRITE_SAFETY_MULTIPLIER = 3.0
DERIVED = ("daily_adjusted_prices", "daily_technicals", "daily_smc")

def assess(database_bytes, bytes_per_price_day, candidate_price_days):
    if type(database_bytes) is not int or database_bytes < 1:
        raise ValueError("Invalid database size")
    if (not isinstance(bytes_per_price_day,(float,int)) or
        bytes_per_price_day <= 0 or not isinstance(candidate_price_days,list) or
        len(candidate_price_days)>2*MAX_PER_MARKET or
        any(type(n) is not int or n < 0 for n in candidate_price_days)):
        raise ValueError("Invalid bounded derived write footprint")
    exposure = round(sum(candidate_price_days)*bytes_per_price_day*REWRITE_SAFETY_MULTIPLIER)
    return {
        "database_bytes":database_bytes,
        "estimated_heap_index_growth_bytes":exposure,
        "internal_stop_bytes":STOP_BYTES,
        "maintenance_reserve_bytes":RESERVE_BYTES,
        "candidate_count":len(candidate_price_days),
        "allow_apply":database_bytes+exposure+RESERVE_BYTES<STOP_BYTES,
        "read_only":True,
        "projection_not_quota_guarantee":True,
    }

def inspect(url):
    if not url:
        raise ValueError("Protected DATABASE_URL required")
    with psycopg.connect(
        url,connect_timeout=20,row_factory=dict_row,
        options="-c default_transaction_read_only=on"
    ) as conn:
        with conn.transaction():
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            conn.execute("SET LOCAL statement_timeout='45000ms'")
            size=int(conn.execute(
                "SELECT pg_database_size(current_database())").fetchone()["pg_database_size"])
            cost=0.0
            for table in DERIVED:
                rec=conn.execute(
                    "SELECT pg_total_relation_size(%s::regclass)::bigint AS bytes,"
                    " (SELECT count(*)::bigint FROM public." + table + ") AS n",
                    ("public."+table,)
                ).fetchone()
                if int(rec["n"])<=0:
                    raise RuntimeError("No conservative physical row-cost evidence")
                cost+=int(rec["bytes"])/int(rec["n"])
            days=[]
            for market in ("twse","tpex"):
                candidates=select_candidates(conn,market,MAX_PER_MARKET)
                for stock in candidates:
                    result=conn.execute(
                        "SELECT count(*)::int AS n FROM public.daily_prices "
                        "WHERE market=%s AND stock_id=%s",
                        (market,stock["stock_id"])
                    ).fetchone()
                    days.append(int(result["n"]))
    return assess(size,cost,days)

if __name__=="__main__":
    report=inspect(os.getenv("DATABASE_URL",""))
    print("Neon Free derived pre-write check: "
          + "ALLOW" if report["allow_apply"] else "Neon Free derived pre-write check: BLOCK")
    if not report["allow_apply"]:
        raise SystemExit("Bounded indicator batch exceeds conservative free storage reserve")
