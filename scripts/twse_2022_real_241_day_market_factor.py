"""One-time 241 real 2022 TWSE market sessions, no persistent OHLCV or factors.

Requires immutable SHA256 of old official 2330 STOCK_DAY 241-session calendar,
fresh current-listed owner-allowed TWSE roster (excluding 1589), no source
progress already stored, and exactly one dated MI_INDEX official HTTP GET
per historical trading day at >=4-second intervals. One bounded in-RAM
cross-sectional streaming run yields real Decimal MA240 for every continuously
observed current-survivor stock and full 12-feature no-future parity for FIVE
sample stocks. No source retries, public price artifacts, database DML, LINE
messages, financial positions or promoted model performance claims.

The model uses surviving *current* securities, so as-of historical issuer
membership, true dividend-adjusted returns and independent prospective alpha
remain UNPROVEN. An official-source outage aborts without fake success.
"""
from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
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

REPLAY_SESSIONS = 241
EARLIEST = date(2022, 1, 4)
LATEST = date(2022, 12, 26)
EXPECTED_CALENDAR_SHA256 = "ab40cd254d22158dee6b0933fa212774f92a227397bb10c5ff77537580f62b9c"
SOURCE_INTERVAL_SECONDS = 4.0
REPORT_BYTE_LIMIT = 8192


def verify_source_date_calendar(days):
    ordered = validate_days(days)
    if (len(ordered) != REPLAY_SESSIONS
        or ordered[0] != EARLIEST or ordered[-1] != LATEST
        or sha256(",".join(d.isoformat() for d in ordered).encode("ascii")
                  ).hexdigest() != EXPECTED_CALENDAR_SHA256):
        raise ValueError("2022 241-session official date ledger changed; fail closed")
    return ordered


def execute(database_url, *, fetcher=fetch_official_day,
            sleeper=time.sleep, output=None):
    if not isinstance(database_url, str) or not database_url:
        raise ValueError("A protected read-only Neon roster/date URL is required")
    import psycopg
    with psycopg.connect(
        database_url, connect_timeout=20,
        options="-c default_transaction_read_only=on",
    ) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '45000ms'")
        eligible = load_current_twse_allowed(conn)
        with conn.cursor() as cur:
            cur.execute(
                REFERENCE_CALENDAR_SQL, (EARLIEST, LATEST, REPLAY_SESSIONS+1)
            )
            calendar = [r[0] for r in cur.fetchall()]
        dates = verify_source_date_calendar(calendar)
        processed = _processed_days(conn)
        if any(d in processed for d in dates):
            raise ValueError("Already processed market dates must not be reinterpreted as missing")
    if len(eligible) < 700 or ("twse","1589") in eligible:
        raise ValueError("Owner current-listed issuer allowlist incomplete")
    requests_sent = 0
    def controlled(day):
        nonlocal requests_sent
        if requests_sent >= REPLAY_SESSIONS or day != dates[requests_sent]:
            raise RuntimeError("Out-of-order or excess official API requests")
        if requests_sent:
            sleeper(SOURCE_INTERVAL_SECONDS)
        requests_sent += 1
        return fetcher(day)

    proof = compute_stream(dates, eligible, controlled)
    if (requests_sent != REPLAY_SESSIONS
        or proof.get("synthetic_source_days_evaluated") != REPLAY_SESSIONS
        or proof.get("stock_ma240_passes", 0) < 500
        or proof.get("technical_smc_240_prefix_checks") != 5
        or proof.get("neon_rows_written") != 0
        or proof.get("raw_price_or_factor_rows_persisted") != 0
        or proof.get("live_trading_approved") is not False):
        raise RuntimeError("Real 2022 market full 241-session factor gate failed")
    # The pure 241-stream calculator labels its output SYNTHETIC by default,
    # so explicitly promote *proven source provenance*, never alpha/trading.
    proof.update({
        "scope": "TWSE_2022_REAL_241_SESSION_SOURCE_MA240_UNADJUSTED_RESEARCH_ONLY",
        "authentic_source_days_evaluated": REPLAY_SESSIONS,
        "real_2022_241_session_source_replayed": True,
        "synthetic_source_days_evaluated": 0,
        "synthetic_full_241_session_stress_verified": False,
        "real_current_survivor_2022_ma240_source_feasibility": True,
        "earliest_official_source_date": dates[0].isoformat(),
        "last_official_source_date": dates[-1].isoformat(),
        "verified_date_ledger_sha256": EXPECTED_CALENDAR_SHA256,
        "actual_official_http_requests": requests_sent,
        "maximum_official_http_requests": REPLAY_SESSIONS,
        "minimum_interval_between_requests_seconds": SOURCE_INTERVAL_SECONDS,
        "current_issuer_survivorship_unbiased": False,
        "total_return_corporate_actions_adjusted": False,
        "source_historical_original_capture_vintage_verified": False,
        "independent_forward_cost_stressed_model_alpha_validated": False,
        "full_five_year_historical_source_coverage_proven": False,
        "model_retraining_and_live_signals_approved": False,
        "no_neon_price_factor_score_writes": True,
        "raw_price_or_feature_artifacts_uploaded": False,
    })
    serialized = json.dumps(proof, allow_nan=False, ensure_ascii=False,
                            indent=2)+"\n"
    if len(serialized.encode("utf-8")) > REPORT_BYTE_LIMIT:
        raise RuntimeError("Source-only proof exceeded public aggregate limit")
    if output is None:
        print(serialized)
    else:
        dest = Path(output)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(serialized, encoding="utf-8")
    return proof


def main():
    parser = argparse.ArgumentParser(
        description="Research-only full 241 official trading days in RAM; no model release")
    parser.add_argument("--output",type=Path)
    opts=parser.parse_args()
    execute(os.environ.get("DATABASE_URL",""),output=opts.output)


if __name__ == "__main__":
    main()
