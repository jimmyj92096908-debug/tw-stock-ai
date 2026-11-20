"""Read-only verification of the first two newly backfilled stock scores.

The approved composite-score command is a separate writer. This checker ONLY
reads price, indicator, SMC and score rows and refuses stale/partial scores.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

TARGETS = (("twse", "1626"), ("twse", "1702"))
QUERY = """
WITH latest AS (SELECT max(trade_date) AS trade_date
                  FROM public.daily_prices WHERE close>0),
targets(market,stock_id) AS (VALUES ('twse','1626'),('twse','1702'))
SELECT x.market,x.stock_id,l.trade_date,
       p.close AS raw_close,
       t.ma5,t.ma20,t.ma60,
       s.trend_direction,
       sc.total_score,sc.coverage_weight,sc.as_of_date AS score_date
FROM targets x CROSS JOIN latest l
LEFT JOIN public.daily_prices p
 ON p.market=x.market AND p.stock_id=x.stock_id AND p.trade_date=l.trade_date
LEFT JOIN public.daily_technicals t
 ON t.market=x.market AND t.stock_id=x.stock_id AND t.trade_date=l.trade_date
LEFT JOIN public.daily_smc s
 ON s.market=x.market AND s.stock_id=x.stock_id AND s.trade_date=l.trade_date
LEFT JOIN public.daily_composite_scores sc
 ON sc.market=x.market AND sc.stock_id=x.stock_id AND sc.as_of_date=l.trade_date
ORDER BY x.market,x.stock_id
"""


def snapshot(rows, *, phase):
    if phase not in ("before", "after"):
        raise ValueError("Invalid verification phase")
    if len(rows) != len(TARGETS):
        raise ValueError("Missing or duplicate target stocks")
    results = []
    seen = set()
    days = set()
    for row in rows:
        key = (row["market"], str(row["stock_id"]))
        if key not in TARGETS or key in seen:
            raise ValueError("Unexpected or duplicate target")
        seen.add(key)
        date = row["trade_date"]
        if not date or not row["raw_close"] or float(row["raw_close"]) <= 0:
            raise ValueError("Missing current same-day price")
        days.add(str(date)[:10])
        if any(row[name] is None for name in ("ma5", "ma20", "ma60", "trend_direction")):
            raise ValueError("Indicators incomplete for latest price session")
        score = row["total_score"]
        coverage = row["coverage_weight"]
        valid_score = (
            score is not None and coverage is not None
            and 0 <= float(score) <= 100
            and 0.5 <= float(coverage) <= 1
            and str(row["score_date"])[:10] == str(date)[:10]
        )
        results.append({
            "market": key[0], "stock_id": key[1],
            "valid_same_day_score": valid_score,
            "total_score": round(float(score), 2) if valid_score else None,
            "coverage_weight": round(float(coverage), 2) if valid_score else None,
        })
    if len(days) != 1 or seen != set(TARGETS):
        raise ValueError("Score verification mixed trading dates or missing symbols")
    if phase == "after" and not all(x["valid_same_day_score"] for x in results):
        raise ValueError("Newly backfilled symbols lack valid same-day composite scores")
    return {
        "schema_version": 1,
        "phase": phase,
        "date": days.pop(),
        "symbols": results,
        "all_targets_scored": all(x["valid_same_day_score"] for x in results),
        "read_only": True,
        "line_messages_sent": False,
        "trade_signals_enabled": False,
    }


def fetch(database_url, *, phase):
    if not database_url:
        raise ValueError("DATABASE_URL missing")
    with psycopg.connect(database_url, connect_timeout=20, row_factory=dict_row) as conn:
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            with conn.cursor() as cur:
                cur.execute(QUERY)
                return snapshot([dict(row) for row in cur.fetchall()], phase=phase)


def compare(before, after):
    if not before.get("read_only") or not after.get("read_only"):
        raise ValueError("Read-only verification required")
    if before.get("phase") != "before" or after.get("phase") != "after":
        raise ValueError("Wrong verification evidence phases")
    if before.get("date") != after.get("date"):
        raise ValueError("Market date changed during score refresh")
    if before.get("schema_version") != 1 or after.get("schema_version") != 1:
        raise ValueError("Unexpected evidence schema")
    if not after.get("all_targets_scored"):
        raise ValueError("Final target scores missing")
    pre = {(x["market"],x["stock_id"]):x for x in before["symbols"]}
    post = {(x["market"],x["stock_id"]):x for x in after["symbols"]}
    if set(pre) != set(TARGETS) or set(post) != set(TARGETS):
        raise ValueError("Mismatched target symbols")
    new = sum(not pre[key]["valid_same_day_score"] and post[key]["valid_same_day_score"] for key in TARGETS)
    if new == 0:
        raise ValueError("No newly verified scores in the first indicator batch")
    return {"date": after["date"], "newly_scored_stocks": new, "targets": len(TARGETS),
            "verified": True, "research_only": True, "trading_approved": False}


def main():
    p = argparse.ArgumentParser(description="Verify two real indicator-to-composite research transitions")
    p.add_argument("--phase", choices=("before","after"), required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--before", type=Path)
    args = p.parse_args()
    current = fetch(os.environ.get("DATABASE_URL", ""), phase=args.phase)
    args.out.write_text(json.dumps(current, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"Read-only score verification {args.phase}: date {current['date']}, "
          f"scored {sum(x['valid_same_day_score'] for x in current['symbols'])}/{len(TARGETS)}")
    if args.phase == "after":
        if not args.before:
            raise ValueError("--before required for after phase")
        previous = json.loads(args.before.read_text(encoding="utf-8"))
        evidence = compare(previous, current)
        print(json.dumps(evidence, ensure_ascii=False))


if __name__ == "__main__":
    main()
