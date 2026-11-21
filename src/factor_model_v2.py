"""Conservative adjusted-price model validation with a predeclared holdout.

Scores are fixed at signal close. All ranking decisions happen BEFORE reading
future labels. Missing forward adjusted prices invalidate a whole cohort,
rather than improving the rank by deleting losing/missing stocks.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from statistics import mean
import math
from src.current_official_listing import CURRENT_OFFICIAL_LISTED_CTE

MODEL_VERSION = "composite-rank-v2-adjusted"
TOP_FRACTION = 0.20
MIN_UNIVERSE = 5
MIN_COVERAGE = 0.50
ROUND_TRIP_COST_BPS = 30  # research-only illustrative estimate; not broker quote

# Anchor the lead offset on actual RAW closing sessions, then fetch adjustment
# from corresponding dates. A missing adjusted bar never shifts the window.
# A future verified corporate-action change can revise the adjusted price
# history: do not treat this research series as an immutable historical feed.
ADJUSTED_EVALUATION_SQL = f"""{CURRENT_OFFICIAL_LISTED_CTE}, bars AS (
 SELECT p.market,p.stock_id,p.trade_date,
        p.close AS raw_close,a.close AS adjusted_close,
        LEAD(p.trade_date,1) OVER w AS entry_date,
        LEAD(p.trade_date,6) OVER w AS exit_date,
        LEAD(a.close,1) OVER w AS entry_close,
        LEAD(a.close,6) OVER w AS exit_close
 FROM public.daily_prices p
 LEFT JOIN public.daily_adjusted_prices a
   ON a.market=p.market AND a.stock_id=p.stock_id
   AND a.trade_date=p.trade_date
 WHERE p.close IS NOT NULL AND p.close>0
 WINDOW w AS (PARTITION BY p.market,p.stock_id ORDER BY p.trade_date)
)
SELECT s.market,s.stock_id,s.as_of_date,s.total_score,s.coverage_weight,
       b.raw_close,b.adjusted_close,b.entry_date,b.exit_date,
       b.entry_close,b.exit_close
FROM public.daily_composite_scores s
JOIN official_current_listed active
 ON active.market=s.market AND active.stock_id=s.stock_id
JOIN public.stock_master sm
 ON sm.market=s.market AND sm.stock_id=s.stock_id
JOIN bars b ON b.market=s.market AND b.stock_id=s.stock_id
 AND b.trade_date=s.as_of_date
WHERE s.total_score IS NOT NULL
 AND s.as_of_date >= %s AND s.as_of_date <= %s
 AND s.stock_id <> '1808'
