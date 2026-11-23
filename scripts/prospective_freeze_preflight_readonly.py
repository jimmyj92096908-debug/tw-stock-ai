"""Fail-closed, SMALL read-only gate before costly prospective cohort SQL.

This preflight intentionally does NOT freeze a roster and cannot write Neon.
It only allows an existing, separately authorized freeze workflow to proceed
when Free-tier storage AND authenticated Neon transfer headroom are safe,
official market close and composite score head dates match, and timing is
actually prospective. On a mismatch/timeout/missing meter, return a recorded
ABSTAIN instead of executing a 30-second roster query on a near-full DB.

A workflow marked "success" after ABSTAIN means the *guard worked*; it does
NOT mean a cohort was frozen or that the AI model is ready.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from scripts.neon_free_meter_guard import (
    DB_WARN_BYTES, DB_STOP_BYTES, TRANSFER_PAUSE_BYTES,
    assess, fetch_meter,
)
from src.research_forward_freeze import eligible_freeze_time

SIZE_SQL = "SELECT pg_database_size(current_database())::bigint AS bytes"
HEAD_SQL = """
SELECT
  (SELECT MAX(trade_date) FROM public.daily_prices WHERE close>0) AS market_day,
  (SELECT MAX(as_of_date) FROM public.daily_composite_scores
    WHERE total_score IS NOT NULL) AS score_day,
  clock_timestamp() AS captured_at
"""
MAX_SQL_MS = 8000
STATUSES = frozenset({
    "READY_FOR_EXISTING_AUTHORIZED_FREEZE",
    "ABSTAIN_STORAGE_WARN",
    "ABSTAIN_NO_VERIFIED_NEON_TRANSFER",
    "ABSTAIN_NEON_TRANSFER_PAUSED",
    "ABSTAIN_MARKET_SCORE_DAY_MISMATCH",
    "ABSTAIN_MISSING_REAL_MARKET_OR_SCORE_DAY",
    "ABSTAIN_OUTSIDE_PROSPECTIVE_TIME",
    "ABSTAIN_READONLY_PREFLIGHT_UNAVAILABLE",
})


def verdict(*, db_bytes, market_day=None, score_day=None,
            captured_at=None, transfer_usage=None):
    """Pure fail-closed research gate; never returns an approval to trade."""
    if type(db_bytes) is not int or db_bytes < 1:
        raise ValueError("Verified positive database size required")
    reason = "ABSTAIN_STORAGE_WARN" if db_bytes >= DB_WARN_BYTES else None
    meter = None
    if reason is None:
        if transfer_usage is None:
            reason = "ABSTAIN_NO_VERIFIED_NEON_TRANSFER"
        else:
            # The API must provide a project-ID-matching verified usage record.
            meter = assess(db_bytes=db_bytes, usage=transfer_usage)
            if meter["network_transfer_status"] == "PAUSE_NEW_NONESSENTIAL_WORK":
                reason = "ABSTAIN_NEON_TRANSFER_PAUSED"
    if reason is None:
        if (not isinstance(market_day, date) or
                isinstance(market_day, datetime) or
                not isinstance(score_day, date) or
                isinstance(score_day, datetime)):
            reason = "ABSTAIN_MISSING_REAL_MARKET_OR_SCORE_DAY"
        elif market_day != score_day:
            reason = "ABSTAIN_MARKET_SCORE_DAY_MISMATCH"
        else:
            try:
                eligible_freeze_time(score_day, as_of=captured_at)
            except (ValueError, TypeError):
                reason = "ABSTAIN_OUTSIDE_PROSPECTIVE_TIME"
    status = reason or "READY_FOR_EXISTING_AUTHORIZED_FREEZE"
    return {
        "schema_version": 1,
        "scope": "PROSPECTIVE_RESEARCH_FREE_READONLY_PREFLIGHT",
        "status": status,
        "safe_to_attempt_existing_authorized_freeze": reason is None,
        "conservative_storage_warning_bytes": DB_WARN_BYTES,
        "hard_storage_stop_bytes": DB_STOP_BYTES,
        "measured_database_bytes": db_bytes,
        "project_network_transfer_verified": meter is not None,
        "paid_services_authorized": False,
        "neon_database_writes": 0,
        "LINE_messages_sent": 0,
        "live_trading_approved": False,
        "holdout_alpha_proven": False,
        "model_release": "BLOCKED",
    }


def run(*, database_url, neon_api_key="", report_path=None,
        github_output_path=None):
    # Every connection uses server-enforced read-only mode before any SELECT.
    # Even when written model records already exist, this script cannot DML.
    result = None
    try:
        if not database_url:
            raise ValueError("Missing protected DB configuration")
        with psycopg.connect(
                database_url, connect_timeout=10, row_factory=dict_row,
                options="-c default_transaction_read_only=on") as conn:
            with conn.transaction():
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                    cursor.execute("SET LOCAL statement_timeout = '8000ms'")
                    cursor.execute(SIZE_SQL)
                    size = cursor.fetchone()["bytes"]
                    if type(size) is not int or size < 1:
                        raise ValueError("Unverified size")
                    if size >= DB_WARN_BYTES:
                        result = verdict(db_bytes=size)
                    else:
                        cursor.execute(HEAD_SQL)
                        head = cursor.fetchone()
                        usage = fetch_meter(neon_api_key) if neon_api_key else None
                        result = verdict(
                            db_bytes=size,
                            market_day=head["market_day"],
                            score_day=head["score_day"],
                            captured_at=head["captured_at"],
                            transfer_usage=usage,
                        )
    except Exception:
        # Never expose PostgreSQL/network exception text: it might include a
        # source URL, sensitive Neon hostname, or future private metadata.
        result = {
            "schema_version": 1,
            "scope": "PROSPECTIVE_RESEARCH_FREE_READONLY_PREFLIGHT",
            "status": "ABSTAIN_READONLY_PREFLIGHT_UNAVAILABLE",
            "safe_to_attempt_existing_authorized_freeze": False,
            "conservative_storage_warning_bytes": DB_WARN_BYTES,
            "hard_storage_stop_bytes": DB_STOP_BYTES,
            "measured_database_bytes": None,
            "project_network_transfer_verified": False,
            "paid_services_authorized": False,
            "neon_database_writes": 0,
            "LINE_messages_sent": 0,
            "live_trading_approved": False,
            "holdout_alpha_proven": False,
            "model_release": "BLOCKED",
        }
    if result["status"] not in STATUSES:
        raise AssertionError("Unrecognized read-only preflight classification")
    if report_path is not None:
        Path(report_path).write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if github_output_path is not None:
        with Path(github_output_path).open("a", encoding="utf-8") as f:
            f.write("safe_to_freeze=" + (
                "true" if result["safe_to_attempt_existing_authorized_freeze"]
                else "false") + "\n")
            f.write("freeze_preflight_status=" + result["status"] + "\n")
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--report", default="prospective-freeze-preflight.json")
    p.add_argument("--github-output", default=None)
    opts=p.parse_args()
    result=run(
        database_url=os.getenv("DATABASE_URL",""),
        neon_api_key=os.getenv("NEON_API_KEY",""),
        report_path=opts.report,
        github_output_path=opts.github_output,
    )
    print(json.dumps({
        "status":result["status"],
        "safe_to_freeze":result["safe_to_attempt_existing_authorized_freeze"],
        "database_writes":0,
        "model_release":"BLOCKED",
    }))


if __name__=="__main__":
    main()
