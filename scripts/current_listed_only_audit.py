"""Verify official currently listed exchange membership for research selection.

This is a read-only evidence gate; it never removes raw price rows or
retroactively edits immutable old score/cohort snapshots.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import json,os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from src.current_official_listing import (
    CURRENT_OFFICIAL_LISTED_CTE,CURRENT_UNIVERSE_SELECTION
)

AUDIT_SQL=f"""{CURRENT_OFFICIAL_LISTED_CTE}
SELECT
 (SELECT MAX(observed_at) FROM current_receipt) AS last_current_official_observed_at,
 (SELECT COUNT(*)::int FROM official_current_listed) AS official_current_listing_count,
 (SELECT COUNT(*)::int FROM public.stock_master) AS current_master_count,
 (SELECT COUNT(*)::int FROM public.stock_master sm
   JOIN official_current_listed a ON a.market=sm.market AND a.stock_id=sm.stock_id)
   AS matched_current_exchange_issuers,
 (SELECT COUNT(*)::int FROM public.stock_master sm
   LEFT JOIN official_current_listed a ON a.market=sm.market AND a.stock_id=sm.stock_id
   WHERE a.stock_id IS NULL) AS master_only_excluded,
 (SELECT COUNT(*)::int FROM official_current_listed a
   LEFT JOIN public.stock_master sm ON sm.market=a.market AND sm.stock_id=a.stock_id
   WHERE sm.stock_id IS NULL) AS official_missing_from_current_master
"""
EXCLUSIONS_SQL=f"""{CURRENT_OFFICIAL_LISTED_CTE}
SELECT sm.market,sm.stock_id,sm.stock_name
FROM public.stock_master sm
LEFT JOIN official_current_listed a
 ON a.market=sm.market AND a.stock_id=sm.stock_id
WHERE a.stock_id IS NULL
ORDER BY sm.market,sm.stock_id LIMIT 20
"""

def verify(summary,excluded):
    if not isinstance(summary,dict) or not isinstance(excluded,list):
        raise ValueError("Missing actual official current source evidence")
    nums=("official_current_listing_count","current_master_count",
          "matched_current_exchange_issuers","master_only_excluded",
          "official_missing_from_current_master")
    if any(type(summary.get(k)) is not int or summary[k]<0 for k in nums):
        raise ValueError("Invalid current listed universe count")
    if (summary["official_current_listing_count"]<1000 or
        summary["matched_current_exchange_issuers"]<1000 or
        summary["matched_current_exchange_issuers"]+
          summary["master_only_excluded"]!=summary["current_master_count"] or
        summary["matched_current_exchange_issuers"]+
          summary["official_missing_from_current_master"]!=
          summary["official_current_listing_count"]):
        raise ValueError("Current official market source or saved master not reconciled")
    if (summary["master_only_excluded"]<len(excluded) or
        len(excluded)>20 or
        any(item.get("market") not in ("twse","tpex") or
            not isinstance(item.get("stock_id"),str) for item in excluded)):
        raise ValueError("Invalid excluded code evidence")
    if type(summary.get("last_current_official_observed_at")) is not datetime:
        raise ValueError("Current exchange company source is unavailable or expired")
    return {
        "schema_version":1,
        "scope":"CURRENT_OFFICIALLY_LISTED_STOCK_ONLY_NO_DELISTED_SELECTION",
        "last_current_official_observed_at":
           summary["last_current_official_observed_at"].isoformat(),
        "current_official_snapshot_max_age_days":14,
        "current_official_stocks":summary["official_current_listing_count"],
        "master_stocks":summary["current_master_count"],
        "selectable_officially_listed_master_stocks":
           summary["matched_current_exchange_issuers"],
        "master_only_stocks_excluded_from_new_rankings":
           summary["master_only_excluded"],
        "sample_excluded_stocks":excluded,
        "official_not_yet_synchronized_to_master":
           summary["official_missing_from_current_master"],
        "new_research_universe_rule":CURRENT_UNIVERSE_SELECTION,
        "historical_scores_and_raw_prices_preserved":True,
        "already_frozen_historical_predictions_modified":False,
        "historical_survivorship_bias_explicit":True,
        "historical_unbiased_alpha_claim_allowed":False,
        "live_trading_approved":False,
        "line_messages_sent":False,
        "database_writes":0,
    }

def inspect(url,*,report_path=None):
    if not url:
        raise ValueError("Existing protected read-only database URL required")
    with psycopg.connect(url,connect_timeout=20,row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout='30000ms'")
        summary=dict(conn.execute(AUDIT_SQL).fetchone())
        exclusions=[dict(r) for r in conn.execute(EXCLUSIONS_SQL).fetchall()]
    report=verify(summary,exclusions)
    report["audited_utc"]=datetime.now(timezone.utc).isoformat()
    if report_path:
        p=Path(report_path)
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",
                     encoding="utf-8")
    return report

def main():
    p=argparse.ArgumentParser(description="Read-only actual current-market listed-only research pool")
    p.add_argument("--report",type=Path,default=Path("current-listed-only-proof.json"))
    args=p.parse_args()
    result=inspect(os.getenv("DATABASE_URL",""),report_path=args.report)
    print(json.dumps({k:result[k] for k in (
        "current_official_stocks","master_stocks",
        "selectable_officially_listed_master_stocks",
        "master_only_stocks_excluded_from_new_rankings",
        "sample_excluded_stocks","historical_unbiased_alpha_claim_allowed",
        "database_writes")},ensure_ascii=False))

if __name__=="__main__":
    main()