ORDER BY s.as_of_date,s.market,s.stock_id
"""

def _real(x):
    try:
        value=float(x)
    except (ValueError,TypeError,OverflowError):
        return None
    return value if math.isfinite(value) else None


def evaluate_adjusted(rows, *, holdout_start="2026-10-01",
                      round_trip_cost_bps=ROUND_TRIP_COST_BPS,
                      min_universe=MIN_UNIVERSE):
    if not (0 <= round_trip_cost_bps <= 1000) or min_universe < 2:
        raise ValueError("Invalid model evaluation parameters")
    if date.fromisoformat(holdout_start).isoformat() != holdout_start:
        raise ValueError("holdout_start must be YYYY-MM-DD")
    days=defaultdict(list)
    seen=set()
    exclusions={"duplicate":0,"invalid_signal":0,"insufficient_factor_coverage":0,
                "missing_adjusted_signal_close":0}
    for x in rows:
        try:
            day=x["as_of_date"]
            day=day.isoformat() if isinstance(day,date) else str(day)[:10]
            date.fromisoformat(day)
            market=x["market"]
            code=x["stock_id"]
            key=(market,code,day)
            if key in seen:
                exclusions["duplicate"]+=1
                continue
            seen.add(key)
            score=_real(x["total_score"])
            coverage=_real(x["coverage_weight"])
            adj_signal=_real(x["adjusted_close"])
            if market not in ("twse","tpex") or code=="1808" or score is None or not 0<=score<=100:
                exclusions["invalid_signal"]+=1
                continue
            if coverage is None or not MIN_COVERAGE<=coverage<=1:
                exclusions["insufficient_factor_coverage"]+=1
                continue
            if adj_signal is None or adj_signal<=0:
                exclusions["missing_adjusted_signal_close"]+=1
                continue
            entry=_real(x.get("entry_close"))
            exit_=_real(x.get("exit_close"))
            exit_date=x.get("exit_date")
            exit_date=exit_date.isoformat() if isinstance(exit_date,date) else (
                str(exit_date)[:10] if exit_date is not None else None)
            days[day].append((score,coverage,market,code,entry,exit_,exit_date))
        except (ValueError,TypeError,KeyError):
            exclusions["invalid_signal"]+=1
    periods=[]
    skipped={"small_universe":0,"incomplete_forward_label":0,"development_holdout_boundary":0}
    label_missing=0
    for day, candidates in sorted(days.items()):
        if len(candidates)<min_universe:
            skipped["small_universe"]+=1
            continue
        ranked=sorted(candidates,key=lambda t:(-t[0],-t[1],t[2],t[3]))
        count=max(1,math.ceil(len(ranked)*TOP_FRACTION))
        top=ranked[:count]
        # The selected list is frozen before any examination of future returns.
        missing=sum(t[4] is None or t[5] is None or t[4]<=0 or t[5]<=0 for t in ranked)
        label_missing+=missing
        if missing:
            skipped["incomplete_forward_label"]+=1
            continue
        # Purge development labels that extend into the holdout period. A
        # validation result must not see future prices from its holdout set.
        if day < holdout_start and any(t[6] is None or t[6] >= holdout_start for t in ranked):
            skipped["development_holdout_boundary"]+=1
            continue
        returns=[t[5]/t[4]-1 for t in ranked]
        selected=returns[:count]
        cost=round_trip_cost_bps / 10000
        gross=mean(selected)
        benchmark=mean(returns)
        split="holdout" if day>=holdout_start else "development"
        periods.append({
            "as_of_date":day,"split":split,"universe":len(ranked),"selected":count,
            "top_gross":round(gross,8),
            "top_net_after_assumed_cost":round(gross-cost,8),
            "universe_gross":round(benchmark,8),
            "gross_excess":round(gross-benchmark,8),
            "net_excess_vs_gross_universe":round(gross-cost-benchmark,8)
        })
    def summary(group):
        sample=[p for p in periods if p["split"]==group]
        return {"cohorts":len(sample),
                "mean_gross_excess":round(mean(x["gross_excess"] for x in sample),8) if sample else None,
                "mean_net_excess":round(mean(x["net_excess_vs_gross_universe"] for x in sample),8) if sample else None,
                "positive_net_excess_fraction":round(mean(x["net_excess_vs_gross_universe"]>0 for x in sample),6) if sample else None}
    return {
        "model_version":MODEL_VERSION,"holdout_start":holdout_start,
        "round_trip_cost_bps_assumption":round_trip_cost_bps,
        "selection_rule":"fixed top 20% by pre-existing score and coverage",
        "label_rule":"raw sessions t+1 and t+6, adjusted endpoint prices",
        "development":summary("development"),"holdout":summary("holdout"),
        "cohorts":periods,"excluded":exclusions,"skipped_dates":skipped,
        "missing_forward_labels_in_large_cohorts":label_missing,
        "research_only":True,"production_validated":False,
        "warnings":["No trade simulation or independently verified executable prices",
                    "Overlapping 5-session cohorts; not independent observations",
                    "Survivorship, stock availability and corporate-action revision bias",
                    "Assumed illustrative fixed cost, not a confirmed Taiwan broker fee schedule",
                    "A negative holdout result cannot be tuned away using the same holdout"],
    }
