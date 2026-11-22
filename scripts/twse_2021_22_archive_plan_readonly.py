"""2021-22 TWSE five-year official-source gap -> bounded owner-private AES archive plan.

READ ONLY. Sessions are 2330-backed *date anchors*, not proof that every
currently-listed issuer traded. Never downloads market data, persists historical
prices, exports secrets, sends LINE, or approves live model release.

Use the existing scripts.twse_official_direct_archive preview/archive, with
owner-local AES key custody, for each returned <=8-session same-month window.
Archived official rows must be source-authenticated separately; this planner
does not claim any missing price has been acquired.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta
from itertools import groupby
import json
import os
from zoneinfo import ZoneInfo

from scripts.twse_history_gap_audit import CALENDAR_SQL
from src.current_official_listing import CURRENT_OFFICIAL_LISTED_CTE
from src.twse_dated_history import has_source_write_budget

MAX_ANCHOR_DAYS = 600
MAX_DAYS_PER_ARCHIVE = 8
SPARSE_THRESHOLD = 700
MIN_ACTIVE_TWSE = 700
FIVE_YEAR_RESEARCH_END = date(2023, 1, 1)

METADATA_SQL = CURRENT_OFFICIAL_LISTED_CTE + """
SELECT
 (SELECT COUNT(*)::int FROM official_current_listed o
  JOIN public.stock_master m
    ON m.market=o.market AND m.stock_id=o.stock_id
  WHERE o.market='twse' AND NOT EXISTS (
   SELECT 1 FROM public.model_stock_exclusions x
   WHERE x.market=o.market AND x.stock_id=o.stock_id
  )) AS active_twse,
 (SELECT MAX(observed_at) FROM current_receipt) AS official_receipt,
 (SELECT COUNT(*)::int FROM public.model_stock_exclusions
  WHERE market='twse' AND stock_id='1589') AS exclusion_1589,
 pg_database_size(current_database())::bigint AS database_bytes
