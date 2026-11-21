"""Reconcile historical TPEx factor/score freshness after dated-price backfills.

Source sessions being appended AFTER a latest-day MA/SMC/score calculation
invalidate earlier 60/120-day windows. Latest-row existence alone is NOT
a complete verification. Only after source history and legacy thousand-unit
corrections are verified, process <=20 stocks x <=5 bounded batches.

No writes to daily_prices, trading, LINE or paid services. Default read-only.
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
sys.path.insert(0, str(ROOT / "scripts"))

from build_adjusted_prices import build as build_adjusted
from calculate_technicals import calculate_stock as build_technicals
from calculate_smc import calculate_stock as build_smc
from composite_score import calculate_all
from twse_240_release_gate import snapshot as release_snapshot

MIN_OFFICIAL_SOURCE_DAYS = 80
MIN_RECENT_ELIGIBLE = 700
MAX_BATCH = 20
MAX_ROUNDS = 5
MAX_DATABASE_BYTES = 800_000_000

# Source date completeness and calculation ordering both matter. Historical
# prices may arrive later than a previously scored latest-close row.
# Aggregate MIN(calculated_at) ignores NULL timestamps, so the correlated
# per-raw-day EXISTS audit below must independently reject any NULL factor
# calculation timestamp, even when every derived row is present.
CANDIDATES_SQL = """
WITH latest_market AS (
 SELECT max(trade_date) latest_date FROM public.daily_prices WHERE close>0
), prices AS (
 SELECT stock_id,
   count(*)::int price_rows,
   count(*) FILTER(WHERE close>0 AND volume>=0)::int valid_days,
   max(trade_date) FILTER(WHERE close>0 AND volume>=0) last_valid,
   max(retrieved_at) FILTER(WHERE source='TPEX_DATED_OTC_EW') last_source_write
 FROM public.daily_prices
 WHERE market='tpex' AND stock_id<>'1808'
 GROUP BY stock_id
), analysis AS (
 SELECT p.*,
   (SELECT count(*)::int FROM public.daily_adjusted_prices a
    WHERE a.market='tpex' AND a.stock_id=p.stock_id) adjusted_rows,
   (SELECT count(*)::int FROM public.daily_technicals t
    WHERE t.market='tpex' AND t.stock_id=p.stock_id) technical_rows,
   (SELECT count(*)::int FROM public.daily_smc s
    WHERE s.market='tpex' AND s.stock_id=p.stock_id) smc_rows,
   (SELECT min(a.calculated_at) FROM public.daily_adjusted_prices a
    WHERE a.market='tpex' AND a.stock_id=p.stock_id) adjusted_at,
   (SELECT min(t.calculated_at) FROM public.daily_technicals t
    WHERE t.market='tpex' AND t.stock_id=p.stock_id) technical_at,
   (SELECT min(s.calculated_at) FROM public.daily_smc s
    WHERE s.market='tpex' AND s.stock_id=p.stock_id) smc_at,
   (SELECT max(c.calculated_at) FROM public.daily_composite_scores c
    WHERE c.market='tpex' AND c.stock_id=p.stock_id
      AND c.as_of_date=p.last_valid AND c.total_score IS NOT NULL) score_at
 FROM prices p CROSS JOIN latest_market d
 WHERE p.valid_days>=60
   AND p.last_valid>=d.latest_date-interval '7 days'
)
SELECT a.stock_id,a.price_rows,a.valid_days,a.last_valid,
       a.adjusted_rows,a.technical_rows,a.smc_rows,
       a.last_source_write,a.adjusted_at,a.technical_at,
       a.smc_at,a.score_at
