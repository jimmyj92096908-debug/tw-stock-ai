"""Owner 2021 TWSE AES vs Neon 552 overlapped keys: READ-ONLY economic parity.

This evaluates prices/volume only for exact authenticated stock/date overlaps.
It never imports AES data to Neon, never creates inferred bars, never changes
LINE, and does not claim historical point-in-time universe/total-return proof.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import re

from scripts.twse_2021_22_traded_240_warmup_readonly import _private_archives, _private_file
from scripts.twse_2021_28day_aes_current_cohort_density_readonly import EXPECTED_DAYS
from scripts.twse_2021_28day_aes_neon_stockdate_union_readonly import (
    SCOPE as UNION_SCOPE,
    BEGIN, END,
)
from scripts.twse_2022_aes_neon_eligible_density_readonly import ELIGIBLE_SQL
from scripts.twse_local_aes_gap_dedup import authenticated_archive_days
from scripts.twse_local_encrypted_archive import verify_archive
from scripts.twse_archive_key_vault import resolve_archive_key
from src.current_official_listing import CURRENT_OFFICIAL_LISTED_CTE

SCOPE = "OWNER_TWSE_2021_AES_NEON_552_OVERLAP_OHLCV_ECONOMIC_PARITY_READONLY"
COMPARE_FIELDS = ("open", "high", "low", "close", "volume",
                  "turnover", "price_change", "transactions")
CRITICAL_FIELDS = ("open", "high", "low", "close", "volume")
SOURCE_TAGS = ("TWSE_STOCK_DAY", "TWSE_MI_INDEX_ALLBUT0999")
MAX_NEON_ROWS = 800
MAX_SOURCE_ROWS = 40_000
MAX_REPORT_BYTES = 145_000

READONLY_SQL = CURRENT_OFFICIAL_LISTED_CTE + """
, eligible AS (
 SELECT o.stock_id FROM official_current_listed o
 WHERE o.market='twse' AND o.stock_id<>'1589'
 AND NOT EXISTS (SELECT 1 FROM public.model_stock_exclusions x
                 WHERE x.market=o.market AND x.stock_id=o.stock_id)
)
SELECT p.trade_date,p.stock_id,p.source,p.open,p.high,p.low,p.close,
       p.volume,p.turnover,p.price_change,p.transactions
FROM public.daily_prices p
JOIN eligible e ON e.stock_id=p.stock_id
WHERE p.market='twse'
 AND p.trade_date >= DATE '2021-11-23'
 AND p.trade_date < DATE '2022-01-01'
 AND p.source IN ('TWSE_STOCK_DAY','TWSE_MI_INDEX_ALLBUT0999')
 AND p.close>0 AND p.volume>=0
