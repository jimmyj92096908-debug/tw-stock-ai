"""Bounded recalculation of TPEx legacy thousand-unit *derived* research data.

Never alters public.daily_prices. Defaults to preview. Apply requires explicit
production gates, a fixed 10-stock window, and an unchanged raw TPEx legacy
source fingerprint. Intended only AFTER earlier TPEx history/indicator jobs.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import sys

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from build_adjusted_prices import build as build_adjusted
from calculate_technicals import calculate_stock as build_technicals
from calculate_smc import calculate_stock as build_smc
from composite_score import calculate_all

MAX_TARGETS = 70
MAX_WINDOW = 10
MAX_DATABASE_BYTES = 800_000_000
MIN_DAYS = 1
MIN_SCORE_DAYS = 60

TARGET_SQL = """
WITH last_day AS (
 SELECT max(trade_date) latest FROM public.daily_prices WHERE close>0
), qualified AS (
 SELECT stock_id,
        count(*) FILTER(WHERE close>0 AND volume>=0)::int AS valid_days,
        max(trade_date) FILTER(WHERE close>0 AND volume>=0) AS last_price
 FROM public.daily_prices
 WHERE market='tpex' AND stock_id<>'1808'
 GROUP BY stock_id
)
SELECT q.stock_id,q.valid_days,q.last_price
FROM qualified q CROSS JOIN last_day d
WHERE q.valid_days>=%s
  AND q.last_price>=d.latest-interval '7 days'
  AND EXISTS (
   SELECT 1 FROM public.daily_prices p
   WHERE p.market='tpex' AND p.stock_id=q.stock_id
     AND p.source='TPEX_TRADING_STOCK'
  )
ORDER BY q.stock_id
LIMIT %s
"""

RAW_FINGERPRINT_SQL = """
SELECT count(*)::bigint AS rows,
  coalesce(sum(volume)::numeric,0) AS volume_sum,
  coalesce(sum(turnover),0) AS turnover_sum,
  (SELECT pg_database_size(current_database())::bigint) AS database_bytes
FROM public.daily_prices
WHERE market='tpex' AND source='TPEX_TRADING_STOCK'
"""

VERIFY_SQL = """
WITH legacy AS (
 SELECT p.trade_date, p.volume, p.turnover,
        a.volume AS adj_volume, a.turnover AS adj_turnover,
        a.share_adjustment_factor
 FROM public.daily_prices p
 LEFT JOIN public.daily_adjusted_prices a
   ON a.market=p.market AND a.stock_id=p.stock_id AND a.trade_date=p.trade_date
 WHERE p.market='tpex' AND p.stock_id=%s
   AND p.source='TPEX_TRADING_STOCK'
)
SELECT count(*)::int AS legacy_rows,
 count(*) FILTER (WHERE volume IS NOT NULL AND
     (adj_volume IS NULL OR share_adjustment_factor IS NULL OR
      abs(adj_volume - volume::numeric*1000*share_adjustment_factor) >
         greatest(1, abs(volume::numeric*1000*share_adjustment_factor)*0.00001)))::int
    AS bad_volume,
 count(*) FILTER (WHERE turnover IS NOT NULL AND
     (adj_turnover IS NULL OR abs(adj_turnover - turnover*1000)>0.02))::int
    AS bad_turnover
FROM legacy
"""

LATEST_CHECK_SQL = """
SELECT
  EXISTS(SELECT 1 FROM public.daily_adjusted_prices
    WHERE market='tpex' AND stock_id=%s AND trade_date=%s) AS adjusted,
  EXISTS(SELECT 1 FROM public.daily_technicals
    WHERE market='tpex' AND stock_id=%s AND trade_date=%s) AS technical,
  EXISTS(SELECT 1 FROM public.daily_smc
    WHERE market='tpex' AND stock_id=%s AND trade_date=%s) AS smc
"""

SCORE_CHECK_SQL = """
SELECT EXISTS(SELECT 1 FROM public.daily_composite_scores
 WHERE market='tpex' AND stock_id=%s AND as_of_date=%s
   AND total_score IS NOT NULL) AS scored
