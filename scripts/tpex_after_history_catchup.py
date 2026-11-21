"""One-time no-price-write TPEx indicator + missing composite catch-up.

This is *research data coverage only*: no trading or LINE sends. The source
must already have a genuine 60-session price cohort. The market's raw price
row count is frozen throughout; storage is capped below the free branch limit.
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
from batch_indicator_catchup import run as indicator_run
from composite_score import calculate_all

MAX_ROUNDS = 45
MAX_SCORE_BATCHES = 100
SCORE_BATCH_SIZE = 10
MAX_DATABASE_BYTES = 800_000_000

STATE_SQL = """
WITH priced AS (
 SELECT stock_id, COUNT(*) FILTER (WHERE close>0 AND volume>=0)::int AS valid_days,
        MAX(trade_date) FILTER (WHERE close>0 AND volume>=0) AS latest_valid
 FROM public.daily_prices
 WHERE market='tpex' AND stock_id<>'1808'
 GROUP BY stock_id
), latest AS (
 SELECT MAX(trade_date) AS max_day FROM public.daily_prices WHERE close>0
), eligible AS (
 SELECT p.stock_id,p.latest_valid FROM priced p,latest l
 WHERE p.valid_days>=60 AND p.latest_valid>=l.max_day-INTERVAL '7 days'
), coverage AS (
 SELECT e.stock_id,e.latest_valid,
 EXISTS(SELECT 1 FROM public.daily_technicals t WHERE t.market='tpex'
   AND t.stock_id=e.stock_id AND t.trade_date=e.latest_valid) AS tech,
 EXISTS(SELECT 1 FROM public.daily_smc s WHERE s.market='tpex'
   AND s.stock_id=e.stock_id AND s.trade_date=e.latest_valid) AS smc,
 EXISTS(SELECT 1 FROM public.daily_composite_scores c WHERE c.market='tpex'
   AND c.stock_id=e.stock_id AND c.as_of_date=e.latest_valid
   AND c.total_score IS NOT NULL) AS scored
 FROM eligible e
)
SELECT (SELECT count(*)::bigint FROM public.daily_prices) AS raw_price_rows,
       (SELECT pg_database_size(current_database())::bigint) AS database_bytes,
       (SELECT count(DISTINCT trade_date)::int FROM public.daily_prices
        WHERE market='tpex' AND source='TPEX_DATED_OTC_EW') AS source_days,
       count(*)::int AS eligible,
       count(*) FILTER(WHERE tech AND smc)::int AS indicators,
       count(*) FILTER(WHERE tech AND smc AND scored)::int AS matched
FROM coverage
"""

MISSING_SCORE_SQL = """
WITH priced AS (
 SELECT stock_id, COUNT(*) FILTER (WHERE close>0 AND volume>=0)::int AS valid_days,
        MAX(trade_date) FILTER (WHERE close>0 AND volume>=0) AS latest_valid
 FROM public.daily_prices WHERE market='tpex' AND stock_id<>'1808'
 GROUP BY stock_id
), latest AS (
 SELECT max(trade_date) max_day FROM public.daily_prices WHERE close>0
)
SELECT 'tpex' AS market,p.stock_id
FROM priced p,latest l
WHERE p.valid_days>=60 AND p.latest_valid>=l.max_day-INTERVAL '7 days'
AND EXISTS(SELECT 1 FROM public.daily_technicals t WHERE t.market='tpex'
  AND t.stock_id=p.stock_id AND t.trade_date=p.latest_valid)
AND EXISTS(SELECT 1 FROM public.daily_smc s WHERE s.market='tpex'
  AND s.stock_id=p.stock_id AND s.trade_date=p.latest_valid)
AND NOT EXISTS(SELECT 1 FROM public.daily_composite_scores c WHERE c.market='tpex'
  AND c.stock_id=p.stock_id AND c.as_of_date=p.latest_valid
  AND c.total_score IS NOT NULL)
