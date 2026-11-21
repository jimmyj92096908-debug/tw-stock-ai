"""Read ONLY precommitted Ridge full-cohort label maturity and returns.

No training, editing old rows, cloud scheduler, LINE, or live brokerage orders.
A successful observation is NOT an independently audited positive-alpha model.
"""
from __future__ import annotations
import argparse
from datetime import date,datetime
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.research_forward_outcome import FROZEN_LABEL_SQL,assess_frozen_outcomes

LATEST_FREEZE_SQL="""
SELECT MAX(signal_date) AS signal_date
FROM public.research_forward_frozen_cohorts
WHERE model_version=%s
"""
MARKET_CUTOFF_SQL="SELECT MAX(trade_date) AS latest FROM public.daily_prices WHERE close>0"


def run(url,*,model_version="tw-factor-ridge-1",
        signal_date=None,cutoff=None,report_path=None):
    if not url:
        raise ValueError("Existing protected database connection required")
    if model_version!="tw-factor-ridge-1":
        raise ValueError("Other models have not been prospectively sealed")
    with psycopg.connect(url,connect_timeout=15,row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cur.execute("SET LOCAL statement_timeout='30000ms'")
                cur.execute(LATEST_FREEZE_SQL,(model_version,))
                newest=cur.fetchone()["signal_date"]
                if newest is None:
                    raise ValueError("No genuine prior precommitted model roster exists")
                start=signal_date or newest
                if isinstance(start,str):
                    start=date.fromisoformat(start)
                if type(start) is not date or start>newest:
                    raise ValueError("Invalid or future prospective signal date")
                cur.execute(MARKET_CUTOFF_SQL)
                market_latest=cur.fetchone()["latest"]
                observed=cutoff or market_latest
                if isinstance(observed,str):
                    observed=date.fromisoformat(observed)
                if type(observed) is not date or market_latest is None:
                    raise ValueError("Verified market cutoff date required")
                if observed>market_latest or observed>datetime.now(
                        ZoneInfo("Asia/Taipei")).date() or observed<start:
                    raise ValueError("Cannot observe future or pre-signal labels")
                cur.execute(FROZEN_LABEL_SQL,(model_version,start,observed))
                aggregate=cur.fetchone()
                if aggregate is None:
                    raise ValueError("Selected genuine prospective frozen day absent")
                report=assess_frozen_outcomes(dict(aggregate),cutoff=observed)
    if report_path:
        p=Path(report_path)
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return report


def main():
    ap=argparse.ArgumentParser(description="First-frozen full-cohort research return readiness ONLY")
    ap.add_argument("--signal-date",type=date.fromisoformat,default=None)
    ap.add_argument("--cutoff",type=date.fromisoformat,default=None)
    ap.add_argument("--out",type=Path,default=Path("frozen-research-forward-outcome.json"))
    args=ap.parse_args()
    report=run(os.getenv("DATABASE_URL",""),signal_date=args.signal_date,
               cutoff=args.cutoff,report_path=args.out)
    print(json.dumps({k:report.get(k) for k in (
        "signal_date","label_cutoff","universe_count","selected_count",
        "entry_count","exit_count","matured_members","status",
        "model_net_excess","baseline_net_excess","live_trading_approved")},
        ensure_ascii=False))


if __name__=="__main__":
    main()
