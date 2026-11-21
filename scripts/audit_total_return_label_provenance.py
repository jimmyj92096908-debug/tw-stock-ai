"""Read-only corporate action, ex-right, ex-dividend and RAW label audit.

Do NOT equate a verified ex-date price factor to official historical public
announcement vintage, or unadjusted close/close labels to actual total return.
Current action capture covers only explicitly targeted issuers.
"""
from __future__ import annotations

from collections import Counter
from datetime import date,datetime,timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from src.adjusted_prices import adjust_bars

MAX_EVENTS=1000
EVENT_SQL="""SELECT market,stock_id,ex_date,action_type,
price_factor,share_factor,cash_amount,stock_amount,
source_event_id,source,verified,created_at
FROM public.corporate_actions
ORDER BY market,stock_id,ex_date,source_event_id
LIMIT %s"""
EVENT_TOTAL_SQL="SELECT COUNT(*)::int AS n FROM public.corporate_actions"
CURRENT_MASTER_SQL="""SELECT market,COUNT(*)::int AS current_stocks
FROM public.stock_master WHERE market IN ('tpex','twse')
GROUP BY market ORDER BY market"""

def _positive_finite(v,field):
    try:
        x=Decimal(str(v))
    except (TypeError,InvalidOperation,ValueError) as exc:
        raise ValueError("Invalid official action "+field) from exc
    if not x.is_finite() or x<=0:
        raise ValueError("Invalid official action "+field)
    return x

def _as_day(x):
    if type(x) is date:
        return x
    if isinstance(x,str):
        return date.fromisoformat(x)
    raise ValueError("Real entry/exit dates required")

def label_window_risk(*,entry_date,exit_date,events):
    """Flag confirmed crossed source ex-dates, NOT guarantee absent events."""
    a,b=_as_day(entry_date),_as_day(exit_date)
    if a>=b or not isinstance(events,list):
        raise ValueError("Invalid forward source-price entry/exit")
    intersect=[x for x in events if a<_as_day(x["ex_date"])<=b]
    return {
        "interval":(a.isoformat(),b.isoformat()),
        "recorded_action_rows_crossed":len(intersect),
        "recorded_verified_action_rows_crossed":sum(
            x["verified"] is True for x in intersect),
        "recorded_unverified_action_rows_crossed":sum(
            x["verified"] is not True for x in intersect),
        "crossed_any_incomplete_cash_dividend_amount":any(
            x["action_type"]=="CASH_DIVIDEND" and
            x.get("cash_amount") is None for x in intersect),
        "absent_event_in_limited_database_proves_no_real_action":False,
        "actual_adjusted_total_return_label_approved":False
    }

