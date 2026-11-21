"""Tiny read-only official TWSE source -> in-memory technical/SMC canary.

This intentionally does NOT materialize adjusted/technical/SMC database tables,
does NOT produce trading recommendations, and does NOT certify model alpha.
Uses just five current officially-listed stocks and 320 real saved sessions each.
"""
from __future__ import annotations

import argparse
from datetime import date,datetime,timezone
from hashlib import sha256
import json
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from src.current_official_listing import CURRENT_OFFICIAL_LISTED_CTE
from src.raw_factor_feature_bridge import (
    MAX_BARS,MIN_WARMUP_SESSIONS,FEATURE_NAMES,build_research_features
)

STOCK_LIMIT=5
BARS_PER_STOCK=320
MAX_DB_BYTES=800_000_000

CANDIDATES_SQL=CURRENT_OFFICIAL_LISTED_CTE+"""
, last_market AS (
 SELECT max(trade_date) AS day FROM public.daily_prices
 WHERE market='twse' AND close>0
), maturity AS (
 SELECT listed.stock_id,
        count(p.trade_date) FILTER(WHERE p.close>0 AND p.volume>=0)::int valid_days,
        max(p.trade_date) FILTER(WHERE p.close>0 AND p.volume>=0) latest
 FROM official_current_listed listed
 LEFT JOIN public.daily_prices p
   ON p.market=listed.market AND p.stock_id=listed.stock_id
 WHERE listed.market='twse'
 GROUP BY listed.stock_id
)
SELECT m.stock_id,m.valid_days,l.day AS market_day
FROM maturity m CROSS JOIN last_market l
WHERE m.valid_days>=240 AND m.latest=l.day
ORDER BY m.valid_days DESC,m.stock_id LIMIT 5
"""

SOURCE_SQL="""
SELECT market,stock_id,trade_date,open,high,low,close,volume,
       turnover,price_change,transactions,source
FROM (
 SELECT market,stock_id,trade_date,open,high,low,close,volume,
        turnover,price_change,transactions,source
 FROM public.daily_prices
 WHERE market='twse' AND stock_id=%s AND trade_date<=%s
   AND close>0 AND volume>=0
 ORDER BY trade_date DESC LIMIT %s
) sorted_prices ORDER BY trade_date
"""

def run(url):
    if not url:
        raise ValueError("Protected DATABASE_URL required")
    with psycopg.connect(url,connect_timeout=20,row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout='60000ms'")
        size=conn.execute(
            "SELECT pg_database_size(current_database())::bigint AS bytes"
        ).fetchone()["bytes"]
        if type(size) is not int or size<=0 or size>=MAX_DB_BYTES:
            raise RuntimeError("Neon free database read-only canary capacity gate")
        selected=[dict(row) for row in conn.execute(CANDIDATES_SQL).fetchall()]
        if len(selected)!=STOCK_LIMIT or len({r["stock_id"] for r in selected})!=STOCK_LIMIT:
            raise RuntimeError("Insufficient unique current official 240-session stock canary")
        proofs=[]
        for row in selected:
            stock_id=row["stock_id"]
            cutoff=row["market_day"]
            if (not isinstance(stock_id,str) or type(cutoff) is not date
                or type(row["valid_days"]) is not int
                or row["valid_days"]<MIN_WARMUP_SESSIONS):
                raise RuntimeError("Unverified TWSE source canary maturity")
            bars=[dict(raw) for raw in conn.execute(
                SOURCE_SQL,(stock_id,cutoff,BARS_PER_STOCK)).fetchall()]
            if not MIN_WARMUP_SESSIONS<=len(bars)<=BARS_PER_STOCK:
                raise RuntimeError("Insufficient bounded raw source series")
            if bars[-1]["trade_date"]!=cutoff:
                raise RuntimeError("Source changed or last actual day disagrees")
            current=build_research_features(
                bars,stock_id=stock_id,market="twse",cutoff=cutoff,
                signal_dates=[cutoff]
            )
            prior=bars[-2]["trade_date"]
            whole=build_research_features(
                bars,stock_id=stock_id,market="twse",cutoff=cutoff,
                signal_dates=[prior]
            )
            no_suffix=build_research_features(
                bars[:-1],stock_id=stock_id,market="twse",cutoff=prior,
                signal_dates=[prior]
            )
            if (current["included_signals"]!=1 or whole["included_signals"]!=1
                or no_suffix["included_signals"]!=1
                or whole["signals"][0]["feature_vector"]!=
                    no_suffix["signals"][0]["feature_vector"]):
                raise RuntimeError("Causal TWSE technical/SMC price feature parity failed")
            proofs.append({
                "stock_id":stock_id,"raw_sessions_used":len(bars),
                "feature_version":current["feature_version"],
                "source_hash":current["raw_source_fingerprint_sha256"],
                "causal_prior_session_prefix_check":True,
                "source_tags":current["original_source_tags"],
            })
    fingerprint=sha256(json.dumps(proofs,sort_keys=True,
                   separators=(",",":"),allow_nan=False).encode()).hexdigest()
    return {
        "scope":"TWSE_OFFICIAL_CURRENT_ACTIVE_RAW_FACTOR_READONLY_CANARY",
        "completed_at_utc":datetime.now(timezone.utc).isoformat(),
        "real_stock_sample_count":len(proofs),
        "original_source_price_rows":sum(item["raw_sessions_used"] for item in proofs),
        "verified_no_future_suffix_samples":len(proofs),
        "feature_names":list(FEATURE_NAMES),
        "source_fingerprint_sha256":fingerprint,
        "per_stock_source_evidence":proofs,
        "database_bytes":size,
        "persistent_technical_or_smc_rows_written":0,
        "cash_dividend_total_return_factors_proven":False,
        "source_capture_asof_vintage_independently_proven":False,
        "independent_future_model_validation_proven":False,
        "production_model_weights_changed":False,
        "line_messages_sent":False,
        "trading_approved":False,
        "paid_upgrade_required":False,
    }


def main():
    parser=argparse.ArgumentParser(description="Official TWSE raw factor 5-stock causal no-storage proof")
    parser.add_argument("--report",type=Path,default=Path("twse-raw-factor-canary.json"))
    args=parser.parse_args()
    report=run(os.environ.get("DATABASE_URL",""))
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",
                           encoding="utf-8")
    print(json.dumps({
        "scope":report["scope"],
        "stocks":report["real_stock_sample_count"],
        "raw_rows":report["original_source_price_rows"],
        "no_future_suffix_checks":report["verified_no_future_suffix_samples"],
        "persistent_factor_rows_written":0,
        "independent_future_model_validation_proven":False,
        "trading_approved":False,
    },ensure_ascii=False))


if __name__=="__main__":
    main()
