"""Point-in-time market-regime archive for offline V3 research.

Use declared official index closes only, no arbitrary equity proxy.
Dates alone do not establish publication time, immutable vintage or
calendar completeness. Unknown/stale data never opens exposure.
"""
from __future__ import annotations

from collections import defaultdict
from math import fsum
from src.research_risk import market_regime
from src.v3_probability_calibration import _day
from src.v3_capital_risk_research import _num
from src.v3_purged_logistic_baseline import _hash

INDEX_ID="TWSE_TAIEX"
REGIMES=("UPTREND","DOWNTREND","RANGE_OR_TRANSITION","UNKNOWN_HISTORY")


def market_regime_archive(*,index_rows,decision_dates):
    """Classify each close decision from available trailing index history.

    Require current session close and 80 observations; do not fill gaps.
    Require explicit source and availability declarations, not authentication.
    Volatility >=3% per session is a separate flag from trend direction.
    """
    if (not isinstance(index_rows,list) or len(index_rows)>5000
            or not isinstance(decision_dates,list) or not 1<=len(decision_dates)<=1260):
        raise ValueError("Invalid bounded regime inputs")
    dates=[_day(d) for d in decision_dates]
    if any(a>=b for a,b in zip(dates,dates[1:])):
        raise ValueError("Unordered decision dates")
    seen=set()
    rows=[]
    for r in index_rows:
        day,available=map(_day,(r["date"],r["available_date"]))
        if (day in seen or available<day or r["index_id"]!=INDEX_ID
                or r.get("source_declared_official") is not True
                or r.get("vintage_declared") is not True):
            raise ValueError("Invalid index identity, vintage or chronology")
        seen.add(day)
        rows.append((day,available,_num(r["close"],"index close",1e-9,1e9)))
    rows.sort()
    states=[]
    for day in dates:
        eligible=[{"date":d.isoformat(),"close":v} for d,a,v in rows if d<=day and a<=day]
        if not eligible or eligible[-1]["date"]!=day.isoformat():
            state={"regime":"UNKNOWN_HISTORY","volatile_heuristic":False,"reason":"CURRENT_CLOSE_UNAVAILABLE"}
        else:
            state=market_regime(eligible,as_of_date=day.isoformat())
            state["volatile_heuristic"]=state.get("volatile_heuristic",False)
            if state["regime"]=="UNKNOWN_HISTORY":
                state["reason"]="INSUFFICIENT_TRAILING_HISTORY"
        states.append({"signal_date":day.isoformat(),"regime":state["regime"],
                       "volatile_heuristic":state["volatile_heuristic"],
                       "observations":len(eligible),"last_available_close":eligible[-1]["date"] if eligible else None,
                       "index_input_sha256":_hash(eligible),
                       "reason":state.get("reason")})
    return {"index_id":INDEX_ID,"states":states,"states_sha256":_hash(states),
            "source_provenance_verified":False,"calendar_completeness_verified":False,
            "intraday_publication_verified":False,"model_release":"BLOCKED","trading_approved":False}


def regime_outcome_diagnostics(*,archive,regimes,decision_date):
    """Report mature forecast metrics by trend and volatility, never tune here."""
    cutoff=_day(decision_date)
    if cutoff>_day(archive["archive_cutoff"]):
        raise ValueError("Beyond archive cutoff")
    states={}
    for r in regimes["states"]:
        day=_day(r["signal_date"])
        if day in states or r["regime"] not in REGIMES or type(r["volatile_heuristic"]) is not bool:
            raise ValueError("Invalid regime state")
        states[day]=(r["regime"],r["volatile_heuristic"])
    groups=defaultdict(list)
    seen=set()
    for r in archive["mature_outcomes"]:
        trained,signal,exit_day,available,cohort=map(_day,(r["training_labels_through"],
             r["signal_date"],r["exit_date"],r["label_available_date"],r["cohort_available_date"]))
        if not trained<signal<exit_day<=available<=cohort or r["protocol_sha256"]!=archive["protocol_sha256"]:
            raise ValueError("Invalid forecast outcome")
        key=(signal,r["market"],r["stock_id"])
        if key in seen:
            raise ValueError("Duplicate outcome")
        seen.add(key)
        if cohort>=cutoff:
            continue
        if signal not in states:
            raise ValueError("Missing signal regime")
        p=_num(r["probability"],"probability",0,1)
        net=_num(r["net_return"],"net return",-1,1000)
        groups[states[signal]].append((signal,p,net))
    results=[]
    for (regime,volatile),rows in sorted(groups.items()):
        chosen=[r for r in rows if r[1]>=.8]
        results.append(dict(regime=regime,volatile_heuristic=volatile,
                  observations=len(rows),signal_dates=len({r[0] for r in rows}),
                  brier=fsum((p-int(n>0))**2 for _,p,n in rows)/len(rows),
                  screened_count=len(chosen),screened_win_rate=sum(n>0 for _,_,n in chosen)/len(chosen) if chosen else None))
    return {"groups":results,"decision_date":decision_date,"regime_weights_selected":False,
            "source_provenance_verified":False,"independent_holdout_verified":False,
            "model_release":"BLOCKED","trading_approved":False}