FROM analysis a
WHERE
 a.adjusted_rows<a.price_rows OR a.technical_rows<a.price_rows
 OR a.smc_rows<a.price_rows
 OR a.adjusted_at IS NULL OR a.technical_at IS NULL
 OR a.smc_at IS NULL OR a.score_at IS NULL
 OR (a.last_source_write IS NOT NULL AND
     (a.adjusted_at<a.last_source_write
      OR a.technical_at<a.last_source_write
      OR a.smc_at<a.last_source_write
      OR a.score_at<a.last_source_write))
 OR a.technical_at<a.adjusted_at
 OR a.smc_at<a.adjusted_at
 OR a.score_at<GREATEST(a.technical_at,a.smc_at)
 OR EXISTS (
   SELECT 1 FROM public.daily_prices p
   LEFT JOIN public.daily_adjusted_prices d
     ON d.market=p.market AND d.stock_id=p.stock_id AND d.trade_date=p.trade_date
   LEFT JOIN public.daily_technicals t
     ON t.market=p.market AND t.stock_id=p.stock_id AND t.trade_date=p.trade_date
   LEFT JOIN public.daily_smc s
     ON s.market=p.market AND s.stock_id=p.stock_id AND s.trade_date=p.trade_date
   WHERE p.market='tpex' AND p.stock_id=a.stock_id
     AND (
       d.trade_date IS NULL OR t.trade_date IS NULL OR s.trade_date IS NULL
       OR d.calculated_at IS NULL OR t.calculated_at IS NULL
       OR s.calculated_at IS NULL
       OR (a.last_source_write IS NOT NULL AND (
           d.calculated_at<a.last_source_write
           OR t.calculated_at<a.last_source_write
           OR s.calculated_at<a.last_source_write
       ))
     )
 )
ORDER BY
 (a.price_rows-LEAST(a.adjusted_rows,a.technical_rows,a.smc_rows)) DESC,
 a.stock_id
LIMIT %s
"""

RAW_PROOF_SQL = """
SELECT count(*)::bigint AS rows,coalesce(sum(volume),0)::numeric AS volume_sum,
       coalesce(sum(turnover),0)::numeric AS turnover_sum,
       max(retrieved_at) AS newest_ingest
FROM public.daily_prices
WHERE market='tpex' AND stock_id=%s
"""

CHECK_STOCK_SQL = """
WITH official_source AS (
 SELECT max(retrieved_at) newest_official_ingest
 FROM public.daily_prices
 WHERE market='tpex' AND stock_id=%s AND source='TPEX_DATED_OTC_EW'
), raw AS (
 SELECT p.trade_date,
        a.trade_date adjusted_day,t.trade_date technical_day,
        s.trade_date smc_day,
        a.calculated_at adjusted_at,t.calculated_at technical_at,
        s.calculated_at smc_at
 FROM public.daily_prices p
 LEFT JOIN public.daily_adjusted_prices a
   ON a.market=p.market AND a.stock_id=p.stock_id AND a.trade_date=p.trade_date
 LEFT JOIN public.daily_technicals t
   ON t.market=p.market AND t.stock_id=p.stock_id AND t.trade_date=p.trade_date
 LEFT JOIN public.daily_smc s
   ON s.market=p.market AND s.stock_id=p.stock_id AND s.trade_date=p.trade_date
 WHERE p.market='tpex' AND p.stock_id=%s
)
SELECT count(*)::int price_rows,
  count(*) FILTER(WHERE adjusted_day IS NULL OR technical_day IS NULL
    OR smc_day IS NULL)::int missing_derived_days,
  count(*) FILTER(WHERE
    adjusted_day IS NULL OR technical_day IS NULL OR smc_day IS NULL
    OR adjusted_at IS NULL OR technical_at IS NULL OR smc_at IS NULL
    OR (newest_official_ingest IS NOT NULL AND (
      adjusted_at < newest_official_ingest
      OR technical_at < newest_official_ingest
      OR smc_at < newest_official_ingest
    ))
  )::int stale_derived_days
FROM raw CROSS JOIN official_source
"""

# A score that is recomputed but numerically unchanged is intentionally a
# no-op in composite_score.calculate_all(). This dedicated historical
# reconciliation must still record the verified calculation time to avoid
# incorrectly selecting the same stock forever. No actual score values
# change here: only the audit timestamp, after calculate_all() succeeded.
STAMP_VERIFIED_SCORE_SQL = """
UPDATE public.daily_composite_scores c SET calculated_at=clock_timestamp()
WHERE c.market='tpex' AND c.stock_id=%s AND c.as_of_date=%s
  AND c.calculated_at < (
    SELECT GREATEST(t.calculated_at,s.calculated_at,a.calculated_at)
    FROM public.daily_technicals t
    JOIN public.daily_smc s USING(market,stock_id,trade_date)
    JOIN public.daily_adjusted_prices a USING(market,stock_id,trade_date)
    WHERE t.market=c.market AND t.stock_id=c.stock_id AND t.trade_date=c.as_of_date
  )
