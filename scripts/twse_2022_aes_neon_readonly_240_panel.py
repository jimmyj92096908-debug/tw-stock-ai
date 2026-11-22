"""Read-only 2022 TWSE: owner AES evidence + existing Neon sources, research ONLY.

Original current-listed-only AES source archives are authenticated locally.
The Neon connection uses a server-enforced read-only transaction to obtain
2022 official market-session dates and *only 20 frozen research identifiers*.
Matching OHLCV duplicate keys must agree exactly. At most 20 stock series are
held in RAM for exact SMA240 and a bounded causal 12-feature spotcheck.
Does NOT certify complete historic exchange calendar, PIT issuer membership,
corporate actions, total returns, model alpha or production release.
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

from scripts.twse_2022_aes_factor_readiness import (
    YEAR, MAX_DAYS, SOURCE_TAG, _bar_ok, _ordered_paths, audit as audit_aes,
)
from scripts.twse_local_encrypted_archive import verify_archive
from scripts.twse_archive_key_vault import resolve_archive_key
from scripts.twse_stateless_240_monthly_factor import exact_sma240
from src.raw_factor_feature_bridge import FEATURE_NAMES, build_research_features

FROZEN_STOCKS = (
    "1103", "1201", "1216", "1301", "1303", "2002", "2207", "2303",
    "2308", "2317", "2327", "2330", "2357", "2379", "2382", "2412",
    "2454", "2603", "2881", "6505",
)
FIELDS = ("open", "high", "low", "close", "volume",
          "turnover", "price_change", "transactions")
SMA_DAYS = 240
MAX_NEON_STOCK_ROWS = 20 * MAX_DAYS
SQL_NEON_DAYS = """
SELECT DISTINCT trade_date
FROM public.daily_prices
WHERE market='twse' AND source='TWSE_MI_INDEX_ALLBUT0999'
  AND trade_date >= DATE '2022-01-01' AND trade_date < DATE '2023-01-01'
ORDER BY trade_date
"""
SQL_NEON_PANEL = """
SELECT market,stock_id,trade_date,open,high,low,close,volume,
       turnover,price_change,transactions,source,retrieved_at
FROM public.daily_prices
WHERE market='twse' AND source='TWSE_MI_INDEX_ALLBUT0999'
  AND trade_date >= DATE '2022-01-01' AND trade_date < DATE '2023-01-01'
  AND stock_id = ANY(%s::varchar[])