"""


def fingerprint(conn):
    with conn.cursor() as cur:
        cur.execute(RAW_FINGERPRINT_SQL)
        result = dict(cur.fetchone())
    if result["database_bytes"] >= MAX_DATABASE_BYTES:
        raise RuntimeError("Free storage guard reached before derived recalculation")
    if result["rows"] <= 0:
        raise RuntimeError("No source-provenanced legacy TPEx rows")
    return result


def choose_targets(conn):
    with conn.cursor() as cur:
        cur.execute(TARGET_SQL, (MIN_DAYS, MAX_TARGETS))
        found = [dict(x) for x in cur.fetchall()]
    if len(found) > MAX_TARGETS:
        raise RuntimeError("Unbounded legacy cohort")
    if len({x["stock_id"] for x in found}) != len(found):
        raise RuntimeError("Duplicate target stock")
    return found


def verify_derived(conn, stock):
    with conn.cursor() as cur:
        cur.execute(VERIFY_SQL, (stock["stock_id"],))
        result = dict(cur.fetchone())
        cur.execute(LATEST_CHECK_SQL, (
            stock["stock_id"], stock["last_price"],
            stock["stock_id"], stock["last_price"],
            stock["stock_id"], stock["last_price"],
        ))
        latest = dict(cur.fetchone())
    if (result["legacy_rows"] < 1 or result["bad_volume"] != 0 or
            result["bad_turnover"] != 0 or not all(latest.values())):
        raise RuntimeError("TPEx derived source unit / latest indicator mismatch")
    return {"legacy_rows": result["legacy_rows"],
            "bad_volume": 0, "bad_turnover": 0}


def save(path, report):
    if not path:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, default=str, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


def execute(url, *, apply=False, rescore=False, offset=0,
            limit=MAX_WINDOW, report_path=None):
    if not url:
        raise ValueError("Protected DATABASE_URL required")
    if type(offset) is not int or not 0 <= offset < MAX_TARGETS:
        raise ValueError("Unsafe source cohort offset")
    if type(limit) is not int or not 1 <= limit <= MAX_WINDOW:
        raise ValueError("Unsafe per-run source cohort size")
    if rescore and not apply:
        raise ValueError("Rescore requires explicit apply")
    if apply and (
        os.environ.get("STOCK_TPEX_LEGACY_DERIVED_REPAIR_ENABLED") != "yes" or
        os.environ.get("STOCK_INDICATOR_CATCHUP_WRITE_ENABLED") != "yes" or
        (rescore and os.environ.get("STOCK_TPEX_LEGACY_SCORE_RECALC_ENABLED") != "yes")
    ):
        raise ValueError("Missing explicit source-specific production write gates")

    report = {
        "scope": "TPEX_LEGACY_SOURCE_DERIVED_ONLY",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "apply": apply, "rescore": rescore,
        "offset": offset, "limit": limit, "stocks": [],
        "raw_prices_modified": False, "line_messages_sent": False,
        "trading_enabled": False,
    }
    with psycopg.connect(url, row_factory=dict_row, connect_timeout=20) as conn:
        baseline = fingerprint(conn)
        universe = choose_targets(conn)
        targets = universe[offset:offset + limit]
        conn.commit()
        report["eligible_legacy_stocks"] = len(universe)
        report["target_stock_count"] = len(targets)
        report["raw_fingerprint"] = {k: str(v) for k,v in baseline.items()
                                     if k != "database_bytes"}
        save(report_path, report)
        if not apply:
            report["stocks"] = [{"stock_id":x["stock_id"],"status":"dry-run"}
                                for x in targets]
            save(report_path, report)
            return report

        for stock in targets:
            sid = stock["stock_id"]
            with conn.transaction():
                n_adj = build_adjusted(conn, "tpex", sid)
                n_tech = build_technicals(conn, "tpex", sid)
                n_smc = build_smc(conn, "tpex", sid)
                if min(n_adj, n_tech, n_smc) < stock["valid_days"]:
                    raise RuntimeError("Incomplete TPEx derived recalculation")
                checks = verify_derived(conn, stock)
            conn.commit()
            score_processed = 0
            if rescore and stock["valid_days"] >= MIN_SCORE_DAYS:
                # Separate dedicated connection; only this verified explicit
                # stock may have its research-only score corrected.
                score_processed = calculate_all(url, stocks=[("tpex", sid)],
                                                missing_only=False)
                if score_processed != 1:
                    raise RuntimeError("Expected exactly one audited TPEx research score")
                with conn.cursor() as cur:
                    cur.execute(SCORE_CHECK_SQL, (sid, stock["last_price"]))
                    if not cur.fetchone()["scored"]:
                        raise RuntimeError("Corrected TPEx research score missing")
            after = fingerprint(conn)
            if any(after[k] != baseline[k] for k in
                   ("rows", "volume_sum", "turnover_sum")):
                raise RuntimeError("Legacy raw price fingerprint changed during repair")
            conn.commit()
            report["stocks"].append({
                "stock_id": sid, "status": "verified",
                "valid_days": stock["valid_days"],
                "legacy_rows_verified": checks["legacy_rows"],
                "derived_rows": n_adj, "technical_rows": n_tech,
                "smc_rows": n_smc, "scores_processed": score_processed,
                "research_score_eligible": stock["valid_days"] >= MIN_SCORE_DAYS,
            })
            save(report_path, report)
    return report


def main():
    parser = argparse.ArgumentParser(description="Bounded derived-only TPEx unit repair")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rescore", action="store_true")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=MAX_WINDOW)
    parser.add_argument("--report", type=Path, default=Path("tpex-legacy-derived-evidence.json"))
    args = parser.parse_args()
    result = execute(os.getenv("DATABASE_URL", ""), apply=args.apply,
                     rescore=args.rescore, offset=args.offset,
                     limit=args.limit, report_path=args.report)
    print(json.dumps({
        "scope":result["scope"], "apply":result["apply"],
        "eligible_legacy_stocks":result["eligible_legacy_stocks"],
        "verified":sum(x["status"]=="verified" for x in result["stocks"]),
        "raw_prices_modified":False,"trading_enabled":False,"line_messages_sent":False,
    },ensure_ascii=False))


if __name__ == "__main__":
    main()
