"""Scheduled, read-only indicator catch-up preflight.

Proves that GitHub Actions can connect to the *real* Neon database and
identify the exact next (bounded) TWSE/TPEx indicator catch-up candidates.
No adjustments, indicator calculations, SQL writes, LINE messages or orders.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from batch_indicator_catchup import MAX_PER_MARKET, MIN_VERIFIED_PRICE_DAYS, select_candidates
from stock_db_audit import collect_audit


def build_probe(conn, *, captured_at=None):
    """Read all counts and selected candidates in one stable transaction."""
    conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
    audit = collect_audit(conn)
    market_date = audit["latest"]["latest_price_date"]
    if not market_date:
        raise ValueError("No valid market price date")
    records = audit.get("indicator_backlog")
    if not isinstance(records, list) or not records:
        raise ValueError("No current backlog evidence")
    by_market = {}
    for record in records:
        market = record["market"]
        if market not in ("twse", "tpex") or market in by_market:
            raise ValueError("Invalid or duplicate backlog market")
        vals = {k: int(record[k]) for k in ("eligible", "pending", "complete", "unstarted")}
        if (any(v < 0 for v in vals.values())
                or vals["pending"] + vals["complete"] != vals["eligible"]
                or vals["unstarted"] > vals["pending"]):
            raise ValueError("Inconsistent indicator coverage data")
        by_market[market] = vals
    selected = []
    for market in ("twse", "tpex"):
        stats = by_market.get(market, {"eligible": 0, "pending": 0, "complete": 0, "unstarted": 0})
        candidates = select_candidates(conn, market, MAX_PER_MARKET)
        if len(candidates) != min(MAX_PER_MARKET, stats["pending"]):
            raise ValueError("Candidate/coverage mismatch in repeatable-read snapshot")
        codes = set()
        for item in candidates:
            if (item["market"] != market or item["stock_id"] == "1808"
                    or int(item["close_days"]) < MIN_VERIFIED_PRICE_DAYS
                    or (int(item["technical_rows"]) >= int(item["close_days"])
                        and int(item["smc_rows"]) >= int(item["close_days"])
                        and item.get("has_latest_technical") is True
                        and item.get("has_latest_smc") is True)
                    or item["stock_id"] in codes):
                raise ValueError("Candidate violates bounded catch-up contract")
            codes.add(item["stock_id"])
        selected.append({
            "market": market,
            "eligible": stats["eligible"],
            "pending": stats["pending"],
            "complete": stats["complete"],
            "unstarted": stats["unstarted"],
            "preview_candidate_count": len(candidates),
            "per_run_cap": MAX_PER_MARKET,
        })
    if captured_at is None:
        captured_at = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": 1,
        "observed_at_utc": captured_at,
        "latest_price_date": market_date,
        "latest_score_date": audit["latest"]["latest_score_date"],
        "markets": selected,
        "pending_total": sum(item["pending"] for item in selected),
        "eligible_total": sum(item["eligible"] for item in selected),
        "minimum_full_success_batches": max(
            ((item["pending"] + MAX_PER_MARKET - 1) // MAX_PER_MARKET for item in selected),
            default=0,
        ),
        "candidate_selection_tested_against_real_sql": True,
        "database_transaction_read_only": True,
        "indicator_writes_performed": False,
        "automatic_write_schedule_activated": False,
        "trading_signals_enabled": False,
        "line_webhook_changed": False,
    }


def summary(report):
    rows = [
        "### Indicator Catch-Up Schedule Probe (Read-Only)",
        f"- Latest verified price date: {report['latest_price_date']}",
        f"- Latest score date: {report['latest_score_date']}",
        f"- Fresh 60-session backlog: {report['pending_total']:,}/{report['eligible_total']:,}",
    ]
    for item in report["markets"]:
        rows.append(
            f"- {item['market']}: pending {item['pending']:,}, complete {item['complete']:,}, "
            f"unstarted {item['unstarted']:,}, next-batch candidates {item['preview_candidate_count']}"
        )
    rows.extend([
        f"- Mathematical minimum at {MAX_PER_MARKET}/market/run: "
        f"{report['minimum_full_success_batches']} successful runs (not a calendar forecast)",
        "- All SQL executed in a REPEATABLE READ, READ ONLY transaction.",
        "- NO indicator writes, new write schedule, LINE messages, or trading instructions.",
        "- This is evidence of preview/readiness, NOT evidence that the real catch-up ran.",
    ])
    return "\n".join(rows) + "\n"


def run(database_url):
    if not database_url:
        raise ValueError("DATABASE_URL is required")
    with psycopg.connect(database_url, connect_timeout=20, row_factory=dict_row) as conn:
        with conn.transaction():
            return build_probe(conn)


def main():
    parser = argparse.ArgumentParser(description="Read-only indicator backlog and candidate schedule preflight")
    parser.add_argument("--output", type=Path, default=Path("indicator-schedule-probe.json"))
    args = parser.parse_args()
    result = run(os.environ.get("DATABASE_URL", ""))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(summary(result))
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(summary(result))


if __name__ == "__main__":
    main()