ORDER BY p.stock_id LIMIT %s
"""


def capture(url):
    if not url:
        raise ValueError("Protected DATABASE_URL required")
    with psycopg.connect(url, connect_timeout=15, row_factory=dict_row) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        row = conn.execute(STATE_SQL).fetchone()
    state = dict(row)
    for key in ("raw_price_rows", "database_bytes", "source_days",
                "eligible", "indicators", "matched"):
        if type(state.get(key)) is not int or state[key] < 0:
            raise RuntimeError("Invalid database coverage measurement")
    if state["database_bytes"] >= MAX_DATABASE_BYTES:
        raise RuntimeError("Near free database size limit; stop writes")
    if not state["matched"] <= state["indicators"] <= state["eligible"]:
        raise RuntimeError("Impossible TPEx matched indicator cohort")
    return state


def missing_scores(url):
    with psycopg.connect(url, connect_timeout=15, row_factory=dict_row) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        rows = conn.execute(MISSING_SCORE_SQL, (SCORE_BATCH_SIZE,)).fetchall()
        return [(r["market"], r["stock_id"]) for r in rows]


def save(path, report):
    if not path:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


def assert_safe(before, after):
    if before["raw_price_rows"] != after["raw_price_rows"]:
        raise RuntimeError("Raw market history changed during indicator campaign")
    if before["eligible"] != after["eligible"]:
        raise RuntimeError("Eligible source cohort changed during indicator campaign")
    if after["indicators"] < before["indicators"] or after["matched"] < before["matched"]:
        raise RuntimeError("Same-date TPEx analysis coverage regressed")


def execute(url, *, apply=False, max_rounds=MAX_ROUNDS, report_path=None):
    if type(max_rounds) is not int or not 0 <= max_rounds <= MAX_ROUNDS:
        raise ValueError("Unsafe indicator campaign round count")
    if apply and (
        max_rounds == 0 or
        os.environ.get("STOCK_TPEX_INDICATOR_CAMPAIGN_WRITE_ENABLED") != "yes" or
        os.environ.get("STOCK_INDICATOR_CATCHUP_WRITE_ENABLED") != "yes"
    ):
        raise ValueError("Two explicit production research write gates required")
    before = capture(url)
    report = {
        "scope": "TPEX_CURRENT_VERIFIED_60_SESSION_RESEARCH_ONLY",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "baseline": before, "latest": before, "rounds": [],
        "score_batches": [], "raw_prices_modified": False,
        "line_messages_sent": False, "trading_enabled": False,
        "paid_upgrade_requested": False, "completed": False,
    }
    save(report_path, report)
    if not apply:
        return report
    if before["source_days"] < 50 or before["eligible"] < 100:
        raise RuntimeError("Insufficient source-verified TPEx history for bulk catch-up")

    current = before
    for i in range(max_rounds):
        if current["indicators"] == current["eligible"]:
            break
        items = indicator_run(url, apply=True, per_market=20, markets=("tpex",))
        verified = sum(x["status"] == "verified" for x in items)
        failed = sum(x["status"] == "failed" for x in items)
        after = capture(url)
        assert_safe(current, after)
        report["rounds"].append({
            "round": i + 1, "selected": len(items), "verified": verified,
            "failed": failed, "indicators": after["indicators"]
        })
        report["latest"] = after
        save(report_path, report)
        if failed or not verified or after["indicators"] <= current["indicators"]:
            raise RuntimeError("TPEx bounded indicator round failed or made no progress")
        current = after
    if current["indicators"] != current["eligible"]:
        raise RuntimeError("TPEx indicator round ceiling reached before full eligible cohort")

    for i in range(MAX_SCORE_BATCHES):
        cohort = missing_scores(url)
        if not cohort:
            break
        processed = calculate_all(url, stocks=cohort, missing_only=True)
        after = capture(url)
        assert_safe(current, after)
        report["score_batches"].append({
            "batch": i + 1, "requested": len(cohort),
            "inserted": processed, "matched": after["matched"],
        })
        report["latest"] = after
        save(report_path, report)
        if processed <= 0 or after["matched"] <= current["matched"]:
            raise RuntimeError("TPEx missing-only score batch made no progress")
        current = after
    report["completed"] = (
        current["eligible"] >= 100 and
        current["indicators"] == current["eligible"] and
        current["matched"] == current["eligible"]
    )
    save(report_path, report)
    if not report["completed"]:
        raise RuntimeError("Not all currently eligible TPEx stocks verified and scored")
    return report


def main():
    parser = argparse.ArgumentParser(description="Protected one-time TPEx research catch-up")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-rounds", type=int, default=MAX_ROUNDS)
    parser.add_argument("--report", type=Path, default=Path("tpex-history-followon.json"))
    args = parser.parse_args()
    result = execute(os.getenv("DATABASE_URL", ""), apply=args.apply,
                     max_rounds=args.max_rounds, report_path=args.report)
    print(json.dumps({
        "scope": result["scope"],
        "latest": result["latest"],
        "completed": result["completed"],
        "trading_enabled": False,
        "line_messages_sent": False
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
