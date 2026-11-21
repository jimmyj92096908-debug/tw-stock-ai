"""Bounded prospective freeze outcome read-only auditor.

Check a PREVIOUS precommitted research cohort no sooner than ten calendar
days after its saved signal. Absent matured forward labels is a report, not
permission to backdate or alter precommitted research.
"""
from __future__ import annotations
from datetime import date
from pathlib import Path
import json,os
import psycopg
from psycopg.rows import dict_row
from scripts.audit_frozen_forward_outcomes import run as examine

CANDIDATE_SQL="""WITH market_latest AS (
 SELECT MAX(trade_date) AS last_market_day
 FROM public.daily_prices WHERE close>0
)
SELECT MAX(f.signal_date) AS mature_candidate,m.last_market_day
FROM market_latest m LEFT JOIN public.research_forward_frozen_cohorts f
 ON f.model_version=%s AND f.signal_date<=m.last_market_day-INTERVAL '10 days'
GROUP BY m.last_market_day"""

def check(url,*,report_path=None):
    if not url:
        raise ValueError("Protected read-only Neon connection required")
    with psycopg.connect(url,connect_timeout=15,row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout='30000ms'")
        row=conn.execute(CANDIDATE_SQL,("tw-factor-ridge-1",)).fetchone()
    if row is None or type(row["last_market_day"]) is not date:
        raise ValueError("Actual market cutoff missing")
    if row["mature_candidate"] is None:
        result={
            "scope":"PRECOMMITTED_PROSPECTIVE_RESEARCH_MATURITY_READ_ONLY",
            "status":"NO_OLDER_PRECOMMITTED_COHORT_AVAILABLE",
            "latest_market_session":row["last_market_day"].isoformat(),
            "matured_forward_alpha_proven":False,
            "no_backfill_or_overwrite":True,
            "database_writes":0,
            "LINE_or_trading_enabled":False
        }
    else:
        frozen_day=row["mature_candidate"]
        if type(frozen_day) is not date or frozen_day>row["last_market_day"]:
            raise ValueError("Unverified prior frozen signal day")
        observed=examine(url,model_version="tw-factor-ridge-1",
                         signal_date=frozen_day,cutoff=row["last_market_day"])
        result={
            "scope":"PRECOMMITTED_PROSPECTIVE_RESEARCH_MATURITY_READ_ONLY",
            "status":observed["status"],
            "latest_market_session":row["last_market_day"].isoformat(),
            "audited_prior_frozen_date":frozen_day.isoformat(),
            "prospective_result":observed,
            "matured_forward_alpha_proven":False,
            "no_backfill_or_overwrite":True,
            "database_writes":0,
            "LINE_or_trading_enabled":False
        }
    if report_path:
        p=Path(report_path);p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return result

def main():
    import argparse
    p=argparse.ArgumentParser(description="Read-only mature outcomes on precommitted research")
    p.add_argument("--report",type=Path,default=Path("prospective-outcome-maturity.json"))
    a=p.parse_args()
    result=check(os.getenv("DATABASE_URL",""),report_path=a.report)
    print(json.dumps({k:v for k,v in result.items() if k!="prospective_result"},ensure_ascii=False))

if __name__=="__main__":
    main()
