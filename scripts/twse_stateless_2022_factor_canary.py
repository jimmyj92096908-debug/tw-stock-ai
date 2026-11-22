"""Compute a real historical TWSE price-only factor without Neon derived storage.

Five *fixed* missing January 2022 official sessions, read with the existing
validated TWSE dated source parser into ephemeral runner memory. A protected
Neon READ ONLY transaction is used solely for current issuer allowlisting
and processed-date checks. Never store raw bars, index rows, factor rows,
private archives or portfolio picks in GitHub/Neon.

This is a raw unadjusted 5-session return factor feasibility demonstration,
not a 240-day factor, backtest, historical survivorship audit or alpha result.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path
import time

from src.official_market_feed import SOURCE, select_candidates
from src.twse_dated_history import (
    MIN_COVERAGE_SHARE, fetch_official_day,
    load_current_twse_allowed, _processed_days,
)

DATES = (
    date(2022,1,4), date(2022,1,5), date(2022,1,6),
    date(2022,1,7), date(2022,1,10),
)
MIN_COHORT = 500
MAX_SOURCE_CALLS = len(DATES)


def compute_stateless_price_factor(day_rows, *, allowed):
    """Pure function: exact date-aligned 5-session price-only momentum."""
    if (not isinstance(day_rows,list) or len(day_rows)!=MAX_SOURCE_CALLS or
        len(allowed)<700 or ("twse","1589") in allowed):
        raise ValueError("Five verified source sessions and approved roster required")
    by_date = []
    day_counts = []
    for day,source_rows in zip(DATES,day_rows):
        minimum=max(MIN_COHORT,int(len(allowed)*MIN_COVERAGE_SHARE))
        selected=select_candidates(source_rows,allowed,minimum=minimum)
        mapped={}
        for row in selected:
            sid=row["stock_id"]
            price=row["close"]
            if (row["market"]!="twse" or row["trade_date"]!=day
                or row["source"]!=SOURCE["twse"]
                or sid=="1589" or type(price) is not Decimal
                or not price.is_finite() or price<=0):
                raise ValueError("Wrong source/date/precision in five-session factor")
            mapped[sid]=price
        day_counts.append(len(mapped))
        by_date.append(mapped)
    cohort=set.intersection(*(set(x) for x in by_date))
    if len(cohort)<MIN_COHORT:
        raise ValueError("Too few stocks share all five authentic price sessions")
    # As-of last session only. No future return labels or model ranking.
    digest=sha256()
    raw_returns=[]
    for sid in sorted(cohort):
        series=[d[sid] for d in by_date]
        momentum=(series[-1]/series[0]-Decimal(1))
        if not momentum.is_finite():
            raise ValueError("Nonfinite raw five-session momentum")
        raw_returns.append(momentum)
        fingerprint=(sid+"|"+",".join(str(p) for p in series)
                     +"|"+str(momentum)+"\n")
        digest.update(fingerprint.encode())
    sorted_returns=sorted(raw_returns)
    middle=len(sorted_returns)//2
    median=(sorted_returns[middle] if len(sorted_returns)%2
            else (sorted_returns[middle-1]+sorted_returns[middle])/2)
    gainers=sum(v>0 for v in raw_returns)
    return {
        "scope":"TWSE_2022_FIVE_SESSION_STATELESS_RAW_FACTOR_ONLY",
        "source_days":[d.isoformat() for d in DATES],
        "official_current_allowed_bars_per_day":day_counts,
        "fully_observed_five_session_stock_cohort":len(cohort),
        "as_of_session":DATES[-1].isoformat(),
        "raw_price_only_median_4_interval_return":str(median),
        "raw_price_only_positive_momentum_stock_count":gainers,
        "feature_input_sha256":digest.hexdigest(),
        "source_ohlcv_rows_written":0,
        "model_derived_rows_written":0,
        "temporary_runner_memory_only":True,
        "date_and_source_vintage_verified_historical_issuer_roster":False,
        "historical_issuer_survivorship_free":False,
        "total_return_dividend_adjusted":False,
        "five_year_technical_factor_coverage_proven":False,
        "independent_out_of_sample_alpha_proven":False,
        "line_messages_sent":0,
        "live_trading_approved":False,
        "paid_upgrade_requested":False,
    }


def execute(database_url, *, fetcher=fetch_official_day, pause_seconds=2,
            output=None):
    if not database_url or type(pause_seconds) not in (int,float) or not 0<=pause_seconds<=3:
        raise ValueError("Only read-only Neon and bounded official request pacing")
    import psycopg
    with psycopg.connect(database_url,connect_timeout=15,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '40000ms'")
        allowed=load_current_twse_allowed(conn)
        previously_processed=_processed_days(conn)
        if any(day in previously_processed for day in DATES):
            raise ValueError("Source-on-demand factor date no longer missing")
    readings=[]
    for i,day in enumerate(DATES):
        rows=fetcher(day)
        if rows is None:
            raise ValueError("Five-day feasibility request included nontrading date")
        readings.append(rows)
        if i+1<len(DATES) and pause_seconds:
            time.sleep(pause_seconds)
    report=compute_stateless_price_factor(readings,allowed=allowed)
    serial=json.dumps(report,ensure_ascii=False,allow_nan=False,indent=2)+"\n"
    if len(serial.encode())>8192:
        raise RuntimeError("Unexpectedly large factor-only evidence")
    if output is None:
        print(serial)
    else:
        dest=Path(output)
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text(serial,encoding="utf-8")
    return report


def main():
    p=argparse.ArgumentParser(description="Five 2022 TWSE source dates, raw factor in RAM")
    p.add_argument("--output",type=Path)
    opts=p.parse_args()
    execute(os.environ.get("DATABASE_URL",""),output=opts.output)


if __name__=="__main__":
    main()