"""


def rolling_start(today: date) -> date:
    if type(today) is not date:
        raise ValueError("Current date required")
    try:
        return today.replace(year=today.year - 5)
    except ValueError:
        return today.replace(year=today.year - 5, day=28)


def plan(rows, metadata: dict, *, today: date, owner_aes_evidence=None) -> dict:
    """Build exact month-bounded archive previews, never a write instruction."""
    start = rolling_start(today)
    end = min(today, FIVE_YEAR_RESEARCH_END)
    if start >= end or not isinstance(metadata, dict):
        raise ValueError("No 2021-22 dates remain within the rolling five years")
    allowed = metadata.get("active_twse")
    exclusions = metadata.get("exclusion_1589")
    size = metadata.get("database_bytes")
    stamp = metadata.get("official_receipt")
    if (type(allowed) is not int or not MIN_ACTIVE_TWSE <= allowed <= 1500
            or type(exclusions) is not int or exclusions != 1
            or type(size) is not int or size < 0
            or type(stamp) is not datetime or stamp.tzinfo is None
            or stamp.date() > today
            or not 0 <= (today - stamp.date()).days <= 14):
        raise ValueError("Fresh official issuer roster, exclusion and actual size required")
    if not isinstance(rows, (tuple, list)) or not rows or len(rows) > MAX_ANCHOR_DAYS:
        raise ValueError("Missing or unbounded 2330-anchored official candidate dates")

    aes_days = frozenset()
    aes_files = 0
    if owner_aes_evidence is not None:
        if (not isinstance(owner_aes_evidence, dict)
                or owner_aes_evidence.get("full_file_integrity_verified") is not True
                or type(owner_aes_evidence.get("authenticated_private_files")) is not int
                or not 1 <= owner_aes_evidence["authenticated_private_files"] <= 72
                or not isinstance(owner_aes_evidence.get("days"), frozenset)
                or any(type(d) is not date or not start <= d < end
                       for d in owner_aes_evidence["days"])):
            raise ValueError("Complete authenticated local AES day evidence required")
        aes_days = owner_aes_evidence["days"]
        aes_files = owner_aes_evidence["authenticated_private_files"]

    sparse = []
    annual = defaultdict(lambda: {"reference_market_days": 0,
                                  "sparse_unprocessed_days": 0,
                                  "sparse_with_processed_receipt": 0})
    prev = None
    for record in rows:
        if not isinstance(record, (tuple, list)) or len(record) != 4:
            raise ValueError("Unexpected reference-day ledger shape")
        day, observed, imported, closed = record
        if (type(day) is not date or not start <= day < end or day.weekday() >= 5
                or prev is not None and day <= prev
                or type(observed) is not int or observed < 1 or observed > 1500
                or type(imported) is not int or imported not in (0, 1)
                or type(closed) is not int or closed not in (0, 1)
                or imported and closed):
            raise ValueError("Unreliable, unsorted or out-of-window reference day")
        prev = day
        status = annual[str(day.year)]
        status["reference_market_days"] += 1
        if observed < SPARSE_THRESHOLD:
            if imported or closed:
                status["sparse_with_processed_receipt"] += 1
            else:
                status["sparse_unprocessed_days"] += 1
                sparse.append(day)

    # Only confirmed 2330 anchors count. Never call an archive a source-day
    # substitute when the Neon official reference ledger cannot align it.
    referenced = {item[0] for item in rows}
    if not aes_days <= referenced:
        raise ValueError("Authenticated AES date does not match Neon trade-day anchor")
    already_archived = aes_days & set(sparse)
    pending = [d for d in sparse if d not in already_archived]
    batches = []
    for (year, month), iterator in groupby(pending, key=lambda d: (d.year, d.month)):
        dates = list(iterator)
        for i in range(0, len(dates), MAX_DAYS_PER_ARCHIVE):
            group = dates[i:i + MAX_DAYS_PER_ARCHIVE]
            begin, finish = group[0], group[-1]
            if (begin.year != finish.year or begin.month != finish.month
                    or (finish - begin).days > 35):
                raise ValueError("Owner archive cannot accept proposed date span")
            batches.append({
                "year_month": f"{year:04d}-{month:02d}",
                "start": begin.isoformat(),
                "end": finish.isoformat(),
                "known_sparse_anchor_days": len(group),
                "preview_command": (
                    "python -m scripts.twse_official_direct_archive preview "
                    f"--start {begin.isoformat()} --end {finish.isoformat()}"
                ),
                "official_source_downloaded_here": False,
                "encrypted_owner_archive_verified_here": False,
            })
    return {
        "schema_version": 1,
        "scope": "TWSE_2021_2022_ROLLING5Y_PRIVATE_AES_BATCH_PLAN_READ_ONLY",
        "research_date_start": start.isoformat(),
        "research_date_end_exclusive": end.isoformat(),
        "official_issuer_snapshot": stamp.isoformat(),
        "fresh_current_listed_allowed_twse": allowed,
        "owner_exclusion_1589_enforced": True,
        "anchored_days_scanned": len(rows),
        "sparse_unprocessed_days_to_independently_source_verify": len(sparse),
        "authenticated_existing_owner_aes_source_days_within_sparse_gaps": len(already_archived),
        "remaining_sparse_days_without_authenticated_owner_aes": len(pending),
        "owner_aes_files_fully_authenticated_on_local_machine": aes_files,
        "existing_archive_source_not_independently_rechecked_at_exchange_here": True,
        "years": dict(sorted(annual.items())),
        "bounded_private_archive_batch_count": len(batches),
        "batch_previews": batches,
        "production_pg_database_bytes": size,
        "production_source_insert_allowed_by_current_one_day_guard":
            has_source_write_budget(size, days=1),
        "source_year_2022_owner_local_aes_archives_must_be_checked_before_refetch": True,
        "not_proof_of_historical_listing_or_all_issuer_trade_days": True,
        "corporate_action_total_returns_verified": False,
        "private_archive_writes_performed": 0,
        "postgres_writes_performed": 0,
        "line_messages_sent": 0,
        "paid_services_used": False,
        "live_model_release": "BLOCKED",
    }


def read_only_plan(database_url: str, *, today: date | None = None,
                   owner_aes_evidence=None) -> dict:
    today = today or datetime.now(ZoneInfo("Asia/Taipei")).date()
    start = rolling_start(today)
    end = min(today, FIVE_YEAR_RESEARCH_END)
    if not database_url or start >= end:
        raise ValueError("Existing owner database access and eligible 2021-22 window required")
    import psycopg
    from psycopg.rows import dict_row, tuple_row
    with psycopg.connect(database_url, connect_timeout=20, row_factory=dict_row) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '45000ms'")
        metadata = dict(conn.execute(METADATA_SQL).fetchone())
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(CALENDAR_SQL, (start, end))
            rows = cur.fetchall()
        conn.rollback()
    return plan(rows, metadata, today=today,
                owner_aes_evidence=owner_aes_evidence)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="READ ONLY 2021-22 TWSE encrypted archive priority windows")
    parser.add_argument("--archive-dir", help="Existing owner-private .twseenc folder")
    parser.add_argument("--key-vault", help="Existing owner-private AES key vault")
    args = parser.parse_args()
    if bool(args.archive_dir) != bool(args.key_vault):
        parser.error("--archive-dir and --key-vault must be supplied together")
    today = datetime.now(ZoneInfo("Asia/Taipei")).date()
    evidence = None
    if args.archive_dir:
        from pathlib import Path
        from scripts.twse_archive_key_vault import resolve_archive_key
        from scripts.twse_local_aes_gap_dedup import authenticated_archive_days
        directory = Path(args.archive_dir).expanduser()
        if (directory.is_symlink() or not directory.is_dir()
                or any((p / ".git").exists() for p in
                       (directory, *directory.parents))):
            raise ValueError("Use a private local archive directory outside Git")
        paths = sorted(directory.glob("*.twseenc"))
        evidence = authenticated_archive_days(
            paths,
            hex_key=resolve_archive_key(
                vault_path=Path(args.key_vault),
                env_key=os.environ.get("STOCK_ARCHIVE_KEY_HEX", "")),
            start=rolling_start(today), end=min(today, FIVE_YEAR_RESEARCH_END))
    report = read_only_plan(os.environ.get("DATABASE_URL", ""), today=today,
                            owner_aes_evidence=evidence)
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