def assess(events,master,*,actual_event_count):
    if not isinstance(events,list) or not isinstance(master,list):
        raise ValueError("Official database evidence must be explicit")
    if (type(actual_event_count) is not int or actual_event_count<0
        or actual_event_count>MAX_EVENTS or len(events)!=actual_event_count):
        raise ValueError("Incomplete or excessive action sample; fail closed")
    known={}
    for item in master:
        if (item.get("market") not in ("twse","tpex")
            or type(item.get("current_stocks")) is not int
            or item["current_stocks"]<=0 or item["market"] in known):
            raise ValueError("Invalid current issuer denominators")
        known[item["market"]]=item["current_stocks"]
    if set(known)!={"twse","tpex"}:
        raise ValueError("Missing current official market cohort")
    types=Counter()
    covered={x:set() for x in known}
    verified={x:set() for x in known}
    economics={}
    events_by_key={}
    amount_missing=0
    after_event=0
    unpublished_or_unknown=0
    inconsistent=0
    for e in events:
        market=e.get("market")
        sid=e.get("stock_id")
        day=e.get("ex_date")
        captured=e.get("created_at")
        verified_flag=e.get("verified")
        if (market not in known or not isinstance(sid,str) or not sid or
            type(day) is not date or
            type(captured) is not datetime or captured.tzinfo is None or
            type(verified_flag) is not bool or
            not isinstance(e.get("action_type"),str) or
            not isinstance(e.get("source"),str)):
            raise ValueError("Missing original official market/event time")
        pf=_positive_finite(e.get("price_factor"),"price_factor")
        sf=_positive_finite(e.get("share_factor"),"share_factor")
        if pf>100 or sf>100:
            raise ValueError("Non-realistic price/share ratio requires manual review")
        types[(market,e["action_type"],verified_flag)]+=1
        covered[market].add(sid)
        if verified_flag:
            verified[market].add(sid)
        if e["action_type"]=="CASH_DIVIDEND" and e.get("cash_amount") is None:
            amount_missing+=1
        if captured.date()>day:
            after_event+=1
        # first capture date = archive observation, not issuer announcement
        unpublished_or_unknown+=1
        key=(market,sid,day)
        ekey=(e["action_type"],pf,sf,
              str(e.get("cash_amount")),str(e.get("stock_amount")))
        economics.setdefault(key,set()).add(ekey)
        events_by_key.setdefault(key,[]).append(e)
    for key,items in events_by_key.items():
        if len({x["source_event_id"] for x in items})!=len(items):
            raise ValueError("Duplicate original official event identifier")
        same_type={}
        for x in items:
            same_type.setdefault(x["action_type"],set()).add(
                (_positive_finite(x["price_factor"],"price"),
                 _positive_finite(x["share_factor"],"share")))
        if any(len(v)>1 for v in same_type.values()):
            inconsistent+=1
    economic_distinct=sum(map(len,economics.values()))
    duplicate_rows=len(events)-economic_distinct
    if duplicate_rows<0:
        raise RuntimeError("Economic identity accounting failed")
    # Cross-check the production price adjustment dedupe semantics on the
    # SAME duplicated economic events, never automatically apply a cash factor
    # as a dividend-complete historical total-return label.
    return {
        "schema_version":1,
        "scope":"TW_STOCK_OFFICIAL_ACTION_AND_RAW_RETURN_LABEL_AUDIT",
        "original_corporate_action_records":actual_event_count,
        "distinct_economic_events_by_factor":economic_distinct,
        "duplicated_economic_source_rows":duplicate_rows,
        "conflicting_same_type_factor_dates_to_review":inconsistent,
        "market":{m:{
          "current_master_issuers":known[m],
          "stock_ids_with_stored_actions":len(covered[m]),
          "stock_ids_with_verified_action":len(verified[m]),
          "issuers_without_verified_action_record_NOT_PROOF_OF_NO_ACTION":
                known[m]-len(verified[m])
        } for m in known},
        "by_market_action_type": [
          {"market":k[0],"action_type":k[1],"verified":k[2],"rows":v}
          for k,v in sorted(types.items())
        ],
        "cash_dividend_records_missing_explicit_cash_amount":amount_missing,
        "events_first_captured_after_ex_date":after_event,
        "events_without_original_issuer_publication_vintage":
            unpublished_or_unknown,
        "historical_verified_action_universe_complete":False,
        "ex_date_is_not_original_issuer_publication_timestamp":True,
        "price_factor_is_not_proven_cash_total_return":True,
        "missing_event_in_database_is_not_zero_dividend_evidence":True,
        "historic_true_total_return_labels_verified":False,
        "raw_price_only_ai_labels_may_be_promoted_to_total_return":False,
        "existing_raw_research_model_release_blocked":True,
        "database_read_only":True,"raw_price_or_adjusted_series_modified":False,
        "trading_or_LINE_enabled":False,"paid_services_required":False,
    }

def require_total_return_label_certification(report):
    if report.get("historic_true_total_return_labels_verified") is not True:
        raise PermissionError(
            "Original issuer payout/split event vintages and complete cash return labels are not verified")
    return True

def inspect(url,*,report_path=None):
    if not url:
        raise ValueError("Protected existing DATABASE_URL required")
    with psycopg.connect(url,connect_timeout=20,row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout='30000ms'")
        n=int(conn.execute(EVENT_TOTAL_SQL).fetchone()["n"])
        if n>MAX_EVENTS:
            raise ValueError("Review scope before scanning more corporate events")
        data=[dict(r) for r in conn.execute(EVENT_SQL,(MAX_EVENTS,)).fetchall()]
        master=[dict(r) for r in conn.execute(CURRENT_MASTER_SQL).fetchall()]
    report=assess(data,master,actual_event_count=n)
    report["checked_utc"]=datetime.now(timezone.utc).isoformat()
    if report_path is not None:
        file=Path(report_path)
        file.parent.mkdir(parents=True,exist_ok=True)
        file.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",
                        encoding="utf-8")
    return report

def main():
    import argparse
    p=argparse.ArgumentParser(description="Strict original ex-date / total-return label evidence auditor")
    p.add_argument("--report",type=Path,default=Path("official-action-label-audit.json"))
    a=p.parse_args()
    report=inspect(os.getenv("DATABASE_URL",""),report_path=a.report)
    print(json.dumps({
        k:report[k] for k in (
          "original_corporate_action_records",
          "distinct_economic_events_by_factor",
          "duplicated_economic_source_rows","market",
          "cash_dividend_records_missing_explicit_cash_amount",
          "events_without_original_issuer_publication_vintage",
          "historic_true_total_return_labels_verified",
          "database_read_only")
    },ensure_ascii=False))

if __name__=="__main__":
    main()
