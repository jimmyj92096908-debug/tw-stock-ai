"""Owner-private 2330-only 2021/22 virtual AES+Neon raw-source prefix canary.

Proves price provenance and source prefix isolation, NOT point-in-time listing,
dividend/capital-action adjustments, investability, alpha, historical market
completeness, a fully validated 5-year model, or authorization to trade/import.
Never writes SQL, LINE, or any plaintext price file.
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

from scripts.twse_2021_22_traded_240_warmup_readonly import _private_archives, _private_file
from scripts.twse_2021_28day_aes_current_cohort_density_readonly import EXPECTED_DAYS
from scripts.twse_2021_aes_exclusive_quality_readonly import SCOPE as QUALITY_SCOPE
from scripts.twse_2022_aes_neon_eligible_density_readonly import (
    ELIGIBLE_SQL, SCOPE as DENSITY_SCOPE,
)
from scripts.twse_local_aes_gap_dedup import authenticated_archive_days
from scripts.twse_local_encrypted_archive import verify_archive
from scripts.twse_archive_key_vault import resolve_archive_key

STOCK = "2330"
BULK = "TWSE_MI_INDEX_ALLBUT0999"
SECONDARY = "TWSE_STOCK_DAY"
SCOPE = "OWNER_2021_22_AES_NEON_2330_VIRTUAL_RAW_PREFIX_READONLY"
FIELDS = ("open", "high", "low", "close", "volume")
OPTIONAL = ("turnover", "price_change", "transactions")
MAX_NEON_ROWS = 320
MAX_REPORT_BYTES = 8_000
CUTOFFS = frozenset({date(2022, 12, 29), date(2022, 12, 30)})

NEON_SINGLE_ISSUER_SQL = """
SELECT market,stock_id,trade_date,source,open,high,low,close,volume,
       turnover,price_change,transactions
FROM public.daily_prices
WHERE market='twse' AND stock_id=%s
 AND trade_date BETWEEN DATE '2021-11-23' AND DATE '2022-12-30'
 AND source IN ('TWSE_MI_INDEX_ALLBUT0999','TWSE_STOCK_DAY')
 AND close>0 AND volume>=0
ORDER BY trade_date,stock_id
LIMIT 321
"""
BULK_DATES_SQL = """
SELECT DISTINCT trade_date FROM public.daily_prices
WHERE market='twse' AND source='TWSE_MI_INDEX_ALLBUT0999'
 AND trade_date >= DATE '2022-01-01' AND trade_date < DATE '2023-01-01'
