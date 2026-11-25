"""Read-only dual-track owner research readiness: chip inventory and label endpoints.

No performance calculation. Observed market dates are NOT official calendar proof.
Every accepted feature key is preserved. Absence of stored corporate action rows
is NOT proof of absence of actual actions. Only aggregate evidence is emitted.
"""
from collections import Counter, defaultdict
from datetime import date, timedelta
import argparse
import json
import os

from scripts import owner_quarterly_chip_vintage_coverage_readonly as chip
from scripts import owner_twse_tpex_quarterly_panel_merge_offline as m
from scripts import twse_tpex_five_year_neon_only_cohort_readonly as baseline

CUTOFF=date(2026,11,20)
START=date(2021,11,23)
CHIP_TABLES=(("institutional_flows","trade_date"),("margin_short","trade_date"),
             ("tdcc_share_distribution","as_of_date"),("insider_holdings","as_of_date"))
PRICE_TAGS={k:sorted(v) for k,v in baseline.SOURCES.items()}
MIN_TRAIN_DATES=20
# Internal constants only; identifiers never originate from CLI input.
def inventory_sql(table,day):
    if (table,day) not in CHIP_TABLES:
        raise ValueError("Unknown source table")
    return f"""SELECT market,source,EXTRACT(YEAR FROM {day})::int,
        COUNT(*)::bigint,COUNT(DISTINCT stock_id)::int,COUNT(DISTINCT {day})::int,
        MIN({day}),MAX({day}),
        COUNT(*) FILTER(WHERE retrieved_at < (({day}+1)::timestamp AT TIME ZONE 'Asia/Taipei'))::bigint
        FROM public.{table}
        WHERE market IN ('twse','tpex') AND stock_id=ANY(%s)
        AND {day} BETWEEN %s AND %s
        GROUP BY 1,2,3 ORDER BY 1,2,3 LIMIT 201"""

CAL_SQL=baseline.ELIGIBLE+"""
SELECT p.trade_date,COUNT(*)::int
FROM public.daily_prices p JOIN eligible e ON e.market=p.market AND e.stock_id=p.stock_id
WHERE p.market=%s AND p.trade_date>%s AND p.trade_date<=%s
AND p.close>0 AND p.volume>=0 AND p.source=ANY(%s)
GROUP BY 1 ORDER BY 1 LIMIT 6
"""
ENDPOINT_SQL="""
SELECT stock_id,trade_date,open,high,low,close,volume,source
FROM public.daily_prices
WHERE market=%s AND stock_id=ANY(%s) AND trade_date=ANY(%s)
ORDER BY stock_id,trade_date LIMIT 6601
"""
ACTION_SQL="""
SELECT stock_id,COUNT(*)::int,COUNT(*) FILTER(WHERE verified IS TRUE)::int
FROM public.corporate_actions
WHERE market=%s AND stock_id=ANY(%s) AND ex_date>%s AND ex_date<=%s
GROUP BY stock_id ORDER BY stock_id LIMIT 1100
"""


def inspect_window(ids,signal,calendar,prices,actions,market):
    if (market not in PRICE_TAGS or type(signal) is not date or not ids
        or len(ids)>1092 or len(set(ids))!=len(ids)
        or len(calendar)>6 or len(prices)>6*len(ids) or len(actions)>len(ids)):
        raise ValueError("Invalid bounded research window")
    days=[r[0] for r in calendar]
    if (days!=sorted(set(days)) or any(type(d) is not date or not signal<d<=CUTOFF
        or d.weekday()>=5 or type(n) is not int or not 1<=n<=1092 for d,n in calendar)):
        raise ValueError("Invalid observed market calendar")
    allowed=set(ids);index={};action_index={}
    for sid,d,o,h,l,c,v,tag in prices:
        if sid not in allowed or d not in days or (sid,d) in index:
            raise ValueError("Foreign or duplicate endpoint source")
        # Numeric columns are PostgreSQL Decimal/int, never guessed strings.
        try:
            valid=(tag in PRICE_TAGS[market] and all(x is not None and x>0 and x.is_finite() for x in (o,h,l,c))
                and l<=min(o,c)<=max(o,c)<=h and type(v) is int and v>=0)
        except (AttributeError,ArithmeticError,TypeError):
            valid=False
        index[sid,d]=valid
    for sid,n,k in actions:
        if sid not in allowed or sid in action_index or type(n) is not int or type(k) is not int or not 0<=k<=n or n==0:
            raise ValueError("Invalid stored action evidence")
        action_index[sid]=(n,k)
    reasons=Counter()
    if len(days)<6:
        reasons["fewer_than_six_observed_future_sessions_by_cutoff"]=len(ids)
    else:
        for sid in ids:
            if not all(index.get((sid,d),False) for d in days):
                reasons["missing_or_invalid_common_six_session_path"]+=1
                continue
            n,k=action_index.get(sid,(0,0))
            if n==0:
                reasons["raw_path_complete_no_stored_action_not_proof_of_absence"]+=1
            elif k<n:
                reasons["raw_path_complete_stored_unverified_action"]+=1
            else:
                reasons["raw_path_complete_stored_verified_action_not_complete_proof"]+=1
    if sum(reasons.values())!=len(ids):
        raise RuntimeError("Endpoint coverage partition mismatch")
    complete=sum(n for k,n in reasons.items() if k.startswith("raw_path_complete"))
    return {"market":market,"signal_date":signal.isoformat(),"candidate_rows":len(ids),
        "observed_future_sessions":[d.isoformat() for d in days],"raw_complete_path_rows":complete,
        "whole_market_signal_cohort_raw_path_complete":complete==len(ids),
        "reasons":dict(sorted(reasons.items())),"approved_total_return_labels":0}


