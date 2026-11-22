"""Fast, bounded 2021 TWSE official history source verification: 26 dates.

Prior 2021-12-01/02 official source and 2330-close parity passed separately.
Check the OTHER 26 known 2330-anchored, sparse 2021 sessions in four fixed
market batches (6+8+8+4); never request unknown dates or run >8 source dates
inside any one archived-day batch. Every retrieved 2330 close must agree with
the preexisting independent TWSE_STOCK_DAY saved price. The original official
daily source must pass the strict existing whole-market parser and current
issuer survivor / explicit user exclusion filters.

READ ONLY Neon. Market source OHLCV remains only in runner RAM. This is not an
archive/restore/5-year-completion claim or a permission to deploy the model.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from decimal import Decimal
import json
import os
import time
from zoneinfo import ZoneInfo

from scripts.twse_official_direct_archive import (
    MAX_REQUESTED_SESSIONS, preflight, _canonical_source_rows,
)
from src.twse_dated_history import fetch_official_day

BATCHES = (
    (date(2021, 11, 23), date(2021, 11, 24), date(2021, 11, 25),
     date(2021, 11, 26), date(2021, 11, 29), date(2021, 11, 30)),
    (date(2021, 12, 3), date(2021, 12, 6), date(2021, 12, 7),
     date(2021, 12, 8), date(2021, 12, 9), date(2021, 12, 10),
     date(2021, 12, 13), date(2021, 12, 14)),
    (date(2021, 12, 15), date(2021, 12, 16), date(2021, 12, 17),
     date(2021, 12, 20), date(2021, 12, 21), date(2021, 12, 22),
     date(2021, 12, 23), date(2021, 12, 24)),
    (date(2021, 12, 27), date(2021, 12, 28),
     date(2021, 12, 29), date(2021, 12, 30)),
)
ALL_DAYS = tuple(d for batch in BATCHES for d in batch)
REQUEST_CAP = 26
MIN_SOURCE_BARS = 500
MAX_SOURCE_BARS = 1500

ANCHORS_SQL = """
SELECT trade_date,close
FROM public.daily_prices
WHERE market='twse' AND stock_id='2330'
  AND source='TWSE_STOCK_DAY'
  AND trade_date=ANY(%s::date[])
  AND close>0
