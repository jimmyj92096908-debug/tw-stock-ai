"""Second fixed batch: 2022 exchange sessions #49-96, RAM only, no Neon writes.

Shares the validated whole-market day parser and 48-day streaming algorithm.
Reads the existing 2330 STOCK_DAY day calendar under READ ONLY, verifies its
precommitted SHA256 and all holidays, then requests exactly 48 distinct
MI_INDEX official dates at 4+ second gaps. No batch retry or raw artifact.
The two batches are NOT a continuous persistent 96-day source archive.
"""
from __future__ import annotations
from datetime import date
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path
import time

from scripts.twse_2022_shared_source_stream import (
    REFERENCE_CALENDAR_SQL, compute_stream, validate_days,
)
from src.twse_dated_history import (
    fetch_official_day, load_current_twse_allowed, _processed_days,
)

FIRST_DAY = date(2022, 3, 23)
LAST_DAY = date(2022, 6, 1)
DAYS = 48
PAUSE_SECONDS = 4.0
EXPECTED_CALENDAR_SHA256 = "0d87ea97df1a18baaacfaa680753d97b189ab01a2a356e81acfd664cc5740ef8"
OFFICIAL_CLOSURES = (date(2022, 4, 4), date(2022, 4, 5), date(2022, 5, 2))
MAX_OUTPUT_BYTES = 8192


def verify_calendar(calendar):
    ordered = validate_days(calendar)
    serialized = ",".join(d.isoformat() for d in ordered).encode("ascii")
    if (len(ordered) != DAYS or ordered[0] != FIRST_DAY
        or ordered[-1] != LAST_DAY
        or any(closed in ordered for closed in OFFICIAL_CLOSURES)
        or sha256(serialized).hexdigest() != EXPECTED_CALENDAR_SHA256):
        raise ValueError("2022 official second-batch day ledger changed or is incomplete")
    return ordered


def execute(database_url, *, fetcher=fetch_official_day,
            sleeper=time.sleep, output=None):
    if not isinstance(database_url, str) or not database_url:
        raise ValueError("A protected read-only Neon URL is required")
    import psycopg
    with psycopg.connect(
        database_url, connect_timeout=20,
        options="-c default_transaction_read_only=on",
    ) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '45000ms'")
        allowed = load_current_twse_allowed(conn)
        with conn.cursor() as cur:
            cur.execute(REFERENCE_CALENDAR_SQL, (FIRST_DAY, LAST_DAY, DAYS + 1))
            ledger = [x[0] for x in cur.fetchall()]
        dates = verify_calendar(ledger)
        status = _processed_days(conn)
        if any(d in status for d in dates):
            raise ValueError("Cannot source-probe dates with completed import receipts")
    if len(allowed) < 700 or ("twse", "1589") in allowed:
        raise ValueError("Missing authorized current official issuer coverage")
    n = 0
    def source_one_day(day):
        nonlocal n
        if n >= DAYS or day != dates[n]:
            raise RuntimeError("Official source request count/date/order guard")
        if n:
            sleeper(PAUSE_SECONDS)
        n += 1
        return fetcher(day)
    proof = compute_stream(dates, allowed, source_one_day)
    if (n != DAYS or proof["authentic_source_days_evaluated"] != DAYS
        or proof["stock_ma240_passes"] != 0
        or proof["neon_rows_written"] != 0
        or proof["raw_price_or_factor_rows_persisted"] != 0):
        raise RuntimeError("Unexpectedly widened research pilot")
    proof.update({
        "scope": "TWSE_2022_REAL_49_TO_96_SHARED_DAYS_NO_STORAGE",
        "source_session_ordinal_start": 49,
        "source_session_ordinal_end": 96,
        "actual_official_http_requests": n,
        "maximum_official_http_requests": DAYS,
        "minimum_request_interval_seconds": PAUSE_SECONDS,
        "verified_calendar_sha256": EXPECTED_CALENDAR_SHA256,
        "source_is_replay_not_persisted_history": True,
        "real_2022_240_day_ma_verified": False,
        "independent_historical_issuer_universe_verified": False,
        "independent_holdout_alpha_verified": False,
    })
    report = json.dumps(proof, ensure_ascii=False, allow_nan=False,
                        indent=2) + "\n"
    if len(report.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise RuntimeError("Aggregate proof unexpectedly large")
    if output is None:
        print(report)
    else:
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(report, encoding="utf-8")
    return proof


def main():
    parser = argparse.ArgumentParser(
        description="Fixed real 2022 TWSE sessions 49-96, 4sec no-storage source")
    parser.add_argument("--output", type=Path)
    execute(os.environ.get("DATABASE_URL", ""),
            output=parser.parse_args().output)


if __name__ == "__main__":
    main()
