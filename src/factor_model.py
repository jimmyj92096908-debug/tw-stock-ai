"""Deterministic point-in-time composite stock ranking model.

This is an inspectable rule-based research model, NOT a trained predictor or
a trading system. Only publish symbols with a matching same-day real closing
price and the already-calculated verified composite factor coverage.
"""
from __future__ import annotations
from datetime import date, datetime
import math

MODEL_VERSION = "composite-rank-v1"
MIN_COVERAGE = 0.50

LATEST_RANKING_SQL = """
WITH latest AS (
 SELECT MAX(as_of_date) AS last_score_date
 FROM public.daily_composite_scores WHERE total_score IS NOT NULL
)
SELECT s.market,s.stock_id,sm.stock_name,s.as_of_date,
       s.total_score,s.coverage_weight,p.close
FROM latest l
JOIN public.daily_composite_scores s
 ON s.as_of_date=l.last_score_date
JOIN public.daily_prices p
 ON p.market=s.market AND p.stock_id=s.stock_id
 AND p.trade_date=s.as_of_date
JOIN public.stock_master sm
 ON sm.market=s.market AND sm.stock_id=s.stock_id
WHERE s.total_score IS NOT NULL AND s.coverage_weight >= %s
  AND p.close IS NOT NULL AND p.close > 0 AND s.stock_id <> '1808'
ORDER BY s.total_score DESC, s.coverage_weight DESC,
         s.market,s.stock_id
"""

def ranking(rows, *, limit=10):
    if not isinstance(limit,int) or isinstance(limit,bool) or not 1<=limit<=100:
        raise ValueError("limit must be an integer 1..100")
    approved=[]
    seen=set()
    dates=set()
    for raw in rows:
        try:
            score=float(raw["total_score"])
            coverage=float(raw["coverage_weight"])
            close=float(raw["close"])
            market=str(raw["market"])
            stock_id=str(raw["stock_id"])
            day=raw["as_of_date"]
            day=day.date().isoformat() if isinstance(day,datetime) else (
                day.isoformat() if isinstance(day,date) else str(day)[:10])
        except (KeyError,ValueError,TypeError):
            continue
        if (not all(math.isfinite(x) for x in (score,coverage,close)) or
                not 0<=score<=100 or not MIN_COVERAGE<=coverage<=1 or
                close<=0 or stock_id=="1808" or market not in ("twse","tpex")):
            continue
        key=(market,stock_id,day)
        if key in seen:
            continue
        seen.add(key)
        dates.add(day)
        approved.append((score,coverage,market,stock_id,day,close,str(raw.get("stock_name") or "")))
    # Never mix different score dates and falsely present as same-day ranking.
    if len(dates)>1:
        raise ValueError("cross-date ranking is not permitted")
    ranked=sorted(approved,key=lambda x:(-x[0],-x[1],x[2],x[3]))
    return {
        "model_version": MODEL_VERSION,
        "signal_date": next(iter(dates),None),
        "eligible_universe": len(ranked),
        "ranked": [
            {"rank":i,"market":x[2],"stock_id":x[3],"stock_name":x[6],
             "score":x[0],"coverage":x[1],"signal_close":x[5]}
            for i,x in enumerate(ranked[:limit],1)
        ],
        "research_only":True,
        "not_a_trading_signal":True,
    }
