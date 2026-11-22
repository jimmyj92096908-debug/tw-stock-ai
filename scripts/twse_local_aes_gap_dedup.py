"""Authenticate owner-private TWSE AES sources before planning a duplicate download.

Read/verify full ciphertext locally. Only a real official-source day with
>=500 unique, sane daily bars AND a 2330 bar counts as a reusable source day.
Never treat an archive filename, unchecked header, summary JSON, or partial
AES frame as proof. No plaintext output, SQL write, upload, LINE or spending.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
import re

from scripts.twse_local_archive_custody_audit import MAX_ARCHIVE_BYTES
from scripts.twse_local_encrypted_archive import verify_archive, _key

MAX_SCANNED_ARCHIVES = 72
MAX_DAILY_BARS = 1500
MIN_DAILY_BARS = 500
MAX_ARCHIVE_DAYS = 36
SOURCE = "TWSE_MI_INDEX_ALLBUT0999"


def authenticated_archive_days(paths, *, hex_key: str, start: date, end: date):
    """Return verified session dates in [start,end); no unverified-day shortcuts.

    Paths must point to files on the owner's private local disk; even archives
    from outside the requested date range are authenticated before exclusion.
    Overlap across files is rejected to prevent duplicate/corrupt inventories.
    """
    _key(hex_key)
    if (type(start) is not date or type(end) is not date or not start < end
            or not isinstance(paths, (list, tuple))
            or not 1 <= len(paths) <= MAX_SCANNED_ARCHIVES):
        raise ValueError("Bounded private archive inventory and window required")
    verified_days = set()
    seen_paths = set()
    source_rows = 0
    skipped_files = 0
    for item in paths:
        p = Path(item).expanduser()
        if p.is_symlink() or not p.is_file() or p.suffix != ".twseenc":
            raise ValueError("Only regular private encrypted archives are supported")
        p = p.resolve()
        if (p in seen_paths or p.stat().st_size > MAX_ARCHIVE_BYTES
                or any((parent / ".git").exists()
                       for parent in (p.parent, *p.parents))):
            raise ValueError("Repeated, unsafe or public-checkout archive")
        seen_paths.add(p)
        counts = Counter()
        stocks = set()
        checked_rows = 0

        def accept(row):
            nonlocal checked_rows
            checked_rows += 1
            d, stock = row.get("trade_date"), row.get("stock_id")
            numbers = [row.get(k) for k in ("open", "high", "low", "close")]
            volume = row.get("volume")
            if (row.get("market") != "twse" or row.get("source") != SOURCE
                    or type(d) is not date or d.weekday() >= 5
                    or not isinstance(stock, str) or not re.fullmatch(r"[0-9]{4}", stock)
                    or stock == "1589"
                    or any(type(v) is not Decimal or not v.is_finite() or v <= 0
                           for v in numbers)
                    or not numbers[2] <= min(numbers[0], numbers[3])
                         <= max(numbers[0], numbers[3]) <= numbers[1]
                    or type(volume) is not int or volume < 0):
                raise ValueError("Invalid official archived day, OHLCV or excluded issuer")
            counts[d] += 1
            if counts[d] > MAX_DAILY_BARS or len(counts) > MAX_ARCHIVE_DAYS:
                raise ValueError("Unbounded or impossible daily AES source coverage")
            if stock == "2330":
                stocks.add(d)

        proof = verify_archive(p, hex_key=hex_key, on_verified_row=accept)
        if (proof["archive_integrity_verified"] is not True
                or proof["sample_rows"] != checked_rows):
            raise ValueError("Private AES archive not fully authenticated")
        # A genuine 2022 full-market source has far more than 500 rows.
        # A partial/canary or one-stock archive must NEVER suppress a download.
        if any(n < MIN_DAILY_BARS for n in counts.values()):
            raise ValueError("Insufficient official whole-market rows in AES session")
        if any(d not in stocks for d in counts):
            raise ValueError("Archive trading day lacks official 2330 anchor")
        overlap = verified_days & set(counts)
        if overlap:
            raise ValueError("Overlapping authenticated archive trading dates")
        verified_days.update(counts)
        source_rows += checked_rows
        if not any(start <= d < end for d in counts):
            skipped_files += 1
    return {
        "days": frozenset(d for d in verified_days if start <= d < end),
        "authenticated_private_files": len(paths),
        "authenticated_private_source_rows": source_rows,
        "out_of_window_private_files_authenticated": skipped_files,
        "full_file_integrity_verified": True,
        "live_exchange_refetch_avoided_only_for_authentic_source_days": True,
        "current_2026_listing_revalidated_for_each_archived_bar": False,
        "historical_asof_publication_time_verified": False,
        "independent_official_publication_rechecked_here": False,
        "private_archive_copies_physically_independent_verified": False,
        "postgres_writes": 0,
        "line_messages": 0,
    }