ORDER BY trade_date
"""


def validate_fixed_batches(batches):
    if (not isinstance(batches, (tuple, list))
            or tuple(tuple(batch) for batch in batches) != BATCHES
            or len(ALL_DAYS) != REQUEST_CAP
            or MAX_REQUESTED_SESSIONS != 8
            or any(not 1 <= len(batch) <= MAX_REQUESTED_SESSIONS
                   or any(type(d) is not date or d.year != 2021
                          or d.weekday() >= 5 for d in batch)
                   or tuple(batch) != tuple(sorted(set(batch)))
                   or (batch[-1]-batch[0]).days > 35
                   or batch[-1].month != batch[0].month
                   for batch in BATCHES)
            or ALL_DAYS != tuple(sorted(set(ALL_DAYS)))
            or any(d in ALL_DAYS for d in
                   (date(2021, 12, 1), date(2021, 12, 2)))):
        raise ValueError("Only four fixed <=8-day historical source batches permitted")
    return ALL_DAYS


def read_anchors(database_url: str):
    """Read exactly 26 original 2330 official closes with protected SQL."""
    if not database_url:
        raise ValueError("Protected database URL required for 2021 original closes")
    import psycopg
    with psycopg.connect(database_url,connect_timeout=20) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '30000ms'")
        with conn.cursor() as cur:
            cur.execute(ANCHORS_SQL,(list(ALL_DAYS),))
            rows=cur.fetchall()
        conn.rollback()
    if (len(rows) != REQUEST_CAP or tuple(d for d,_ in rows) != ALL_DAYS
            or any(type(d) is not date or type(close) is not Decimal
                   or not close.is_finite() or close<=0
                   for d,close in rows)):
        raise ValueError("Missing, untrusted or reordered independent 2021 2330 close anchors")
    return dict(rows)


def verify_source_batches(batches, allowed, anchors, *,
                          fetcher=fetch_official_day, sleeper=time.sleep,
                          pause_seconds=4.0):
    """Only aggregate counts returned. At most 26 paced public-source GETs."""
    validate_fixed_batches(batches)
    if (not isinstance(allowed,set) or len(allowed)<700
            or ("twse","1589") in allowed
            or not isinstance(anchors,dict) or set(anchors)!=set(ALL_DAYS)
            or any(type(v) is not Decimal or not v.is_finite() or v<=0
                   for v in anchors.values())
            or type(pause_seconds) not in (int,float)
            or not 4 <= pause_seconds <= 6
            or not callable(fetcher) or not callable(sleeper)):
        raise ValueError("Verified current roster and 26 original 2330 anchor closes required")
    counts=Counter()
    matched=set()
    requests=0
    for batch in BATCHES:
        offset=requests
        def paced(day):
            nonlocal requests
            expected_index=requests-offset
            if (expected_index>=len(batch) or day!=batch[expected_index]
                    or requests>=REQUEST_CAP):
                raise RuntimeError("Out-of-order or over-budget 2021 TWSE request")
            if requests:
                sleeper(pause_seconds)
            requests+=1
            return fetcher(day)
        for row in _canonical_source_rows(paced,list(batch),allowed):
            day=row["trade_date"]
            if day not in batch or row["stock_id"]=="1589":
                raise ValueError("Unexpected year/date or excluded TWSE stock")
            counts[day]+=1
            if counts[day]>MAX_SOURCE_BARS:
                raise ValueError("Impossible official whole-market daily source size")
            if row["stock_id"]=="2330":
                if row["close"]!=anchors[day]:
                    raise ValueError("Independent 2021 TWSE 2330 original close mismatch")
                matched.add(day)
    if (requests!=REQUEST_CAP or set(counts)!=set(ALL_DAYS)
            or matched!=set(ALL_DAYS)
            or any(not MIN_SOURCE_BARS<=n<=MAX_SOURCE_BARS
                   for n in counts.values())):
        raise ValueError("Not all 26 authentic TWSE 2021 daily source/anchor checks passed")
    return {
        "schema_version":1,
        "scope":"TWSE_2021_REMAINING_26_OFFICIAL_SOURCE_DAYS_RAM_ONLY",
        "already_separately_verified_2021_dec_1_2_source_days":2,
        "new_official_2021_source_days_verified":requests,
        "date_batches_bounded_to_max_eight":[len(b) for b in BATCHES],
        "first_new_verified_date":ALL_DAYS[0].isoformat(),
        "last_new_verified_date":ALL_DAYS[-1].isoformat(),
        "daily_eligible_official_rows":{
            d.isoformat():counts[d] for d in ALL_DAYS},
        "validated_original_2330_closes":len(matched),
        "total_validated_official_bars":sum(counts.values()),
        "minimum_pause_between_official_requests_seconds":pause_seconds,
        "existing_neon_raw_prices_written":0,
        "new_encrypted_archive_files_created":0,
        "neon_technical_or_model_rows_written":0,
        "line_messages_sent":0,
        "paid_resources_requested":False,
        "owner_exclusion_1589_enforced":True,
        "historically_delisted_issuers_included":False,
        "historical_asof_listing_membership_proven":False,
        "full_five_year_source_archive_verified":False,
        "corporate_action_total_returns_verified":False,
        "live_model_deployment_allowed":False,
    }


def run(database_url:str,*,today=None,fetcher=fetch_official_day,
        sleeper=time.sleep):
    validate_fixed_batches(BATCHES)
    today=today or datetime.now(ZoneInfo("Asia/Taipei")).date()
    if type(today) is not date or today<=date(2021,12,30):
        raise ValueError("Cannot validate 2021 source on same or earlier day")
    anchors=read_anchors(database_url)
    roster=None
    for batch in BATCHES:
        found,allowed=preflight(database_url,start=batch[0],end=batch[-1],today=today)
        if tuple(found)!=batch:
            raise ValueError("Neon 2330-backed missing-day calendar has changed")
        if roster is None:
            roster=allowed
        elif allowed!=roster:
            raise ValueError("Official current listed issuer roster changed within batch verification")
    return verify_source_batches(BATCHES,roster,anchors,fetcher=fetcher,
                                 sleeper=sleeper)


def main():
    result=run(os.environ.get("DATABASE_URL",""))
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,
                     allow_nan=False))


if __name__=="__main__":
    main()
