"""Fail-closed acceptance of existing 50% coverage *evidence*, offline only.

The individual indicator+SMC and scored counts are not necessarily the SAME
stocks. A 50% release claim requires the verified intersection, not just the
minimum of two unrelated aggregate counts.
"""
from __future__ import annotations

from datetime import date
import math

COUNTS=("universe","priced","price_rows","technical_current","smc_current",
        "both_current","scored_current")
# An OPTIONAL, bounded, read-only snapshot query for future manual audit.
# Do NOT auto-run while the owner-authorized catch-up is active.
INTERSECTION_SQL = """
WITH p AS (
  SELECT market,stock_id,MAX(trade_date) day
  FROM public.daily_prices WHERE close>0 GROUP BY market,stock_id
)
SELECT COUNT(*)::int AS scored_and_both_current
FROM p
WHERE EXISTS (
 SELECT 1 FROM public.daily_technicals t
 WHERE t.market=p.market AND t.stock_id=p.stock_id AND t.trade_date=p.day
)
AND EXISTS (
 SELECT 1 FROM public.daily_smc s
 WHERE s.market=p.market AND s.stock_id=p.stock_id AND s.trade_date=p.day
)
AND EXISTS (
 SELECT 1 FROM public.daily_composite_scores c
 WHERE c.market=p.market AND c.stock_id=p.stock_id
 AND c.as_of_date=p.day AND c.total_score IS NOT NULL
)
"""


def _count(snapshot, key):
    v=snapshot.get(key)
    if type(v) is not int or v<0:
        raise ValueError("Missing/noninteger/nonnegative coverage count: "+key)
    return v


def validate_snapshot(s):
    if not isinstance(s,dict):
        raise ValueError("Coverage snapshot must be a JSON object")
    values={k:_count(s,k) for k in COUNTS}
    u,p=values["universe"],values["priced"]
    if u<1 or not p<=u or values["price_rows"]<p:
        raise ValueError("Invalid priced-stock universe / raw price baseline")
    if any(values[k]>p for k in ("technical_current","smc_current",
                                  "both_current","scored_current")):
        raise ValueError("Latest-date counts exceed priced population")
    if values["both_current"]>min(values["technical_current"],values["smc_current"]):
        raise ValueError("Technical+SMC intersection exceeds each component")
    d=s.get("latest_price_date")
    if not isinstance(d,str) or len(d)!=10 or date.fromisoformat(d).isoformat()!=d:
        raise ValueError("Verified latest positive price date required")
    overlap=s.get("scored_and_both_current")
    if overlap is not None:
        if type(overlap) is not int or not 0<=overlap<=min(
                values["both_current"],values["scored_current"]):
            raise ValueError("Invalid matching same-stock scored indicator overlap")
    return {**values,"latest_price_date":d,
            "scored_and_both_current":overlap}


def acceptance(before,after, *, target_fraction=.50):
    b,a=validate_snapshot(before),validate_snapshot(after)
    if isinstance(target_fraction,bool) or not isinstance(target_fraction,(int,float)):
        raise ValueError("Invalid target fraction")
    if not math.isfinite(target_fraction) or not 0<target_fraction<=1:
        raise ValueError("Invalid target fraction")
    for key in ("universe","priced","price_rows","latest_price_date"):
        if a[key]!=b[key]:
            raise ValueError("Underlying universe/price source changed: "+key)
    for key in ("technical_current","smc_current","both_current","scored_current"):
        if a[key]<b[key]:
            raise ValueError("Analysis coverage regressed: "+key)
    if (a["scored_and_both_current"] is not None and
        b["scored_and_both_current"] is not None and
        a["scored_and_both_current"]<b["scored_and_both_current"]):
        raise ValueError("Matching scored+indicator coverage regressed")
    target=math.ceil(a["universe"]*target_fraction)
    both_ready=a["both_current"]>=target
    scored_ready=a["scored_current"]>=target
    matched=a["scored_and_both_current"]
    if not both_ready:
        status="INDICATOR_COVERAGE_NOT_READY"
    elif not scored_ready:
        status="SCORE_REBUILD_NOT_READY"
    elif matched is None:
        status="COHORT_INTERSECTION_NOT_VERIFIED"
    elif matched<target:
        status="MATCHED_STOCK_COVERAGE_NOT_READY"
    else:
        status="RESEARCH_COVERAGE_THRESHOLD_VERIFIED"
    return {
        "schema_version":1,"target_stocks":target,
        "universe":a["universe"],"latest_price_date":a["latest_price_date"],
        "technical_and_smc_current":a["both_current"],
        "scored_current":a["scored_current"],
        "verified_scored_and_both_current":matched,
        "new_indicator_stocks":a["both_current"]-b["both_current"],
        "new_scored_stocks":a["scored_current"]-b["scored_current"],
        "research_coverage_passed":status=="RESEARCH_COVERAGE_THRESHOLD_VERIFIED",
        "status":status,
        "investment_alpha_validated":False,
        "live_trading_approved":False,
        "line_signal_approved":False,
        "production_database_modified":False,
    }


def diagnose_missing(stock_rows):
    """Explain bounded, same-date per-stock completeness; no SQL or writes.

    Every row must be a verified snapshot with explicit booleans and history
    length. Never substitute a missing row with a presumed healthy stock.
    """
    if not isinstance(stock_rows,list) or len(stock_rows)>2000:
        raise ValueError("Bounded stock coverage rows required")
    seen=set()
    reasons={}
    for row in stock_rows:
        if not isinstance(row,dict):
            raise ValueError("Invalid stock completeness row")
        market,stock=row.get("market"),str(row.get("stock_id",""))
        if market not in ("twse","tpex") or not stock.isascii() or not stock.isdigit():
            raise ValueError("Invalid stock key")
        key=market+":"+stock
        if key in seen:
            raise ValueError("Duplicate stock key in completeness snapshot")
        seen.add(key)
        days=row.get("valid_price_days")
        if type(days) is not int or days<0:
            raise ValueError("Missing true valid-price session count")
        for field in ("current_price","technical_current","smc_current","score_current"):
            if type(row.get(field)) is not bool:
                raise ValueError("Missing independently verified flag: "+field)
        notes=[]
        if not row["current_price"]:
            notes.append("NO_LATEST_VALID_PRICE")
        elif days<60:
            notes.append("LESS_THAN_60_VALID_SESSIONS")
        else:
            if not row["technical_current"]:
                notes.append("TECHNICAL_MISSING_ON_LAST_VALID_CLOSE")
            if not row["smc_current"]:
                notes.append("SMC_MISSING_ON_LAST_VALID_CLOSE")
            if not row["score_current"]:
                notes.append("COMPOSITE_MISSING_ON_LAST_VALID_CLOSE")
        if notes:
            reasons[key]=notes
    counts={}
    for values in reasons.values():
        for v in values:
            counts[v]=counts.get(v,0)+1
    return {"examined_stocks":len(seen),
            "incomplete_stocks":len(reasons),
            "reasons":dict(sorted(counts.items())),
            "per_stock":dict(sorted(reasons.items())),
            "writes_enabled":False,
            "missing_data_must_not_be_fabricated":True}
