"""Conservative, read-only Neon Free TWSE history runway evidence.

Observe physical PostgreSQL growth over a *completed* official source batch;
never claim guaranteed future capacity or buy a plan. The observed growth can
contain other concurrent writes and is NOT a pricing/storage bill estimate.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path

MAX_DATABASE_BYTES = 800_000_000
MIN_MAINTENANCE_RESERVE_BYTES = 50_000_000
STRESS_BYTES_PER_NEW_BAR = 600
MAX_OFFICIAL_BARS_PER_DAY = 1500
MAX_DAYS_PER_ROUND = 8


def audit(evidence: dict, *, missing_weekdays: int | None = None) -> dict:
    if not isinstance(evidence, dict):
        raise ValueError("Official history source receipt object required")
    before, after, batches = (evidence.get("baseline"),
                              evidence.get("latest"), evidence.get("batches"))
    if not isinstance(before, dict) or not isinstance(after, dict) or not isinstance(batches, list):
        raise ValueError("Complete source before/after and batch receipt required")
    for section in (before, after):
        for field in ("database_bytes", "source_days"):
            if type(section.get(field)) is not int or section[field] < 0:
                raise ValueError("Unverifiable physical size or source days")
    if missing_weekdays is not None and (type(missing_weekdays) is not int or missing_weekdays < 0):
        raise ValueError("Actual outstanding weekdays count required")
    if after["source_days"] < before["source_days"]:
        raise ValueError("Official source sessions regressed")
    if any(not isinstance(item, dict) or type(item.get("new_valid_bars")) is not int
           or item["new_valid_bars"] < 0 for item in batches):
        raise ValueError("Unverified inserted-bar accounting")
    growth = after["database_bytes"] - before["database_bytes"]
    new_sessions = after["source_days"] - before["source_days"]
    actual_new_bars = sum(item["new_valid_bars"] for item in batches)
    # PostgreSQL physical size can shrink or grow due to VACUUM, concurrent
    # workloads and index page splits. If evidence is not positive, fail
    # closed on extrapolation rather than substituting an invented bar size.
    rate = growth / new_sessions if growth > 0 and new_sessions > 0 else None
    # This is the existing campaign's per-round 8-day reserve, not quota.
    protected_ceiling = MAX_DATABASE_BYTES - (
        MIN_MAINTENANCE_RESERVE_BYTES +
        MAX_DAYS_PER_ROUND * MAX_OFFICIAL_BARS_PER_DAY *
        STRESS_BYTES_PER_NEW_BAR
    )
    room = max(0, protected_ceiling - after["database_bytes"])
    projected = math.floor(room / rate) if rate is not None else None
    # A final single-day batch can use a little more of the *existing*
    # safety budget than an eight-day batch, without reducing the reserve.
    # The strict import-side capacity check still takes precedence.
    one_day_ceiling = MAX_DATABASE_BYTES - (
        MIN_MAINTENANCE_RESERVE_BYTES +
        MAX_OFFICIAL_BARS_PER_DAY * STRESS_BYTES_PER_NEW_BAR
    )
    adaptive_room = max(0, one_day_ceiling - after["database_bytes"])
    adaptive_projected = (
        math.floor(adaptive_room / rate) if rate is not None else None
    )
    return {
        "schema_version": 1,
        "scope": "TWSE_FREE_STORAGE_SOURCE_RUNWAY_OBSERVATION_ONLY",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "baseline_bytes": before["database_bytes"],
        "after_bytes": after["database_bytes"],
        "measured_physical_growth_bytes": growth,
        "new_verified_official_source_days": new_sessions,
        "new_valid_bars_reconciled_by_campaign": actual_new_bars,
        "estimated_bytes_per_new_verified_day": round(rate, 1) if rate is not None else None,
        "existing_protected_campaign_start_ceiling_bytes": protected_ceiling,
        "protected_remaining_bytes": room,
        "adaptive_one_day_capacity_ceiling_bytes": one_day_ceiling,
        "adaptive_remaining_bytes": adaptive_room,
        "illustrative_adaptive_additional_verified_source_days": adaptive_projected,
        "preserved_neon_maintenance_margin_bytes": MIN_MAINTENANCE_RESERVE_BYTES,
        "outstanding_weekdays_not_equivalent_to_official_sessions": missing_weekdays,
        "illustrative_additional_verified_source_days": projected,
        "illustrative_runway_short_of_outstanding_weekdays": (
            projected < missing_weekdays
            if projected is not None and missing_weekdays is not None else None),
        "five_year_storage_feasibility_proven": False,
        "projection_is_not_a_guarantee": True,
        "historical_source_data_modified": False,
        "derived_data_written": False,
        "line_messages_sent": False,
        "live_trading_approved": False,
        "paid_upgrade_requested": False,
    }


def main():
    parser = argparse.ArgumentParser(description="Conservative physical free-space runway, no writes")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--live-readonly", action="store_true")
    parser.add_argument("--missing-weekdays", type=int)
    args = parser.parse_args()
    remaining = args.missing_weekdays
    if args.live_readonly:
        if remaining is not None:
            parser.error("Choose either an observed count or a live read-only audit")
        import os
        from scripts.twse_five_year_source_gate import snapshot
        remaining = snapshot(os.environ.get("DATABASE_URL", ""))["missing_weekdays"]
    result = audit(json.loads(args.evidence.read_text(encoding="utf-8")),
                   missing_weekdays=remaining)
    serialized = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized)


if __name__ == "__main__":
    main()
