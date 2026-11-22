"""Official TWSE five-year gap -> private local AES archive, WITHOUT PostgreSQL writes.

The existing guarded TWSE importer and user exclusions are reused. SQL reads
only confirmed 2330 reference sessions that are sparse and have no imported/
closed receipt; the exact official MI_INDEX response is fetched independently
and current-listed eligible bars must meet whole-market source coverage.

Preview never hits an external source. Archive mode needs an independently
retained AES-256 key, creates an encrypted local file outside Git, verifies all
rows, then emits a private nonsecret manifest. No public CI source artifacts,
no LINE, paid usage, PostgreSQL insertion, or automatic S3 uploads.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

# Owner-local `python -m scripts.twse_official_direct_archive` starts with only
# the checkout root on sys.path. Legacy `src` utilities still use top-level
# imports (official_market_feed, official_snapshot_ingest, etc.). Add this
# checkout's own src directory, without needing PYTHONPATH or changing the
# public CI/importer entrypoints. No database or network access occurs here.
BOOTSTRAP_SRC_DIR = str(Path(__file__).resolve().parents[1] / "src")
if BOOTSTRAP_SRC_DIR not in sys.path:
    sys.path.insert(0, BOOTSTRAP_SRC_DIR)

from scripts.twse_local_encrypted_archive import (
    _key, _safe_output, encrypt_rows, verify_archive,
)
from scripts.twse_neon_remote_restore import create_backup_manifest, _object_key
from scripts.twse_archive_key_vault import resolve_archive_key
from scripts.twse_private_first_batch import _manifest_path, _save_manifest_exclusive
from src.twse_dated_history import (
    MIN_COVERAGE_SHARE, fetch_official_day,
    load_current_twse_allowed, _processed_days,
)
from src.official_market_feed import SOURCE, select_candidates

MAX_CALENDAR_SPAN_DAYS = 35
MAX_REQUESTED_SESSIONS = 8
MAX_SELECTED_ROWS_PER_DAY = 1500
MIN_ELIGIBLE_STOCKS = 700
SPARSE_THRESHOLD = 700

# Must be an existing 2330 reference session, sparse and unprocessed. A low
# count is a candidate to archive, NOT proof every issuer traded that day.
GAP_SQL = """
WITH sparse AS (
 SELECT trade_date, COUNT(*)::int AS observed
 FROM public.daily_prices
 WHERE market='twse' AND trade_date BETWEEN %s AND %s
 GROUP BY trade_date
 HAVING COUNT(*) FILTER (WHERE stock_id='2330') > 0
    AND COUNT(*) < 700
)
SELECT s.trade_date, s.observed
FROM sparse s
WHERE NOT EXISTS (
 SELECT 1 FROM public.twse_history_day_progress p
 WHERE p.trade_date=s.trade_date AND p.status IN ('imported','closed')
)
ORDER BY s.trade_date
LIMIT 8
"""


def _rolling_start(today):
    try:
        return today.replace(year=today.year - 5)
    except ValueError:
        return today.replace(year=today.year - 5, day=28)


def validate_bounds(start, end, *, today=None):
    today = today or datetime.now(ZoneInfo("Asia/Taipei")).date()
    if (type(start) is not date or type(end) is not date
            or start < _rolling_start(today) or end >= today
            or end < start or (end - start).days > MAX_CALENDAR_SPAN_DAYS
            or start.year != end.year):
        raise ValueError("Only 35-day windows in the latest rolling five years are eligible")
    return start, end


def choose_sparse_sessions(rows, *, start, end, processed, today=None):
    validate_bounds(start, end, today=today)
    if not isinstance(processed, set):
        raise ValueError("Official import receipt ledger is required")
    dates = []
    last = None
    for day, count in rows:
        if (type(day) is not date or type(count) is not int
                or count < 1 or count >= SPARSE_THRESHOLD or day.weekday() >= 5
                or day < start or day > end or
                (last is not None and day <= last)):
            raise ValueError("Invalid sparse official calendar candidate")
        last = day
        if day not in processed:
            dates.append(day)
    if not dates or len(dates) > MAX_REQUESTED_SESSIONS:
        raise ValueError("No verifiable unprocessed sparse TWSE sessions to archive")
    return dates


def preflight(database_url, *, start, end, today=None):
    """READ ONLY. Do not create optional progress tables or network requests."""
    validate_bounds(start, end, today=today)
    if not database_url:
        raise ValueError("Protected database URL required for read-only roster")
    import psycopg
    with psycopg.connect(
        database_url, connect_timeout=20,
    ) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        conn.execute("SET LOCAL statement_timeout='45000ms'")
        allowed = load_current_twse_allowed(conn)
        processed = _processed_days(conn)
        if (len(allowed) < MIN_ELIGIBLE_STOCKS
                or ("twse", "1589") in allowed):
            raise ValueError("Fresh current-listed, owner-excluded universe not proven")
        with conn.cursor() as cur:
            cur.execute(GAP_SQL, (start, end))
            sparse_rows = cur.fetchall()
    days = choose_sparse_sessions(
        sparse_rows, start=start, end=end, processed=processed, today=today
    )
    return days, allowed


def _canonical_source_rows(fetcher, dates, allowed):
    minimum = max(500, int(len(allowed) * MIN_COVERAGE_SHARE))
    for day in dates:
        received = fetcher(day)
        if received is None:
            raise ValueError("Candidate 2330 market date not confirmed by official source")
        verified = select_candidates(received, allowed, minimum=minimum)
        if not 500 <= len(verified) <= MAX_SELECTED_ROWS_PER_DAY:
            raise ValueError("Incomplete or impossibly large historical TWSE snapshot")
        captured = datetime.now(timezone.utc)
        for bar in sorted(verified, key=lambda x: x["stock_id"]):
            if (bar["market"] != "twse" or bar["trade_date"] != day
                    or bar["source"] != SOURCE["twse"]
                    or bar["stock_id"] == "1589"
                    or bar["volume"] is None or bar["volume"] < 0
                    or bar["turnover"] is None or bar["turnover"] < 0
                    or bar["close"] is None or bar["close"] <= 0):
                raise ValueError("Unverified TWSE source value or stock exclusion")
            # This is the time the historic source was retrieved for archival;
            # it must NEVER be represented as a 2022 as-of publication time.
            yield {**bar, "retrieved_at": captured}


def prepare_official_archive(
    database_url, *, start, end, archive_path, manifest_path,
    object_key, hex_key, fetcher=fetch_official_day, today=None,
):
    """Make only owner-local ciphertext + inventory; no remote or PG writes."""
    _key(hex_key)
    validate_bounds(start, end, today=today)
    obj_key = _object_key(object_key)
    if not obj_key.startswith(f"market=twse/year={start.year}/"):
        raise ValueError("Source year and manifested private archive key differ")
    destination = _safe_output(archive_path)
    inventory = _manifest_path(destination, manifest_path)
    days, allowed = preflight(
        database_url, start=start, end=end, today=today
    )
    exported = encrypt_rows(
        _canonical_source_rows(fetcher, days, allowed),
        destination, start=days[0], end=days[-1], hex_key=hex_key,
    )
    checked = verify_archive(destination, hex_key=hex_key)
    if checked["sample_rows"] != exported["rows"]:
        raise RuntimeError("Official source rows did not restore exactly")
    manifest = create_backup_manifest(
        destination, hex_key=hex_key, object_key=obj_key,
    )
    if manifest["authenticated_rows"] != checked["sample_rows"]:
        raise RuntimeError("Manifest doesn't agree with complete source receipt")
    _save_manifest_exclusive(inventory, manifest)
    return {
        "scope": "TWSE_5Y_SPARSE_OFFICIAL_DIRECT_AES_LOCAL_ONLY",
        "actual_official_session_dates": [d.isoformat() for d in days],
        "official_current_listed_survivors_only": True,
        "source_acquisition_timestamp_is_not_historical_publication_time": True,
        "encrypted_source_rows": exported["rows"],
        "remote_private_archive_verified": False,
        "historical_five_year_completeness_verified": False,
        "production_postgres_rows_written": 0,
        "production_postgres_rows_deleted": 0,
        "line_messages_sent": 0,
        "paid_upgrade_requested": False,
        "live_trading_approved": False,
    }


def main():
    cli = argparse.ArgumentParser(description="TWSE official missing dates directly to private AES archive")
    cli.add_argument("action", choices=("preview", "archive"))
    cli.add_argument("--start", type=date.fromisoformat, required=True)
    cli.add_argument("--end", type=date.fromisoformat, required=True)
    cli.add_argument("--archive", type=Path)
    cli.add_argument("--manifest", type=Path)
    cli.add_argument("--key-vault", type=Path)
    cli.add_argument("--object-key")
    options = cli.parse_args()
    try:
        if options.action == "preview":
            dates, allowed = preflight(
                os.environ.get("DATABASE_URL", ""),
                start=options.start, end=options.end,
            )
            out = {
                "scope": "TWSE_5Y_SPARSE_GAP_READ_ONLY_PREVIEW",
                "candidate_trade_dates_not_yet_source_verified":
                    [x.isoformat() for x in dates],
                "eligible_current_listed_stocks": len(allowed),
                "neon_rows_written": 0, "line_messages_sent": 0,
            }
        else:
            if not (options.archive and options.manifest and options.object_key):
                cli.error("archive requires a private file, manifest and object key")
            out = prepare_official_archive(
                os.environ.get("DATABASE_URL", ""),
                start=options.start, end=options.end,
                archive_path=options.archive,
                manifest_path=options.manifest,
                object_key=options.object_key,
                hex_key=resolve_archive_key(
                    vault_path=options.key_vault,
                    env_key=os.environ.get("STOCK_ARCHIVE_KEY_HEX", ""),
                ),
            )
    except Exception:
        # Hide provider URLs/DSN and transient source rows from public CI logs.
        raise SystemExit("Official private archive not verified; Neon unchanged") from None
    print(json.dumps(out, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