"""

CHECK_SCORE_SQL = """
SELECT c.total_score,c.calculated_at AS scored_at,
  t.calculated_at AS tech_at,s.calculated_at AS smc_at,
  a.calculated_at AS adjusted_at
FROM public.daily_composite_scores c
JOIN public.daily_technicals t
 ON t.market=c.market AND t.stock_id=c.stock_id AND t.trade_date=c.as_of_date
JOIN public.daily_smc s
 ON s.market=c.market AND s.stock_id=c.stock_id AND s.trade_date=c.as_of_date
JOIN public.daily_adjusted_prices a
 ON a.market=c.market AND a.stock_id=c.stock_id AND a.trade_date=c.as_of_date
WHERE c.market='tpex' AND c.stock_id=%s AND c.as_of_date=%s
"""


def release_ready(proof):
    """Do not collide with legacy normalization or incomplete official source."""
    required = (
        "tpex_source_days","tpex_eligible","tpex_matched","legacy_rows",
        "bad_legacy_volume","bad_legacy_turnover","database_bytes",
    )
    if any(type(proof.get(k)) is not int or proof[k]<0 for k in required):
        raise ValueError("Unverified TPEx release prerequisite")
    if proof["database_bytes"]>=MAX_DATABASE_BYTES:
        raise RuntimeError("Neon Free size guard reached")
    return bool(
        proof["tpex_source_days"]>=MIN_OFFICIAL_SOURCE_DAYS
        and proof["tpex_eligible"]>=MIN_RECENT_ELIGIBLE
        and proof["tpex_matched"]==proof["tpex_eligible"]
        and proof["legacy_rows"]>=1000
        and proof["bad_legacy_volume"]==0
        and proof["bad_legacy_turnover"]==0
    )


def choose(conn,limit=MAX_BATCH):
    if type(limit) is not int or not 1<=limit<=MAX_BATCH:
        raise ValueError("Unsafe historic-factor stock window")
    with conn.cursor() as cursor:
        cursor.execute(CANDIDATES_SQL,(limit,))
        rows=[dict(r) for r in cursor.fetchall()]
    if len(rows)>limit or len({r["stock_id"] for r in rows})!=len(rows):
        raise RuntimeError("Unbounded or repeated TPEx factor targets")
    if any(type(r["valid_days"]) is not int or r["valid_days"]<60
           for r in rows):
        raise RuntimeError("Unverified 60-session TPEx target")
    return rows


def raw_proof(conn,sid):
    with conn.cursor() as cur:
        cur.execute(RAW_PROOF_SQL,(sid,))
        proof=dict(cur.fetchone())
    if type(proof["rows"]) is not int or proof["rows"]<60:
        raise RuntimeError("Unverifiable source price fingerprint")
    return proof


def verify_derived(conn,stock):
    with conn.cursor() as cur:
        cur.execute(CHECK_STOCK_SQL,(stock["stock_id"],stock["stock_id"]))
        checks=dict(cur.fetchone())
    if (checks["price_rows"]!=stock["price_rows"]
            or checks["missing_derived_days"] or checks["stale_derived_days"]):
        raise RuntimeError("TPEx historical adjusted/technical/SMC dates remain missing or stale")
    return checks


def verify_latest_score(conn,stock):
    with conn.cursor() as cur:
        cur.execute(CHECK_SCORE_SQL,(stock["stock_id"],stock["last_valid"]))
        result=cur.fetchone()
    if not result or result["total_score"] is None:
        raise RuntimeError("Missing latest TPEx research score")
    timestamps=("scored_at","tech_at","smc_at","adjusted_at")
    if any(result[k] is None for k in timestamps):
        raise RuntimeError("Missing TPEx factor calculation timestamp")
    if result["scored_at"]<max(result["tech_at"],result["smc_at"],
                               result["adjusted_at"]):
        raise RuntimeError("Latest research score is stale against factor rebuild")


def save(path,report):
    if not path:
        return
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",
                   encoding="utf-8")
    tmp.replace(path)


def execute(url,*,apply=False,rounds=MAX_ROUNDS,report_path=None):
    if not url:
        raise ValueError("Existing protected DATABASE_URL required")
    if type(rounds) is not int or not 0<=rounds<=MAX_ROUNDS:
        raise ValueError("Unsafe historic TPEx factor round count")
    if apply and (rounds==0 or
        os.environ.get("STOCK_TPEX_STALE_FACTOR_WRITE_ENABLED")!="yes" or
        os.environ.get("STOCK_INDICATOR_CATCHUP_WRITE_ENABLED")!="yes" or
        os.environ.get("STOCK_TPEX_STALE_SCORE_WRITE_ENABLED")!="yes"):
        raise ValueError("Three source-specific factor/score write gates required")

    initial=release_snapshot(url)
    ready=release_ready(initial)
    report={
        "scope":"TPEX_SOURCE_VERIFIED_BACKFILL_FACTOR_FRESHNESS",
        "created_utc":datetime.now(timezone.utc).isoformat(),
        "release_preflight_ready":ready,
        "official_tpex_source_days":initial["tpex_source_days"],
        "stocks":[],"complete":False,"raw_prices_modified":False,
        "line_messages_sent":False,"trading_enabled":False,
        "paid_upgrade_requested":False,
    }
    save(report_path,report)
    if apply and not ready:
        raise RuntimeError("TPEx official history or legacy source quality prerequisites unmet")
    with psycopg.connect(url,connect_timeout=20,row_factory=dict_row) as conn:
        for i in range(1,(rounds if apply else 1)+1):
            pending=choose(conn)
            if not pending:
                report["complete"]=ready
                break
            if not apply:
                report["preview_pending_first_batch"]=len(pending)
                break
            for stock in pending:
                sid=stock["stock_id"]
                before=raw_proof(conn,sid)
                try:
                    with conn.transaction():
                        derived=build_adjusted(conn,"tpex",sid)
                        technical=build_technicals(conn,"tpex",sid)
                        smc=build_smc(conn,"tpex",sid)
                        if min(derived,technical,smc)<stock["price_rows"]:
                            raise RuntimeError("Incomplete TPEx historical factor rebuild")
                        verify_derived(conn,stock)
                    conn.commit()
                    # The existing composite calculator uses its own connection.
                    # Failure leaves this stock eligible again due stale score_at.
                    n=calculate_all(url,stocks=[("tpex",sid)],missing_only=False)
                    if n!=1:
                        raise RuntimeError("Expected one stock-scoped, audited score")
                    with conn.cursor() as cur:
                        cur.execute(STAMP_VERIFIED_SCORE_SQL,(sid,stock["last_valid"]))
                    verify_latest_score(conn,stock)
                    after=raw_proof(conn,sid)
                    if after!=before:
                        raise RuntimeError("Original TPEx source OHLCV changed during derived repair")
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                report["stocks"].append({
                    "stock_id":sid,"status":"verified",
                    "raw_price_rows":before["rows"],
                    "adjusted_rows":derived,"technical_rows":technical,
                    "smc_rows":smc,"rescore_processed":n,
                })
                save(report_path,report)
        else:
            # Each invocation remains bounded; re-runnable independent cron
            # only selects remaining stale TPEx stocks, never repaired ones.
            report["complete"]=False
    save(report_path,report)
    return report


def main():
    parser=argparse.ArgumentParser(description="After TPEx dated-backfill factor provenance audit")
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--rounds",type=int,default=MAX_ROUNDS)
    parser.add_argument("--report",type=Path,default=Path("tpex-stale-factor-refresh.json"))
    args=parser.parse_args()
    out=execute(os.getenv("DATABASE_URL",""),apply=args.apply,
                rounds=args.rounds,report_path=args.report)
    print(json.dumps({
        "source_days":out["official_tpex_source_days"],
        "ready":out["release_preflight_ready"],
        "repaired_stocks":len(out["stocks"]),
        "completed":out["complete"],
        "raw_prices_modified":False,"orders_enabled":False,
        "line_trade_signals_enabled":False,
    },ensure_ascii=False))


if __name__=="__main__":
    main()