def capture(url,groups):
    import psycopg
    if not isinstance(url,str) or not url.startswith(("postgres://","postgresql://")):
        raise ValueError("Protected local URL required")
    inventory={};reports=[]
    # Current accepted panel IDs only; stock IDs do not cross markets.
    ids=sorted({s for a in groups.values() for s in a})
    if len(ids)!=1778:
        raise ValueError("Owner merged distinct roster changed")
    with psycopg.connect(url,connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cur.execute("SET LOCAL statement_timeout='45s'")
            for table,day in CHIP_TABLES:
                cur.execute(inventory_sql(table,day),(ids,START,CUTOFF))
                rows=cur.fetchall()
                if len(rows)>200:
                    raise ValueError("Chip inventory bound exceeded")
                inventory[table]=[{"market":a,"source":b,"year":y,"stored_rows":n,
                    "distinct_stocks":s,"distinct_dates":d,"first_date":lo.isoformat(),"last_date":hi.isoformat(),
                    "retrieved_before_end_of_observation_day_rows":k} for a,b,y,n,s,d,lo,hi,k in rows]
            for (market,day),members in sorted(groups.items()):
                signal=date.fromisoformat(day)
                cur.execute(CAL_SQL,(market,signal,min(CUTOFF,signal+timedelta(days=35)),PRICE_TAGS[market]))
                cal=cur.fetchall();prices=[];actions=[]
                if len(cal)==6:
                    cur.execute(ENDPOINT_SQL,(market,members,[r[0] for r in cal]))
                    prices=cur.fetchall()
                    # Include all stored action events after signal, not merely
                    # entry to exit; cannot certify missing events.
                    cur.execute(ACTION_SQL,(market,members,signal,cal[-1][0]))
                    actions=cur.fetchall()
                reports.append(inspect_window(members,signal,cal,prices,actions,market))
        conn.rollback()
    return inventory,reports


def summarize(inventory,reports):
    if len(reports)!=34 or sum(r["candidate_rows"] for r in reports)!=24873:
        raise ValueError("Owner panel partition mismatch")
    dates={r["signal_date"] for r in reports}
    complete_dates={d for d in dates if all(r["whole_market_signal_cohort_raw_path_complete"] for r in reports if r["signal_date"]==d)}
    return {"schema_version":1,"scope":"OWNER_DUAL_TRACK_CHIP_INVENTORY_AND_RAW_ENDPOINT_READINESS",
        "candidate_rows":24873,"chip_inventory_scope":"1778_accepted_issuer_ids_only_current_storage",
        "chip_inventory_stored_rows":{k:sum(r["stored_rows"] for r in v) for k,v in inventory.items()},
        "raw_complete_path_rows":sum(r["raw_complete_path_rows"] for r in reports),
        "complete_dual_market_raw_path_dates":len(complete_dates),
        "maximum_mature_quarterly_signal_dates":sum(d<CUTOFF.isoformat() for d in dates),
        "minimum_existing_ridge_training_signal_dates":MIN_TRAIN_DATES,
        "quarterly_schedule_alone_meets_existing_training_date_minimum":False,
        "approved_total_return_labels":0,"returns_computed":False,"model_trained":False,
        "official_calendar_independently_proven":False,"corporate_action_absence_independently_proven":False,
        "chip_publication_vintage_verified":False,"production_neon_writes":0,"line_messages_sent":0,
        "paid_upgrade_requested":False,"model_release":"BLOCKED",
        "private_inventory":inventory,"market_signal_outcomes":reports}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--panel",required=True);p.add_argument("--out",required=True)
    a=p.parse_args();stage="PANEL"
    try:
        src=m.private_path(a.panel,existing=True);out=m.private_path(a.out,existing=False)
        payload,digest=m.read_panel(src);groups=chip.verify_input(payload)
        stage="NEON_READONLY"
        result=summarize(*capture(os.environ.get("DATABASE_URL",""),groups))
        result["input_panel_sha256"]=digest
        stage="PRIVATE_OUTPUT"
        with out.open("x",encoding="utf-8") as f:
            json.dump(result,f,indent=2,allow_nan=False);f.write("\n")
        print(json.dumps({k:v for k,v in result.items() if k not in ("private_inventory","market_signal_outcomes")},allow_nan=False))
    except Exception:
        raise SystemExit("FAILED safely; diagnostic_stage="+stage+"; no Neon writes or LINE action") from None


if __name__=="__main__":
    main()