ORDER BY trade_date LIMIT 100
"""


# Only these non-sensitive stage codes may leave the owner's computer.
# Never emit original exception messages (which may hold a URI, price or path).
AUDIT_STAGES = frozenset({
    "ARCHIVE_PATHS",
    "PRIVATE_RECEIPTS",
    "PREVIOUS_REPORT_GUARD",
    "AES_KEY_VAULT",
    "CIPHERTEXT_HASH",
    "AES_2021_AUTHENTICATION",
    "AES_2022_AUTHENTICATION",
    "NEON_READONLY_SNAPSHOT",
    "AES_2021_2330_REPLAY",
    "AES_2022_2330_REPLAY",
    "ARCHIVE_IMMUTABILITY",
    "SOURCE_2022_CALENDAR",
    "AES_NEON_2330_CORE_OHLCV",
    "VIRTUAL_PREFIX_EVALUATION",
    "PRIVATE_RECEIPT_WRITE",
    "UNCLASSIFIED",
})


class VirtualAuditStageError(ValueError):
    """Sanitized error. Its only public text is a code from AUDIT_STAGES."""

    def __init__(self, code):
        self.code = code if code in AUDIT_STAGES else "UNCLASSIFIED"
        super().__init__(self.code)


def _stage(code, callback, *args, **kwargs):
    if code not in AUDIT_STAGES:
        raise VirtualAuditStageError("UNCLASSIFIED")
    try:
        return callback(*args, **kwargs)
    except VirtualAuditStageError:
        raise
    except Exception:
        raise VirtualAuditStageError(code) from None


def _failure_message(stage):
    safe = stage if stage in AUDIT_STAGES else "UNCLASSIFIED"
    return (
        "Owner 2021/22 2330 AES+Neon virtual prefix FAILED safely; "
        "diagnostic_stage=" + safe
        + "; no raw prices, key vault, Neon URL, local path, SQL writes or LINE data disclosed"
    )


def validate_receipts(quality, density):
    if (not isinstance(quality, dict) or not isinstance(density, dict)
        or quality.get("scope") != QUALITY_SCOPE
        or quality.get("verified_original_aes_source_stockdate_keys") != 26120
        or quality.get("verified_original_neon_overlap_keys") != 552
        or quality.get("original_552_overlap_critical_ohlcv_parity_revalidated") is not True
        or quality.get("aes_exclusive_stockdate_source_keys") != 25568
        or quality.get("aes_exclusive_source_keys_with_sane_core_ohlcv") != 25568
        or quality.get("aes_exclusive_distinct_current_survivor_issuers") != 919
        or quality.get("aes_exclusive_missing_optional_economic_field_counts") != {}
        or quality.get("production_backfill_approved") is not False
        or quality.get("model_release") != "BLOCKED"
        or quality.get("neon_writes") != 0
        or quality.get("line_messages_sent") != 0
        or density.get("scope") != DENSITY_SCOPE
        or density.get("aes_prior_2022_source_calendar_dates") != 162
        or density.get("neon_original_bulk_source_calendar_dates") != 84
        or density.get("aes_neon_merged_days_with_at_least_500_current_eligible_stock_bars") != 246
        or density.get("aes_neon_current_listed_stocks_with_all_246_source_dates") != 825
        or density.get("model_release") != "BLOCKED"
        or density.get("neon_writes") != 0
        or density.get("line_messages_sent") != 0):
        raise ValueError("Real 2021 quality / 2022 density source receipt is missing or inconsistent")


def _validate_bar(row, *, aes=False):
    if not isinstance(row, dict) or row.get("market") != "twse" or row.get("stock_id") != STOCK:
        raise ValueError("Foreign or excluded source stock")
    d = row.get("trade_date")
    if (type(d) is not date or d not in EXPECTED_DAYS and not d.year == 2022 or
        row.get("source") not in ((BULK,) if aes else (BULK, SECONDARY))):
        raise ValueError("Unapproved source provenance or date")
    prices = [row.get(f) for f in FIELDS[:4]]
    v = row.get("volume")
    if (any(type(x) is not Decimal or not x.is_finite() or x <= 0 for x in prices)
        or not prices[2] <= min(prices[0], prices[3]) <= max(prices[0], prices[3]) <= prices[1]
        or type(v) is not int or v < 0):
        raise ValueError("Invalid exact Decimal OHLCV")
    for f in OPTIONAL:
        x = row.get(f)
        if x is None:
            continue
        if f == "transactions":
            if type(x) is not int or x < 0:
                raise ValueError("Invalid integer transactions")
        elif type(x) is not Decimal or not x.is_finite():
            raise ValueError("Invalid optional decimal economic field")


def stitch(*, quality, density, aes21, aes22, neon_rows, bulk_days, cutoff):
    """Pure provenance-conserving virtual prefix; never emits prices publicly."""
    validate_receipts(quality, density)
    if (type(cutoff) is not date or cutoff not in CUTOFFS
        or not isinstance(aes21, list) or not isinstance(aes22, list)
        or not isinstance(neon_rows, list)
        or not isinstance(bulk_days, list) or len(bulk_days) != 84
        or len(set(bulk_days)) != 84
        or any(type(d) is not date or d.year != 2022 or d.weekday() >= 5
               for d in bulk_days)
        or len(neon_rows) > MAX_NEON_ROWS):
        raise ValueError("Invalid read-only 2330 market-source snapshot size or cutoff")
    if set(r["trade_date"] for r in aes21) != set(EXPECTED_DAYS) or len(aes21) != 28:
        raise ValueError("2021 original 2330 28-day source anchor changed")
    if len(aes22) != 162 or len(set(r["trade_date"] for r in aes22)) != 162:
        raise ValueError("2022 original 2330 162-day source anchor changed")

    local = {}
    source_days_2022 = set()
    for year, source in ((2021, aes21), (2022, aes22)):
        for row in source:
            _validate_bar(row, aes=True)
            d = row["trade_date"]
            if d.year != year or d in local:
                raise ValueError("Overlapping or incorrect local AES source date")
            local[d] = row
            if year == 2022:
                source_days_2022.add(d)
    if (source_days_2022 & set(bulk_days) or
        len(source_days_2022 | set(bulk_days)) != 246 or
        min(source_days_2022 | set(bulk_days)) != date(2022,1,3) or
        max(source_days_2022 | set(bulk_days)) != date(2022,12,30)):
        raise VirtualAuditStageError("SOURCE_2022_CALENDAR")

    combined = dict(local)
    neon_keys = set()
    core_parity = 0
    optional_differences = Counter()
    neon_2022_verified_bulk_calendar_days = set()
    neon_source_counts = Counter()
    for row in neon_rows:
        _validate_bar(row)
        d = row["trade_date"]
        if d in neon_keys:
            raise ValueError("Duplicate official Neon 2330 day")
        neon_keys.add(d)
        neon_source_counts[row["source"]] += 1
        if d.year == 2022:
            # The 84 BULK dates are a *market-wide* provenance calendar.
            # A 2330 stock/date on those dates may itself be independently
            # sourced from TWSE_STOCK_DAY. The source tag of one issuer is
            # not proof that every issuer uses the market-wide source tag.
            if row["source"] == BULK and d not in bulk_days:
                raise ValueError("2022 issuer bulk provenance outside verified bulk calendar")
            if d in bulk_days:
                neon_2022_verified_bulk_calendar_days.add(d)
        if d in combined:
            original = combined[d]
            if any(original[f] != row[f] for f in FIELDS):
                raise VirtualAuditStageError("AES_NEON_2330_CORE_OHLCV")
            for f in OPTIONAL:
                if original.get(f) is None or row.get(f) is None:
                    optional_differences["unverifiable_" + f] += 1
                elif original[f] != row[f]:
                    optional_differences["different_" + f] += 1
            core_parity += 1
        else:
            if d.year != 2022 or d not in bulk_days:
                raise VirtualAuditStageError("SOURCE_2022_CALENDAR")
            combined[d] = row
    if neon_2022_verified_bulk_calendar_days != set(bulk_days):
        raise VirtualAuditStageError("SOURCE_2022_CALENDAR")
    year22 = {d for d in combined if d.year == 2022}
    if year22 != source_days_2022 | set(bulk_days):
        raise VirtualAuditStageError("SOURCE_2022_CALENDAR")
    if len(combined) != 28 + 246:
        raise ValueError("Insufficient authenticated source days for virtual history")

    prefix_dates = [d for d in sorted(combined) if d <= cutoff]
    if len(prefix_dates) < 240 or prefix_dates[-1] != cutoff:
        raise ValueError("No sufficient real 2330 raw source observations at cutoff")
    last240 = prefix_dates[-240:]
    raw_sma240 = sum((combined[d]["close"] for d in last240), Decimal(0)) / Decimal(240)
    h = sha256()
    for d in prefix_dates:
        r = combined[d]
        h.update((d.isoformat() + "|" + "|".join(str(r[f]) for f in FIELDS) + "\n").encode("utf-8"))
    return {
        "schema_version": 1,
        "scope": SCOPE,
        "stock_id": STOCK,
        "as_of": cutoff.isoformat(),
        "original_2021_authenticated_market_source_days": 28,
        "original_2022_authenticated_aes_market_source_days": 162,
        "neon_2022_authenticated_bulk_source_days": 84,
        "virtual_2022_source_calendar_days": 246,
        "virtual_2021_22_combined_source_days": len(combined),
        "neon_AES_overlapping_2330_source_stockdate_keys": core_parity,
        "neon_2022_market_bulk_calendar_days_with_2330_bar": len(neon_2022_verified_bulk_calendar_days),
        "neon_2330_official_price_source_tags": dict(sorted(neon_source_counts.items())),
        "neon_AES_overlap_OHLCV_exact": True,
        "neon_AES_optional_field_discrepancies": dict(sorted(optional_differences.items())),
        "as_of_raw_prefix_source_days": len(prefix_dates),
        "as_of_last_240_observed_source_days": 240,
        "as_of_last_source_date": prefix_dates[-1].isoformat(),
        "as_of_raw_unadjusted_sma240_private_research_value": str(raw_sma240),
        "as_of_raw_prefix_sha256_private": h.hexdigest(),
        "source_rows_after_asof_used_in_computation": 0,
        "physical_historical_rows_written_to_neon": 0,
        "all_five_year_market_data_complete": False,
        "survivorship_free_historical_universe_verified": False,
        "corporate_action_and_publication_vintage_verified": False,
        "raw_unadjusted_sma240_is_tradable_signal": False,
        "authoritative_holdout_alpha_verified": False,
        "production_backfill_approved": False,
        "model_release": "BLOCKED",
        "neon_writes": 0,
        "line_messages_sent": 0,
        "paid_services_used": False,
    }


def capture_neon(url):
    if not isinstance(url, str) or not url.startswith(("postgresql://","postgres://")):
        raise ValueError("Owner protected Neon DATABASE_URL required")
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(url, connect_timeout=15, row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout='90000ms'")
        roster = [r["stock_id"] for r in conn.execute(ELIGIBLE_SQL).fetchall()]
        if len(roster) != 1092 or STOCK not in roster or "1589" in roster:
            raise ValueError("Current official listed issuer roster changed")
        bulk_days = [r["trade_date"] for r in conn.execute(BULK_DATES_SQL).fetchall()]
        neon = [dict(r) for r in conn.execute(NEON_SINGLE_ISSUER_SQL, (STOCK,)).fetchall()]
        if len(neon) > MAX_NEON_ROWS:
            raise ValueError("Too many Neon 2021/22 2330 original source rows")
        conn.rollback()
    return bulk_days, neon


def _authenticated_selected(paths, key, year, expected_days):
    source_days = set()
    result = []
    for path in paths:
        days_in_file = set()
        def consume(r):
            d = r["trade_date"]
            if type(d) is not date or d.year != year:
                raise ValueError("Unexpected source year in owner AES ciphertext")
            days_in_file.add(d)
            if r["stock_id"] == STOCK:
                _validate_bar(r, aes=True)
                result.append(r)
        proof = verify_archive(path, hex_key=key, on_verified_row=consume)
        if proof["archive_integrity_verified"] is not True:
            raise ValueError("Source AES-GCM final footer failed")
        if source_days & days_in_file:
            raise ValueError("Duplicate original AES source trading day")
        source_days.update(days_in_file)
    if len(source_days) != expected_days or len(result) != expected_days:
        raise ValueError("Owner-original source day count or 2330 anchor changed")
    if year == 2021 and source_days != set(EXPECTED_DAYS):
        raise ValueError("Owner-authenticated exact 2021 28-day source calendar changed")
    return result


def run_owner(*, archive21, archive22, vault, quality_path, density_path, out, cutoff, url):
    paths21 = _stage("ARCHIVE_PATHS", _private_archives, archive21)
    paths22 = _stage("ARCHIVE_PATHS", _private_archives, archive22)
    previous21 = _stage("PRIVATE_RECEIPTS", _private_file, quality_path, should_exist=True)
    previous22 = _stage("PRIVATE_RECEIPTS", _private_file, density_path, should_exist=True)
    destination = _stage("PRIVATE_RECEIPTS", _private_file, out, should_exist=False)
    if len({previous21, previous22, destination}) != 3 or any(
        p == destination for p in paths21 + paths22
    ):
        raise VirtualAuditStageError("PRIVATE_RECEIPTS")

    quality = _stage("PREVIOUS_REPORT_GUARD", lambda: json.loads(
        previous21.read_text(encoding="utf-8")))
    density = _stage("PREVIOUS_REPORT_GUARD", lambda: json.loads(
        previous22.read_text(encoding="utf-8")))
    _stage("PREVIOUS_REPORT_GUARD", validate_receipts, quality, density)

    key = _stage(
        "AES_KEY_VAULT", resolve_archive_key,
        vault_path=Path(vault), env_key=os.environ.get("STOCK_ARCHIVE_KEY_HEX", ""),
    )
    originals = paths21 + paths22
    start_hashes = _stage(
        "CIPHERTEXT_HASH",
        lambda: {str(p): sha256(p.read_bytes()).hexdigest() for p in originals},
    )

    for paths, start, end, expected, phase in (
        (paths21, date(2021,11,23), date(2022,1,1), 28, "AES_2021_AUTHENTICATION"),
        (paths22, date(2022,1,1), date(2023,1,1), 162, "AES_2022_AUTHENTICATION"),
    ):
        proof = _stage(
            phase, authenticated_archive_days,
            paths, hex_key=key, start=start, end=end,
        )
        if proof.get("full_file_integrity_verified") is not True or len(proof["days"]) != expected:
            raise VirtualAuditStageError(phase)

    # Still a single, server-enforced read-only snapshot; no data price logged.
    bulk_days, neon = _stage("NEON_READONLY_SNAPSHOT", capture_neon, url)
    aes21 = _stage("AES_2021_2330_REPLAY", _authenticated_selected, paths21, key, 2021, 28)
    aes22 = _stage("AES_2022_2330_REPLAY", _authenticated_selected, paths22, key, 2022, 162)
    same_originals = _stage(
        "ARCHIVE_IMMUTABILITY",
        lambda: all(sha256(p.read_bytes()).hexdigest() == start_hashes[str(p)]
                    for p in originals),
    )
    if not same_originals:
        raise VirtualAuditStageError("ARCHIVE_IMMUTABILITY")

    report = _stage(
        "VIRTUAL_PREFIX_EVALUATION", stitch,
        quality=quality, density=density, aes21=aes21, aes22=aes22,
        neon_rows=neon, bulk_days=bulk_days, cutoff=cutoff,
    )
    raw = _stage(
        "PRIVATE_RECEIPT_WRITE",
        lambda: json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
    )
    if len(raw.encode("utf-8")) > MAX_REPORT_BYTES:
        raise VirtualAuditStageError("PRIVATE_RECEIPT_WRITE")

    def write_owner_only():
        with destination.open("x", encoding="utf-8") as f:
            f.write(raw)
    _stage("PRIVATE_RECEIPT_WRITE", write_owner_only)

    # No price, address, credential, hash, private file path or stock-date leaves stdout.
    print(json.dumps({
        "status": "OWNER_2021_22_2330_VIRTUAL_AES_NEON_RAW_PREFIX_READONLY_PASS",
        "cutoff": report["as_of"],
        "virtual_source_days": report["virtual_2021_22_combined_source_days"],
        "used_prefix_days": report["as_of_raw_prefix_source_days"],
        "core_source_parity": report["neon_AES_overlap_OHLCV_exact"],
        "raw_sma240_not_a_trading_signal": True,
        "production_backfill_approved": False,
        "model_release": "BLOCKED",
        "neon_writes": 0,
        "line_messages_sent": 0,
    }, ensure_ascii=False))

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive-2021", required=True)
    p.add_argument("--archive-2022", required=True)
    p.add_argument("--key-vault", required=True)
    p.add_argument("--prior-2021-quality", required=True)
    p.add_argument("--prior-2022-density", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--as-of", default="2022-12-30", choices=("2022-12-29","2022-12-30"))
    args = p.parse_args()
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        raise SystemExit("Never load owner AES archive/key/Neon credentials in CI")
    try:
        run_owner(
            archive21=args.archive_2021, archive22=args.archive_2022,
            vault=args.key_vault, quality_path=args.prior_2021_quality,
            density_path=args.prior_2022_density, out=args.out,
            cutoff=date.fromisoformat(args.as_of),
            url=os.environ.get("DATABASE_URL", ""))
    except VirtualAuditStageError as exc:
        raise SystemExit(_failure_message(exc.code)) from None
    except Exception:
        raise SystemExit(_failure_message("UNCLASSIFIED")) from None


if __name__ == "__main__":
    main()