ORDER BY p.trade_date,p.stock_id
LIMIT 801
"""


def validate_receipt(prior):
    if (not isinstance(prior, dict) or prior.get("schema_version") != 1
        or prior.get("scope") != UNION_SCOPE
        or prior.get("authenticated_owner_2021_source_dates") != 28
        or prior.get("prior_2021_aes_source_stock_date_pairs") != 26120
        or prior.get("prior_2021_neon_source_stock_date_pairs") != 552
        or prior.get("aes_neon_overlapping_source_stock_date_pairs") != 552
        or prior.get("aes_exclusive_source_stock_date_pairs") != 25568
        or prior.get("neon_exclusive_source_stock_date_pairs") != 0
        or prior.get("actual_deduplicated_aes_neon_stock_date_pairs") != 26120
        or prior.get("current_stocks_with_no_source_day_in_2021") != 153
        or prior.get("production_neon_writes") != 0
        or prior.get("line_messages_sent") != 0
        or prior.get("model_release") != "BLOCKED"):
        raise ValueError("Owner 2021 exact source-key union receipt is inconsistent")


def _valid_economic(row, field):
    value = row.get(field)
    if value is None:
        return None
    if field in ("volume", "transactions"):
        if type(value) is not int or value < 0:
            raise ValueError("Invalid original integer economic field")
        return value
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError("Loss of exact original decimal economic field")
    return value


def compare_economic(aes, neon):
    """Pure comparison preserving decimals; missing means unverifiable, not equal."""
    differences, missing = [], []
    for field in COMPARE_FIELDS:
        a = _valid_economic(aes, field)
        b = _valid_economic(neon, field)
        if a is None or b is None:
            missing.append(field)
        elif a != b:
            differences.append(field)
    return tuple(differences), tuple(missing)


def capture_readonly(url):
    if not isinstance(url, str) or not url.startswith(("postgresql://", "postgres://")):
        raise ValueError("Owner's protected Neon URL is required for read-only parity")
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(
        url, connect_timeout=15, row_factory=dict_row,
        options="-c default_transaction_read_only=on",
    ) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout='60000ms'")
        roster = [x["stock_id"] for x in conn.execute(ELIGIBLE_SQL).fetchall()]
        records = [dict(x) for x in conn.execute(READONLY_SQL).fetchall()]
        if len(records) > MAX_NEON_ROWS:
            raise ValueError("Unbounded or changed Neon 2021 source rows")
        conn.rollback()
    return roster, records


def evaluate(*, receipt, roster, aes_rows, neon_rows):
    validate_receipt(receipt)
    if (not isinstance(roster, list) or len(roster) != 1092
        or len(set(roster)) != 1092
        or any(not isinstance(x, str) or re.fullmatch(r"[0-9]{4}", x) is None
               or x == "1589" for x in roster)
        or not isinstance(aes_rows, dict) or len(aes_rows) != 26120
        or not isinstance(neon_rows, list) or len(neon_rows) != 552):
        raise ValueError("Current official survivor or 2021 AES-Neon source keys changed")

    allowed = set(roster)
    aes_days = Counter()
    for key, row in aes_rows.items():
        if (not isinstance(key, tuple) or len(key) != 2
            or type(key[0]) is not date or key[0] not in EXPECTED_DAYS
            or key[1] not in allowed or not isinstance(row, dict)
            or row.get("trade_date") != key[0]
            or row.get("stock_id") != key[1] or row.get("market") != "twse"
            or row.get("source") != "TWSE_MI_INDEX_ALLBUT0999"):
            raise ValueError("Non-2021, noneligible or inconsistent authenticated AES bar")
        aes_days[key[0]] += 1
    if set(aes_days) != set(EXPECTED_DAYS) or min(aes_days.values()) < 500:
        raise ValueError("Original 2021 28-day authentic AES cohort changed")
    # Reprove issuer-day histogram; an unchanged aggregate 26,120 is not enough.
    per_issuer = Counter(stock for _day, stock in aes_rows)
    if (sum(per_issuer[s] == 28 for s in allowed) != 900 or
        sum(per_issuer[s] >= 26 for s in allowed) != 916 or
        sum(per_issuer[s] == 0 for s in allowed) != 153):
        raise ValueError("Authenticated AES source-key cohort histogram drifted")

    seen = set()
    observed_days = set()
    counters = Counter()
    details = []
    full_match = 0
    critical_match = 0
    source_counts = Counter()
    for row in neon_rows:
        if not isinstance(row, dict):
            raise ValueError("Neon source row malformed")
        key = (row.get("trade_date"), row.get("stock_id"))
        if (type(key[0]) is not date or key[0] not in EXPECTED_DAYS
            or key[1] not in allowed or key in seen
            or row.get("source") not in SOURCE_TAGS or
            key not in aes_rows):
            raise ValueError("Neon duplicate, excluded or AES-nonoverlapping source key")
        seen.add(key)
        observed_days.add(key[0])
        source_counts[row["source"]] += 1
        different, missing = compare_economic(aes_rows[key], row)
        for field in different:
            counters["different_" + field] += 1
        for field in missing:
            counters["unverifiable_" + field] += 1
        if not different and not missing:
            full_match += 1
        if not any(k in CRITICAL_FIELDS for k in different + missing):
            critical_match += 1
        if different or missing:
            details.append({
                "trade_date": key[0].isoformat(),
                "stock_id": key[1],
                "source": row["source"],
                "different_fields": list(different),
                "unverifiable_fields": list(missing),
                "raw_private_prices_not_exported": True,
            })
    if len(seen) != 552 or observed_days != set(EXPECTED_DAYS):
        raise ValueError("Exactly 552 original overlapped bars on all 28 dates required")
    mismatched_critical = len(seen) - critical_match
    report = {
        "schema_version": 1,
        "scope": SCOPE,
        "current_2026_listed_survivor_cohort_only_not_historical_pit": True,
        "authenticated_2021_aes_source_days": 28,
        "authenticated_2021_aes_source_stockdate_keys": len(aes_rows),
        "original_neon_valid_source_stockdate_rows": len(seen),
        "exact_source_key_overlap": len(seen),
        "aes_exclusive_source_keys_never_written_to_neon": len(aes_rows) - len(seen),
        "neon_source_tags": dict(sorted(source_counts.items())),
        "economic_fields_compared": list(COMPARE_FIELDS),
        "complete_economic_field_matches": full_match,
        "critical_ohlcv_field_matches": critical_match,
        "critical_ohlcv_mismatch_or_unverifiable_rows": mismatched_critical,
        "per_field_different_or_unverifiable_counts": dict(sorted(counters.items())),
        "private_552_overlap_exceptions_without_prices": details,
        "all_552_critical_ohlcv_parity_verified": critical_match == 552,
        "all_552_extended_economic_parity_verified": full_match == 552,
        "missing_field_is_not_equal": True,
        "zero_source_153_not_proven_historical_no_trade": True,
        "historical_ipo_or_listing_point_in_time_proven": False,
        "corporate_action_adjusted_total_return_verified": False,
        "aes_exclusive_price_rows_approved_for_import": False,
        "restorable_full_neon_backup_verified": False,
        "safe_to_write_production_history": False,
        "model_release": "BLOCKED",
        "neon_writes": 0, "line_messages_sent": 0, "paid_services_used": False,
    }
    if len(json.dumps(report, ensure_ascii=False).encode("utf-8")) > MAX_REPORT_BYTES:
        raise ValueError("Bounded private exception report exceeded safety limit")
    return report


def run_owner(*, archive_2021, vault_path, prior_union, output, database_url):
    paths = _private_archives(archive_2021)
    prior_path = _private_file(prior_union, should_exist=True)
    destination = _private_file(output, should_exist=False)
    if destination == prior_path or any(p == destination for p in paths):
        raise ValueError("Private source and new report paths must be distinct")
    receipt = json.loads(prior_path.read_text(encoding="utf-8"))
    validate_receipt(receipt)
    key = resolve_archive_key(vault_path=Path(vault_path),
                              env_key=os.environ.get("STOCK_ARCHIVE_KEY_HEX", ""))
    before = {str(p): sha256(p.read_bytes()).hexdigest() for p in paths}
    proof = authenticated_archive_days(paths, hex_key=key, start=BEGIN, end=END)
    if proof.get("full_file_integrity_verified") is not True or \
       proof.get("days") != frozenset(EXPECTED_DAYS):
        raise ValueError("Owner AES 2021 28 source-date proofs changed")

    roster, neon_rows = capture_readonly(database_url)
    allowed = set(roster)
    relevant = {}
    visited = 0
    for file in paths:
        def accept(row):
            nonlocal visited
            visited += 1
            if visited > MAX_SOURCE_ROWS:
                raise ValueError("Unbounded original AES full archive")
            k = (row["trade_date"], row["stock_id"])
            if row["trade_date"] not in EXPECTED_DAYS:
                raise ValueError("Unexpected non-2021 AES source")
            if row["stock_id"] in allowed:
                if k in relevant:
                    raise ValueError("Duplicate authenticated AES stock/date")
                relevant[k] = row
        verified = verify_archive(file, hex_key=key, on_verified_row=accept)
        if verified["archive_integrity_verified"] is not True:
            raise ValueError("Unverified AES encrypted footer")
    if {str(p): sha256(p.read_bytes()).hexdigest() for p in paths} != before:
        raise ValueError("Private AES ciphertext modified during replay")
    report = evaluate(receipt=receipt, roster=roster,
                      aes_rows=relevant, neon_rows=neon_rows)
    with destination.open("x", encoding="utf-8") as fp:
        json.dump(report, fp, ensure_ascii=False, indent=2, allow_nan=False)
        fp.write("\n")
    print(json.dumps({
        "status": "TWSE_2021_552_AES_NEON_OHLCV_OVERLAP_READONLY_PASS",
        "overlapping_stockdate_keys": report["exact_source_key_overlap"],
        "complete_extended_economic_matches": report["complete_economic_field_matches"],
        "critical_ohlcv_matches": report["critical_ohlcv_field_matches"],
        "critical_ohlcv_unverified_or_different": report["critical_ohlcv_mismatch_or_unverifiable_rows"],
        "no_neon_writes": True,
        "line_messages_sent": 0,
        "model_release": "BLOCKED",
    }, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-2021", required=True)
    parser.add_argument("--key-vault", required=True)
    parser.add_argument("--prior-union", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    if os.getenv("CI") or os.getenv("GITHUB_ACTIONS"):
        raise SystemExit("Owner-private AES-Neon reconciliation cannot run on CI")
    try:
        run_owner(
            archive_2021=args.archive_2021,
            vault_path=args.key_vault,
            prior_union=args.prior_union,
            output=args.out, database_url=os.getenv("DATABASE_URL", ""),
        )
    except Exception:
        raise SystemExit(
            "Owner-private 2021 AES-Neon OHLCV parity FAILED safely; "
            "no source prices, keys, or Neon credentials printed; "
            "no Neon or LINE writes"
        ) from None


if __name__ == "__main__":
    main()
