"""Bounded 2022 official whole-market day replay for many stock factors in RAM.

Production can fetch ONLY 12 frozen January 2022 exchange-session references
from a READ ONLY Neon 2330 date calendar; each actual TWSE MI_INDEX GET returns
a shared market day, source-validated and filtered through a fresh current
official issuer allowlist with owner exclusions. No backfill, factor writes,
LINE, or published price data. All processed raw rows live only in RAM.

The pure streaming calculator also accepts up to 241 SYNTHETIC sessions in CI
to exercise cross-sectional SMA240/technical-SMC prefix parity. The real HTTP
CLI has NO option to increase its 12-request cap. This is NOT a 241-day
historical source availability claim, adjusted-return calculation or alpha.
"""
from __future__ import annotations

import argparse
from collections import defaultdict, deque
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import statistics
import time

from src.official_market_feed import SOURCE, select_candidates
from src.twse_dated_history import (
    MIN_COVERAGE_SHARE, fetch_official_day, load_current_twse_allowed,
    _processed_days,
)
from scripts.twse_stateless_240_monthly_factor import exact_sma240
from src.raw_factor_feature_bridge import build_research_features, FEATURE_NAMES

START = date(2022, 1, 4)
END = date(2022, 1, 21)
PILOT_SOURCE_DAYS = 12
MAX_STREAM_SESSIONS = 241
ROLLING_STOCK_SESSIONS = 241
MIN_STOCK_COHORT = 500
MAX_ELIGIBLE_DAILY_BARS = 1500
MAX_REPORT_BYTES = 8192
SOURCE_TAG = SOURCE["twse"]
REFERENCE_CALENDAR_SQL = """
SELECT trade_date FROM public.daily_prices
WHERE market='twse' AND stock_id='2330'
 AND source='TWSE_STOCK_DAY'
 AND trade_date BETWEEN %s AND %s
ORDER BY trade_date
LIMIT %s
"""


def validate_days(days, *, real_pilot=False):
    if (not isinstance(days, (list, tuple)) or not 2 <= len(days) <= MAX_STREAM_SESSIONS
            or any(type(d) is not date or d.year != 2022 or d.weekday() >= 5
                   for d in days)
            or list(days) != sorted(set(days))):
        raise ValueError("Invalid, repeated, out-of-order or non-2022 source sessions")
    if real_pilot and (
        len(days) != PILOT_SOURCE_DAYS or days[0] != START
        or days[-1] > END
    ):
        raise ValueError("Real source requests must be the frozen 12-day pilot only")
    return tuple(days)


def _safe_bar(row, *, day):
    if (not isinstance(row, dict)
        or row.get("market") != "twse"
        or row.get("source") != SOURCE_TAG
        or row.get("trade_date") != day
        or row.get("stock_id") == "1589"):
        raise ValueError("Foreign, mixed-date or owner-excluded official source bar")
    prices = tuple(row.get(k) for k in ("open", "high", "low", "close"))
    if (any(type(x) is not Decimal or not x.is_finite() or x <= 0
            for x in prices)
        or not prices[2] <= min(prices[0], prices[3])
             <= max(prices[0], prices[3]) <= prices[1]
        or type(row.get("volume")) is not int
        or row["volume"] < 0):
        raise ValueError("Noncanonical official OHLC price or shares")
    return prices


