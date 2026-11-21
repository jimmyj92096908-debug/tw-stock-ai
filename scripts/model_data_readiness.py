"""Read-only readiness audit for the Taiwan stock research model.

Usage:
    python scripts/model_data_readiness.py --offline
    DATABASE_URL=... python scripts/model_data_readiness.py --live-readonly

Neither mode writes to Neon, changes model artifacts, or sends LINE messages.
This is a diagnostic report, not an authorization to publish trade signals.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
EVALUATION = ROOT / "models" / "tw-factor-ridge-1-evaluation.json"
sys.path.insert(0, str(ROOT / "src"))
from current_official_listing import CURRENT_OFFICIAL_LISTED_CTE

# Five years of *calendar* history; this count deliberately does not
# assert all stocks have been listed for the full period.
HISTORY_SQL = CURRENT_OFFICIAL_LISTED_CTE + """
, eligible AS (
    SELECT m.market, m.stock_id
    FROM official_current_listed m
    WHERE m.market IN ('twse', 'tpex')
      AND NOT EXISTS (
        SELECT 1 FROM model_stock_exclusions x
        WHERE x.market = m.market AND x.stock_id = m.stock_id
      )
), p AS (
    SELECT e.market, e.stock_id,
           COUNT(d.trade_date) AS five_year_daily_rows,
           MIN(d.trade_date) AS first_date,
           MAX(d.trade_date) AS last_date
    FROM eligible e
    LEFT JOIN daily_prices d ON d.market=e.market AND d.stock_id=e.stock_id
      AND d.trade_date >= %(cutoff)s AND d.trade_date <= %(as_of)s
    GROUP BY e.market, e.stock_id
), t AS (
    SELECT DISTINCT d.market, d.stock_id
    FROM daily_technicals d
    WHERE d.trade_date >= %(cutoff)s AND d.trade_date <= %(as_of)s
)
SELECT p.market, COUNT(*)::int AS eligible_stocks,
       COUNT(*) FILTER (WHERE five_year_daily_rows >= 1000)::int AS stocks_1000_days,
       COUNT(*) FILTER (WHERE five_year_daily_rows >= 750)::int AS stocks_750_days,
       COUNT(*) FILTER (WHERE five_year_daily_rows < 250)::int AS stocks_under_250_days,
       COUNT(*) FILTER (WHERE t.stock_id IS NOT NULL)::int AS stocks_with_any_technicals,
       ROUND(AVG(five_year_daily_rows),1) AS average_days
FROM p
LEFT JOIN t ON t.market=p.market AND t.stock_id=p.stock_id
GROUP BY p.market ORDER BY p.market
"""


def historical_cutoff(as_of: date) -> date:
    try:
        return as_of.replace(year=as_of.year - 5)
    except ValueError:  # February 29
        return as_of.replace(year=as_of.year - 5, day=28)


def release_reasons(evaluation: dict) -> list[str]:
    """Fail closed on insufficient or contaminated out-of-sample evidence."""
    holdout = evaluation.get("holdout") or {}
    reasons = []
    if evaluation.get("holdout_research_gate_passed") is not True:
        reasons.append("saved_holdout_failed")
    if holdout.get("model_mean_net_excess") is None or holdout["model_mean_net_excess"] <= 0:
        reasons.append("non_positive_net_excess")
    if evaluation.get("holdout_is_pristine_independent_validation") is not True:
        reasons.append("holdout_not_independent")
    if evaluation.get("requires_new_unseen_future_holdout") is not False:
        reasons.append("new_unseen_future_holdout_required")
    return reasons


def build_report(evaluation: dict, as_of: date, coverage: list[dict] | None = None) -> dict:
    reasons = release_reasons(evaluation)
    data = {
        "as_of": as_of.isoformat(),
        "five_year_cutoff": historical_cutoff(as_of).isoformat(),
        "model_version": evaluation.get("model_version"),
        "saved_holdout_mean_net_excess": (evaluation.get("holdout") or {}).get("model_mean_net_excess"),
        "model_gate": "BLOCKED" if reasons else "REQUIRES_INDEPENDENT_REVIEW",
        "blocking_reasons": reasons,
        "coverage": coverage,
        "coverage_is_full_five_year_proof": False,
        "current_listing_status_independently_verified": coverage is not None,
        "live_trading_approved": False,
        "line_signal_delivery_approved": False,
        "database_writes": False,
    }
    return data


def read_live_coverage(database_url: str, as_of: date) -> list[dict]:
    if not database_url:
        raise ValueError("DATABASE_URL required for live read-only mode")
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(
        database_url,
        row_factory=dict_row,
        connect_timeout=15,
        options="-c default_transaction_read_only=on",
    ) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                cur.execute("SET LOCAL statement_timeout = '30000ms'")
                cur.execute(HISTORY_SQL, {"cutoff": historical_cutoff(as_of), "as_of": as_of})
                rows = [{k: (float(v) if k == "average_days" and v is not None else v)
                         for k, v in row.items()} for row in cur.fetchall()]
                # The official listing receipt is required. A stale or missing
                # receipt produces no rows and cannot pass this audit.
                if not rows or sum(r["eligible_stocks"] for r in rows) == 0:
                    raise RuntimeError("Missing or stale official current listing receipt")
                return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--offline", action="store_true")
    group.add_argument("--live-readonly", action="store_true")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    evaluation = json.loads(EVALUATION.read_text(encoding="utf-8"))
    coverage = read_live_coverage(os.getenv("DATABASE_URL", ""), args.as_of) if args.live_readonly else None
    report = build_report(evaluation, args.as_of, coverage)
    payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
