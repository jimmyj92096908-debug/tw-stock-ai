"""Offline same-cohort factor-score change and research-evidence drift monitor.

Never compare unlike market cohorts and call it model drift. Stable symbol
intersection must be large enough, timestamps consecutive in *research
snapshots*, and warnings never imply orders or customer notifications.
"""
from __future__ import annotations

from datetime import date
from statistics import median
import math


def _day(x):
    if not isinstance(x,str) or len(x)!=10:
        raise ValueError("Snapshot must have exact YYYY-MM-DD date")
    return date.fromisoformat(x)


def _scores(snapshot):
    if not isinstance(snapshot,dict) or not isinstance(snapshot.get("scores"),list):
        raise ValueError("Verified offline score-snapshot list required")
    day=_day(snapshot.get("date"))
    values={}
    for x in snapshot["scores"]:
        if not isinstance(x,dict) or x.get("market") not in ("twse","tpex"):
            raise ValueError("Invalid score row")
        ident=(x["market"],str(x.get("stock_id","")))
        val=x.get("total_score")
        if not ident[1].isascii() or not ident[1].isdigit() or isinstance(val,bool) or not isinstance(val,(int,float)) or not math.isfinite(val) or not 0<=val<=100:
            raise ValueError("Invalid research score")
        if ident in values:
            raise ValueError("Duplicate symbol within score snapshot")
        values[ident]=float(val)
    return day,values


def score_drift(before,after,*,min_matched=30,
                large_move_threshold=20,
                max_large_move_fraction=.30):
    """Descriptive score instability only, NOT measured model return decay."""
    first,b=_scores(before)
    second,a=_scores(after)
    if second<=first:
        raise ValueError("Snapshots must move forward in time")
    if type(min_matched) is not int or min_matched<5:
        raise ValueError("Invalid minimum matched stock count")
    if isinstance(large_move_threshold,bool) or not isinstance(large_move_threshold,(int,float)) or not 0<large_move_threshold<=100:
        raise ValueError("Invalid large-score movement threshold")
    if isinstance(max_large_move_fraction,bool) or not isinstance(max_large_move_fraction,(int,float)) or not 0<max_large_move_fraction<=1:
        raise ValueError("Invalid movement frequency threshold")
    keys=sorted(set(a)&set(b))
    n=len(keys)
    if n<min_matched:
        return {"status":"INSUFFICIENT_MATCHED_COHORT",
                "matched_stocks":n,"before_stocks":len(b),"after_stocks":len(a),
                "median_absolute_change":None,"large_move_fraction":None,
                "warning":None,"market_context_proven":False,
                "signal_delivery_approved":False,"orders_enabled":False}
    changes=[abs(a[key]-b[key]) for key in keys]
    large=sum(x>=large_move_threshold for x in changes)
    fraction=large/n
    warning=fraction>max_large_move_fraction
    return {"status":"SCORE_SHIFT_REVIEW" if warning else "DESCRIPTIVE_SCORE_STABILITY_OBSERVED",
            "matched_stocks":n,"before_stocks":len(b),"after_stocks":len(a),
            "cohort_retention_from_before":round(n/len(b),6),
            "median_absolute_change":round(median(changes),6),
            "large_move_threshold":large_move_threshold,
            "large_move_fraction":round(fraction,6),"warning":warning,
            "market_context_proven":False,
            "performance_degradation_proven":False,
            "signal_delivery_approved":False,"orders_enabled":False}
