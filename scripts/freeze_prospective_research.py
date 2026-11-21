"""Capture a complete immutable prospective *research-only* model cohort.

The input is one consistent PostgreSQL snapshot of the actual latest saved
features, joined to verified daily prices. This does NOT score future prices.
"""
from __future__ import annotations
import argparse
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.trained_factor_model import LATEST_MODEL_SQL
from src.research_forward_freeze import (
    build_frozen_universe, canonical, summary,
)

MAX_DATABASE_BYTES=800_000_000
MAX_DATA_SIZE=1_800_000
MAX_SQL_MILLISECONDS=30000
CURRENT_PRICE_SQL="SELECT MAX(trade_date) AS latest FROM public.daily_prices WHERE close>0"
SIZE_SQL="SELECT pg_database_size(current_database())::bigint AS bytes"
INSERT_SQL="""
INSERT INTO public.research_forward_frozen_cohorts
(model_version,signal_date,model_sha256,cohort_sha256,
 universe_count,selected_count,roster)
VALUES (%(model_version)s::varchar(90),%(signal_date)s::date,
        %(model_sha256)s::char(64),%(cohort_sha256)s::char(64),
        %(universe_count)s::integer,%(selected_count)s::integer,
        %(roster)s::jsonb)
ON CONFLICT (model_version,signal_date) DO NOTHING
RETURNING cohort_sha256
"""
READ_SQL="""
SELECT cohort_sha256,model_sha256,universe_count,frozen_at
FROM public.research_forward_frozen_cohorts
WHERE model_version=%s AND signal_date=%s
"""


def _size(cur):
    cur.execute(SIZE_SQL)
    n=cur.fetchone()["bytes"]
    if type(n) is not int or n<=0 or n>=MAX_DATABASE_BYTES:
        raise RuntimeError("Neon Free research freeze: conservative 800MB stop line")
    return n


def execute(url,*,model_path,apply=False,report_path=None):
    if apply and os.getenv("STOCK_FORWARD_RESEARCH_FREEZE_WRITE")!="yes":
        raise PermissionError("Explicit owner-approved prospective research freeze required")
    if not url:
        raise ValueError("Protected existing database URL required")
    raw=Path(model_path).read_bytes()
    if not 0<len(raw)<100_000:
        raise ValueError("Frozen research model artifact unbounded")
    model=json.loads(raw)
    model_hash=sha256(raw).hexdigest()
    with psycopg.connect(url,connect_timeout=15,autocommit=True,row_factory=dict_row) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                # Consistent as-of universe. A score recomputation that lands
                # after the snapshot cannot alter the frozen roster.
                cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                cur.execute("SET LOCAL statement_timeout = '30000ms'")
                size_before=_size(cur)
                cur.execute(CURRENT_PRICE_SQL)
                price_day=cur.fetchone()["latest"]
                cur.execute(LATEST_MODEL_SQL)
                source=[dict(r) for r in cur.fetchall()]
                # The trusted DB clock is queried after source selection.
                cur.execute("SELECT clock_timestamp() AS now")
                measured=cur.fetchone()["now"]
                frozen=build_frozen_universe(
                    source,model,model_sha256=model_hash,
                    as_of=measured,latest_market_date=price_day)
                report=summary(frozen)
                report["persisted"]=False
                report["new_frozen_cohort"]=False
                report["source_current_price_day"]=str(price_day)
                report["storage_before_bytes"]=size_before
                report["no_database_writes_on_preview"]=not apply
                if apply:
                    # If source JSON is too big, refuse rather than consuming
                    # the entire Neon Free quota.
                    packed=canonical(frozen["members"])
                    if len(packed.encode("utf-8"))>MAX_DATA_SIZE:
                        raise RuntimeError("Prospective roster size exceeds hard cap")
                    cur.execute((ROOT/"sql/research_forward_frozen_cohorts.sql").read_text(encoding="utf-8"))
                    cur.execute(INSERT_SQL,{
                        **frozen,"roster":packed,
                    })
                    created=cur.fetchone()
                    cur.execute(READ_SQL,(frozen["model_version"],frozen["signal_date"]))
                    existing=cur.fetchone()
                    if (existing is None or
                        existing["cohort_sha256"].strip()!=frozen["cohort_sha256"] or
                        existing["model_sha256"].strip()!=model_hash or
                        existing["universe_count"]!=frozen["universe_count"]):
                        raise RuntimeError("Existing frozen cohort differs: NEVER overwrite or repair as-of history")
                    report["persisted"]=True
                    report["new_frozen_cohort"]=created is not None
                    report["database_frozen_at"]=existing["frozen_at"].isoformat()
                    # Single transaction fail-closed: storage beyond the
                    # budget causes rollback of the new frozen day.
                    report["storage_after_bytes"]=_size(cur)
    if report_path:
        target=Path(report_path)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",
                          encoding="utf-8")
    return report


def main():
    ap=argparse.ArgumentParser(description="Immutable pre-return research cohort only")
    ap.add_argument("--apply",action="store_true")
    ap.add_argument("--model-in",type=Path,default=ROOT/"models/tw-factor-ridge-1-research.json")
    ap.add_argument("--report",type=Path,default=Path("prospective-research-freeze-evidence.json"))
    args=ap.parse_args()
    result=execute(os.getenv("DATABASE_URL",""),model_path=args.model_in,
                   apply=args.apply,report_path=args.report)
    print(json.dumps({k:result[k] for k in (
        "signal_date","universe_count","selected_count","cohort_sha256",
        "persisted","new_frozen_cohort","eligible_for_model_release",
        "live_trading_approved","line_signal_delivery_approved")},ensure_ascii=False))


if __name__=="__main__":
    main()
