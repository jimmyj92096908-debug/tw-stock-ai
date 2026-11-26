"""Offline risk-parity overlay for incremental V3 research allocations.

Never increases any approved research weight. Equal-risk reference applies
only to new candidates, not existing holdings. No live trading or order output.
"""
from __future__ import annotations

from math import fsum
from src.v3_prediction_allocation import allocate_research, _symbol
from src.v3_portfolio_risk_research import portfolio_risk_research
from src.v3_probability_calibration import _day


def allocate_with_risk_overlay(*, histories, **allocation_inputs):
    """Intersect individual Kelly/budget caps with a trailing ERC reference.

    Require histories for every positive candidate and existing position;
    missing, stale (more than seven calendar days old), invalid or
    unaligned histories block the research allocation. A candidate positively
    correlated >=0.80 with an existing holding is blocked. For remaining new
    candidates, scale the ERC reference uniformly to respect every original
    cap. This is not constrained whole-account ERC, and does not sell holdings.
    """
    decision = _day(allocation_inputs["decision_date"])
    base = allocate_research(**allocation_inputs)
    existing = {_symbol(r):r for r in allocation_inputs["existing_positions"]
                if r["account_weight"]>0}
    candidates = {r["stock_id"]:r["incremental_weight"] for r in base["candidates"]
                  if r["incremental_weight"]>0}
    market_by_id = {r["stock_id"]:r["market"] for r in allocation_inputs["predictions"]}
    market_by_id.update({s:r["market"] for s,r in existing.items()})
    required = set(existing)|set(candidates)
    result = {"base":base,"weights":{},"blocked_correlated_candidates":[],
              "risk_reference":None,"status":"NO_ELIGIBLE_CANDIDATES",
              "research_incremental_total":0.0,"model_release":"BLOCKED",
              "trading_approved":False,"whole_account_erc_verified":False,
              "history_provenance_verified":False,"calendar_completeness_verified":False}
    if not candidates:
        return result
    if not isinstance(histories,list) or len(required)>50:
        result["status"]="RISK_HISTORY_UNAVAILABLE"
        return result
    by_id={}
    for h in histories:
        s=_symbol(h)
        if s in by_id:
            raise ValueError("Duplicate history")
        by_id[s]=h
    if not required <= set(by_id):
        result["status"]="RISK_HISTORY_UNAVAILABLE"
        return result
    for s in required:
        if by_id[s]["market"]!=market_by_id[s]:
            raise ValueError("History market mismatch")
    # A single security is validated via its own trailing observations,
    # but no cross-security risk parity is claimed.
    selected=[by_id[s] for s in sorted(required)]
    for h in selected:
        rows=h["returns"]
        if not isinstance(rows,list) or not 60<=len(rows)<=1260:
            result["status"]="RISK_HISTORY_UNAVAILABLE"
            return result
        last=_day(rows[-1]["date"])
        if not 0<(decision-last).days<=7:
            result["status"]="RISK_HISTORY_STALE"
            return result
    if len(selected)==1:
        from src.v3_capital_risk_research import _num
        dates=[_day(r["date"]) for r in selected[0]["returns"]]
        values=[_num(r["return"],"daily return",-1,100) for r in selected[0]["returns"]]
        if any(a>=b for a,b in zip(dates,dates[1:])) or max(values)-min(values)<=1e-10:
            raise ValueError("Invalid single-asset risk history")
    else:
        full=portfolio_risk_research(selected,decision_date=decision.isoformat(),
                                     gross_budget=1,cash_budget=1)
        for pair in full["high_positive_correlation_pairs"]:
            a,b=pair["a"][1],pair["b"][1]
            if a in existing and b in candidates:
                result["blocked_correlated_candidates"].append(b)
            if b in existing and a in candidates:
                result["blocked_correlated_candidates"].append(a)
    blocked=set(result["blocked_correlated_candidates"])
    result["blocked_correlated_candidates"]=sorted(blocked)
    caps={s:w for s,w in candidates.items() if s not in blocked}
    if not caps:
        result["status"]="CORRELATION_BLOCKED"
        return result
    if len(caps)==1:
        weights=dict(caps)
        result["status"]="SINGLE_CANDIDATE_NO_ERC"
    else:
        ref=portfolio_risk_research([by_id[s] for s in sorted(caps)],
                                    decision_date=decision.isoformat(),
                                    gross_budget=fsum(caps.values()),
                                    cash_budget=fsum(caps.values()))
        relative={r["stock_id"]:r["relative_risky_weight"] for r in ref["weights"]}
        scale=min(fsum(caps.values()),*(caps[s]/relative[s] for s in caps))
        weights={s:min(caps[s],scale*relative[s]) for s in caps}
        result["risk_reference"]=ref
        result["status"]="INCREMENTAL_ERC_OVERLAY"
    result["weights"]=weights
    result["research_incremental_total"]=fsum(weights.values())
    return result