ORDER BY trade_date,stock_id
"""


def _same_price(a, b):
    # No silent preference for a conflicting archive / database price.
    return all(a.get(k) == b.get(k) for k in FIELDS)


def reconcile(local_rows, neon_rows, neon_days, *,
              stocks=FROZEN_STOCKS, local_audit=None):
    """Pure audited combination. Tests inject fake Neon rows; no DB needed."""
    if (not isinstance(stocks, (tuple, list)) or not stocks
            or len(set(stocks)) != len(stocks)
            or len(stocks) > len(FROZEN_STOCKS)
            or any(s not in FROZEN_STOCKS for s in stocks)):
        raise ValueError("Only bounded frozen currently listed research IDs accepted")
    target = set(stocks)
    panel = {}
    local_days = set()
    local_target = set()
    local_rows_seen = 0
    for row in local_rows:
        _bar_ok(row)
        local_rows_seen += 1
        if local_rows_seen > 600_000:
            raise ValueError("Too many original AES rows")
        d = row["trade_date"]
        local_days.add(d)
        sid = row["stock_id"]
        if sid not in target:
            continue
        key = (d, sid)
        if key in local_target:
            raise ValueError("Repeated source stock-day in local AES")
        local_target.add(key)
        panel[key] = row
    if local_audit is not None and (
            local_rows_seen != local_audit["authenticated_source_rows"]
            or len(local_days) != local_audit["authentic_distinct_2022_source_sessions"]):
        raise ValueError("Authenticated AES source changed between verification and replay")

    other_days = set()
    for d in neon_days:
        if type(d) is not date or d.year != YEAR or d.weekday() >= 5:
            raise ValueError("Invalid Neon official 2022 source trading date")
        if d in other_days:
            raise ValueError("Duplicate Neon source calendar date")
        other_days.add(d)
    if len(other_days) > MAX_DAYS:
        raise ValueError("Unbounded Neon source trading calendar")
    overlap = 0
    neon_target = set()
    neon_count = 0
    for row in neon_rows:
        neon_count += 1
        if neon_count > MAX_NEON_STOCK_ROWS:
            raise ValueError("Unexpected Neo frozen panel volume")
        _bar_ok(row)
        sid = row["stock_id"]
        if sid not in target or row["trade_date"] not in other_days:
            raise ValueError("Unrequested Neon record / absent market source day")
        key = (row["trade_date"], sid)
        if key in neon_target:
            raise ValueError("Duplicate database official stock-day record")
        neon_target.add(key)
        if key in panel:
            if not _same_price(panel[key], row):
                raise ValueError("Local AES and Neon OHLCV/source event discrepancy")
            overlap += 1
        else:
            panel[key] = row

    calendar = sorted(local_days | other_days)
    if not calendar or len(calendar) > MAX_DAYS:
        raise ValueError("No or excessive verified official source days")
    last = calendar[-1]
    eligible = []
    fingerprint = sha256()
    spotchecks = 0
    prior_parity = 0
    sma_count = 0
    if len(calendar) >= SMA_DAYS:
        last240 = set(calendar[-SMA_DAYS:])
        for sid in sorted(target):
            if not all((day, sid) in panel for day in last240):
                continue
            ordered = sorted((row for (day, stock), row in panel.items()
                              if stock == sid and day <= last),
                             key=lambda r: r["trade_date"])
            mean = sum((panel[(d, sid)]["close"] for d in calendar[-SMA_DAYS:]),
                       Decimal("0")) / Decimal(SMA_DAYS)
            if exact_sma240(ordered, asof=last) != mean:
                raise ValueError("Combined 240-day Decimal SMA source parity failed")
            fingerprint.update(f"{sid}|{mean}\n".encode())
            eligible.append(sid)
            sma_count += 1
            if spotchecks < 5:
                features = build_research_features(
                    ordered, market="twse", stock_id=sid,
                    cutoff=last, signal_dates=[last])
                if (features["included_signals"] != 1
                        or len(features["signals"][0]["feature_vector"]) !=
                        len(FEATURE_NAMES)
                        or features["live_trading_approved"]):
                    raise ValueError("Combined TWSE RAW technical/SMC source failure")
                fingerprint.update(json.dumps(
                    features["signals"][0]["feature_vector"], allow_nan=False,
                    separators=(",", ":")).encode())
                spotchecks += 1
                if (len(ordered) >= SMA_DAYS + 1 and
                        ordered[-2]["trade_date"] == calendar[-2]):
                    prior = ordered[-2]["trade_date"]
                    prior_one = build_research_features(
                        ordered[:-1], market="twse", stock_id=sid,
                        cutoff=prior, signal_dates=[prior])
                    prior_future = build_research_features(
                        ordered, market="twse", stock_id=sid,
                        cutoff=last, signal_dates=[prior])
                    if (prior_one["included_signals"] != 1
                            or prior_future["included_signals"] != 1
                            or prior_one["signals"][0]["feature_vector"] !=
                            prior_future["signals"][0]["feature_vector"]):
                        raise ValueError("Combined 12-factor future-label leakage")
                    prior_parity += 1

    return {
        "schema_version": 1,
        "scope": "TWSE_2022_LOCAL_AES_EXISTING_NEON_READONLY_FROZEN20_FACTOR_RESEARCH",
        "local_2022_source_sessions": len(local_days),
        "neon_source_sessions": len(other_days),
        "overlapping_source_sessions": len(local_days & other_days),
        "unique_observed_2022_source_sessions": len(calendar),
        "first_combined_session": calendar[0].isoformat(),
        "last_combined_session": calendar[-1].isoformat(),
        "remaining_observed_sessions_to_240":
            max(0, SMA_DAYS - len(calendar)),
        "local_authenticated_source_rows": local_rows_seen,
        "neon_frozen_cohort_source_rows_read": neon_count,
        "exact_duplicate_stock_day_ohlcv_matches": overlap,
        "frozen_current_research_stock_count": len(stocks),
        "frozen_stocks_with_complete_last_240_source_sessions": len(eligible),
        "exact_decimal_sma240_computed_in_ram": sma_count,
        "raw_12_factor_vectors_spotchecked": spotchecks,
        "causal_prefix_parity_checks": prior_parity,
        "private_result_fingerprint_sha256":
            fingerprint.hexdigest() if sma_count else None,
        "complete_historical_exchange_calendar_independently_verified": False,
        "historical_delisted_survivorship_bias_removed": False,
        "true_2022_publication_vintage_verified": False,
        "dividends_splits_or_total_return_adjusted": False,
        "complete_five_year_history_verified": False,
        "neon_transaction_mode": "READ_ONLY",
        "neon_write_operations": 0,
        "local_persistent_factor_rows": 0,
        "line_messages_sent": 0,
        "extra_paid_services": False,
        "production_model_weights_modified": False,
        "live_model_release_decision": "BLOCKED",
    }


def _authenticated_rows(paths, *, hex_key, expected_bundle_digest):
    ordered, _ = _ordered_paths(paths, hex_key=hex_key)
    digest_parts = []
    def produce():
        for _, _, path in ordered:
            buf = []
            proof = verify_archive(path, hex_key=hex_key,
                                   on_verified_row=buf.append)
            if not proof["archive_integrity_verified"]:
                raise ValueError("AES file authentication failed on second pass")
            digest_parts.append(proof["canonical_rows_sha256"])
            for row in buf:
                yield row
    return produce(), digest_parts


def _read_neon_2022_frozen_panel():
    # No credentials printed or stored in report. Session explicitly READ ONLY.
    import psycopg
    uri = os.environ.get("DATABASE_URL", "")
    if not uri.startswith(("postgres://", "postgresql://")):
        raise ValueError("DATABASE_URL must be locally configured, never printed")
    with psycopg.connect(
        uri, connect_timeout=15,
        options="-c default_transaction_read_only=on -c statement_timeout=90000",
    ) as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute(SQL_NEON_DAYS)
            days = [r[0] for r in cur.fetchall()]
            cur.execute(SQL_NEON_PANEL, (list(FROZEN_STOCKS),))
            columns = [c.name for c in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
            if len(rows) > MAX_NEON_STOCK_ROWS:
                raise ValueError("Neon frozen research panel unexpectedly large")
        conn.rollback()
    return days, rows


def main():
    parser = argparse.ArgumentParser(
        description="Owner-local 2022 AES and existing Neon read-only 240-source bridge")
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--key-vault", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    a = parser.parse_args()
    archive_dir = a.archive_dir.expanduser().resolve()
    report_path = a.out.expanduser().resolve()
    if (not archive_dir.is_dir() or not report_path.parent.is_dir()
            or report_path.exists()
            or any((p / ".git").exists() for p in archive_dir.parents)
            or any((p / ".git").exists() for p in report_path.parents)):
        raise ValueError("Private archive/output outside Git checkout, no overwrite")
    sources = sorted(archive_dir.glob("*.twseenc"))
    hex_key = resolve_archive_key(
        vault_path=a.key_vault, env_key=os.environ.get("STOCK_ARCHIVE_KEY_HEX", ""))
    local_proof = audit_aes(sources, hex_key=hex_key, spotchecks=0)
    local_rows, second_hashes = _authenticated_rows(
        sources, hex_key=hex_key,
        expected_bundle_digest=local_proof["authenticated_file_digest_bundle_sha256"])
    neon_days, neon_panel = _read_neon_2022_frozen_panel()
    result = reconcile(local_rows, neon_panel, neon_days, local_audit=local_proof)
    bundle_sha = sha256(json.dumps(
        second_hashes, separators=(",", ":")).encode()).hexdigest()
    if bundle_sha != local_proof["authenticated_file_digest_bundle_sha256"]:
        raise ValueError("Authenticated local AES archive bundle changed mid-audit")
    result["other_year_archives_authenticated_excluded"] = (
        local_proof["other_year_archives_authenticated_and_excluded"])
    # Only aggregated metadata; no individual prices, private paths or secrets.
    with report_path.open("x", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")
    print(json.dumps({
        "status": "AES_NEON_READONLY_240_PANEL_AUDIT_PASS",
        "local_days": result["local_2022_source_sessions"],
        "neon_days": result["neon_source_sessions"],
        "overlap_days": result["overlapping_source_sessions"],
        "combined_days": result["unique_observed_2022_source_sessions"],
        "frozen_20_stock_sma240":
            result["frozen_stocks_with_complete_last_240_source_sessions"],
        "neon_writes": 0, "line_messages_sent": 0,
        "model_release": "BLOCKED",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