def compute_stream(days, allowed, day_fetcher):
    """One official day at a time; retain at most 241 prices for each symbol."""
    dates = validate_days(days)
    if (not isinstance(allowed, set)
        or len(allowed) < 700 or ("twse", "1589") in allowed
        or not callable(day_fetcher)):
        raise ValueError("Fresh exchange survivor roster and official fetcher required")
    minimum = max(MIN_STOCK_COHORT, int(len(allowed) * MIN_COVERAGE_SHARE))
    by_stock = defaultdict(lambda: deque(maxlen=ROLLING_STOCK_SESSIONS))
    fully_observed = None
    day_counts = []
    fingerprint = sha256()
    for day in dates:
        source_rows = day_fetcher(day)
        if not isinstance(source_rows, list):
            raise ValueError("Missing an authentic exchange settlement day")
        selected = select_candidates(source_rows, allowed, minimum=minimum)
        if len(selected) > MAX_ELIGIBLE_DAILY_BARS:
            raise ValueError("Unbounded eligible official market response")
        seen = set()
        for row in sorted(selected, key=lambda x: x["stock_id"]):
            _safe_bar(row, day=day)
            sid = row["stock_id"]
            if sid in seen:
                raise ValueError("Duplicate eligible current-listed stock")
            seen.add(sid)
            by_stock[sid].append(row)
            fingerprint.update((
                f"{day.isoformat()}|{sid}|"
                + "|".join(str(row[k]) for k in
                           ("open", "high", "low", "close", "volume"))
                + "\n"
            ).encode())
        fully_observed = seen if fully_observed is None else (fully_observed & seen)
        day_counts.append(len(seen))
    if fully_observed is None or len(fully_observed) < MIN_STOCK_COHORT:
        raise ValueError("Too few stocks observed in every source session")

    if len(dates) < ROLLING_STOCK_SESSIONS:
        # No 240-day factor is claimed by the actual 12-day live pilot.
        prices = []
        for sid in sorted(fully_observed):
            observed = list(by_stock[sid])
            if [x["trade_date"] for x in observed] != list(dates):
                raise ValueError("One stock is missing a shared market session")
            prices.append(observed[-1]["close"] / observed[0]["close"] - Decimal(1))
        ordered = sorted(prices)
        middle = len(ordered) // 2
        med = (ordered[middle] if len(ordered) % 2
               else (ordered[middle - 1] + ordered[middle]) / 2)
        return {
            "scope": "TWSE_2022_SHARED_HISTORIC_SOURCE_MEMORY_PILOT_ONLY",
            "authentic_source_days_evaluated": len(dates),
            "first_source_date": dates[0].isoformat(),
            "last_source_date": dates[-1].isoformat(),
            "daily_current_eligible_source_bar_counts": day_counts,
            "complete_common_stock_cohort": len(fully_observed),
            "raw_price_return_intervals": len(dates) - 1,
            "common_stock_raw_price_return_median": str(med),
            "raw_price_positive_return_stock_count": sum(v > 0 for v in prices),
            "stock_ma240_passes": 0,
            "technical_smc_240_prefix_checks": 0,
            "stock_ma240_historical_proof": False,
            "synthetic_full_241_session_stress_verified": False,
            "source_content_sha256": fingerprint.hexdigest(),
            "one_official_market_source_per_day": True,
            "current_official_survivor_universe_only": True,
            "historically_delisted_issuers_included": False,
            "survivorship_free_historical_universe_verified": False,
            "corporate_action_dividend_adjusted": False,
            "independent_model_alpha_verified": False,
            "full_five_year_market_history_complete": False,
            "raw_price_or_factor_rows_persisted": 0,
            "neon_rows_written": 0,
            "line_messages_sent": 0,
            "live_trading_approved": False,
            "paid_upgrade_requested": False,
        }

    # This branch is offline synthetic in CI; production CLI cannot issue
    # 241 exchange requests. The 240-session prefix test needs 241 sessions.
    last, previous = dates[-1], dates[-2]
    parity_symbols = []
    for sid in sorted(fully_observed):
        history = list(by_stock[sid])
        if len(history) != ROLLING_STOCK_SESSIONS:
            raise ValueError("Missing 241-day shared source stock session")
        today_sma = exact_sma240(history, asof=last)
        previous_sma = exact_sma240(history, asof=previous)
        if previous_sma != exact_sma240(history[:-1], asof=previous):
            raise RuntimeError("240-day SMA used information from the future")
        if len(parity_symbols) < 5:
            current = build_research_features(
                history, stock_id=sid, market="twse", cutoff=last,
                signal_dates=[last],
            )
            future = build_research_features(
                history, stock_id=sid, market="twse", cutoff=last,
                signal_dates=[previous],
            )
            prefix = build_research_features(
                history[:-1], stock_id=sid, market="twse", cutoff=previous,
                signal_dates=[previous],
            )
            if (current["included_signals"] != 1
                or future["included_signals"] != 1
                or prefix["included_signals"] != 1
                or future["signals"][0]["feature_vector"]
                   != prefix["signals"][0]["feature_vector"]
                or len(current["feature_names"]) != len(FEATURE_NAMES)):
                raise RuntimeError("Technical and SMC future-source leakage")
            parity_symbols.append(sid)

    return {
        "scope": "SYNTHETIC_TWSE_241_DAY_SHARED_FACTOR_STRESS_ONLY",
        "authentic_source_days_evaluated": 0,
        "synthetic_source_days_evaluated": len(dates),
        "fully_observed_stock_cohort": len(fully_observed),
        "stock_ma240_passes": len(fully_observed),
        "technical_smc_240_prefix_checks": len(parity_symbols),
        "synthetic_full_241_session_stress_verified": True,
        "real_2022_241_session_source_replayed": False,
        "source_content_sha256": fingerprint.hexdigest(),
        "raw_price_or_factor_rows_persisted": 0,
        "neon_rows_written": 0,
        "line_messages_sent": 0,
        "live_trading_approved": False,
    }


def execute(database_url, *, fetcher=fetch_official_day, pause_seconds=2.0,
            sleeper=time.sleep, output=None):
    if (not database_url or type(pause_seconds) not in (float, int)
        or not 2 <= pause_seconds <= 4):
        raise ValueError("Only paced historical source queries with read-only Neon")
    import psycopg
    with psycopg.connect(
        database_url, connect_timeout=20,
        options="-c default_transaction_read_only=on",
    ) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '45000ms'")
        allowed = load_current_twse_allowed(conn)
        with conn.cursor() as cur:
            cur.execute(
                REFERENCE_CALENDAR_SQL, (START, END, PILOT_SOURCE_DAYS)
            )
            days = [x[0] for x in cur.fetchall()]
        dates = validate_days(days, real_pilot=True)
        processed = _processed_days(conn)
        if any(day in processed for day in dates):
            raise ValueError("Previously imported official day is not a missing pilot date")
    if len(allowed) < 700 or ("twse", "1589") in allowed:
        raise ValueError("No eligible fresh current-listed TWSE securities")
    calls = 0

    def paced(day):
        nonlocal calls
        if calls >= PILOT_SOURCE_DAYS or dates[calls] != day:
            raise RuntimeError("Source request cap or ordering violated")
        if calls:
            sleeper(pause_seconds)
        calls += 1
        return fetcher(day)

    report = compute_stream(dates, allowed, paced)
    if calls != PILOT_SOURCE_DAYS or report["stock_ma240_passes"] != 0:
        raise RuntimeError("The historical 2022 source pilot breached its scope")
    report["maximum_official_http_requests"] = PILOT_SOURCE_DAYS
    report["actual_official_http_requests"] = calls
    blob = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    if len(blob.encode()) > MAX_REPORT_BYTES:
        raise RuntimeError("Proof output is unexpectedly large")
    if output:
        file = Path(output)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(blob, encoding="utf-8")
    else:
        print(blob)
    return report


def main():
    p = argparse.ArgumentParser(
        description="Real 12-day, 2022 TWSE all-market stateless research pilot"
    )
    p.add_argument("--output", type=Path)
    opts = p.parse_args()
    execute(os.environ.get("DATABASE_URL", ""), output=opts.output)


if __name__ == "__main__":
    main()
