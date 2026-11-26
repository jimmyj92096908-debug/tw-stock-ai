"""Offline V3 prediction-to-incremental-allocation research bridge.

Consumes externally supplied frozen predictions and mature out-of-fold
outcomes for one declared strategy protocol. No model training, source
authentication, live approval or executable order generation.
"""
from __future__ import annotations

import re
from math import fsum
from src.v3_capital_risk_research import _num, research_weight, outcome_diagnostics
from src.v3_probability_calibration import _day, fixed_bin_calibration
from src.v3_win_rate_market_budget import block_win_rate_research, incremental_market_budget


def _symbol(row):
    s = row["stock_id"]
    if (row["market"] not in ("TWSE","TPEx") or not isinstance(s,str)
            or not s.isascii() or not s.isdigit() or s=="1589"
            or row.get("currently_listed") is not True):
        raise ValueError("Invalid or excluded instrument")
    return s


def allocate_research(*, decision_date, protocol_sha256, predictions, outcomes,
                      existing_positions, cash_available, drawdown, regime,
                      volatile_heuristic, sector_limit=0.25, total_stop_risk_limit=0.02):
    """Return incremental hypothetical account weights, never full target maps.

    All records must declare the same frozen strategy protocol (features,
    label, costs, horizon, training recipe); the hash is only a matching key,
    not proof. Per-bin historical point and block sensitivity estimates must
    both clear 80%; net average payoff must clear 2. Existing positions are
    not resized or sold. New candidates are ordered by conservative estimate
    then raw probability, then ticker. Caller must verify sector mapping,
    available cash, current stop exposure and data provenance independently.
    """
    cutoff = _day(decision_date)
    if not isinstance(protocol_sha256,str) or re.fullmatch("[0-9a-f]{64}",protocol_sha256) is None:
        raise ValueError("Invalid strategy protocol hash")
    if not isinstance(predictions,list) or len(predictions)>2000 or not isinstance(outcomes,list) or len(outcomes)>200000 or not isinstance(existing_positions,list):
        raise ValueError("Invalid research inputs")
    cash = _num(cash_available,"cash",0,1)
    dd = _num(drawdown,"drawdown",0,1)
    sector_cap = _num(sector_limit,"sector cap",0,1)
    risk_cap = _num(total_stop_risk_limit,"stop risk cap",0,1)
    seen, sectors, weights, risks = set(), {}, [], []
    def sector(row):
        x = row["sector"]
        if not isinstance(x,str) or not x.strip() or x != x.strip():
            raise ValueError("Missing canonical sector")
        return x
    for row in existing_positions:
        s = _symbol(row)
        if s in seen:
            raise ValueError("Duplicate existing stock")
        seen.add(s)
        w = _num(row["account_weight"],"existing weight",0,1)
        risk = _num(row["remaining_stop_risk_fraction"],"existing stop risk",0,1)
        k = sector(row)
        sectors[k] = sectors.get(k,0.0)+w
        weights.append(w)
        risks.append(w*risk)
    gross, used_risk = fsum(weights), fsum(risks)
    market = incremental_market_budget(regime=regime,volatile_heuristic=volatile_heuristic,
                existing_gross_exposure=gross,cash_available=cash,drawdown=dd)
    room = market["incremental_exposure_budget"]
    risk_room = max(0.0,risk_cap-used_risk)
    history_bins = [[] for _ in range(10)]
    for row in outcomes:
        _symbol(row)
        if row.get("protocol_sha256") != protocol_sha256:
            raise ValueError("Mixed historical strategy protocols")
        p = _num(row["probability"],"historical probability",0,1)
        history_bins[min(9,int(p*10))].append(row)
    # Validate the complete history, including bins not used by predictions.
    fixed_bin_calibration(outcomes,decision_date=decision_date,probability=0.8)
    evidence = {}
    def assess(p):
        b = min(9,int(p*10))
        if b not in evidence:
            rows = history_bins[b]
            cal = fixed_bin_calibration(rows,decision_date=decision_date,probability=p)
            boot = block_win_rate_research(rows,decision_date=decision_date) if rows else None
            diag = outcome_diagnostics([r["net_return"] for r in rows]) if rows else None
            lower = boot["sensitivity_lower_estimate"] if boot else None
            payoff = diag["net_payoff_ratio"] if diag else None
            evidence[b] = {"observations":cal["observations"],
                           "signal_dates":cal["distinct_signal_dates"],
                           "point_win_rate":cal["empirical_net_win_rate"],
                           "block_sensitivity_lower":lower,"net_payoff_ratio":payoff,
                           "eligible": bool(cal["descriptive_rate_available"] and boot
                               and boot["research_80pct_screen"] and diag
                               and diag["point_targets_met"])}
        return evidence[b]
    queue, results, candidates = [], [], set()
    for row in predictions:
        s = _symbol(row)
        if s in candidates:
            raise ValueError("Duplicate candidate")
        candidates.add(s)
        if (row.get("protocol_sha256")!=protocol_sha256
                or _day(row["signal_date"])!=cutoff
                or _day(row["training_labels_through"])>=cutoff):
            raise ValueError("Prediction protocol or chronology mismatch")
        p = _num(row["probability"],"probability",0,1)
        stop = _num(row["stop_loss_fraction"],"cost-inclusive stop risk",0.0001,1)
        k = sector(row)
        if s in seen or p<0.8:
            results.append({"stock_id":s,"incremental_weight":0.0,
                            "reason":"EXISTING_POSITION" if s in seen else "LOW_PREDICTION"})
            continue
        e = assess(p)
        if not e["eligible"]:
            results.append({"stock_id":s,"incremental_weight":0.0,"reason":"INSUFFICIENT_BIN_EVIDENCE"})
            continue
        conservative = min(p,e["block_sensitivity_lower"])
        queue.append((conservative,p,s,k,stop,e["net_payoff_ratio"]))
    for p,raw,s,k,stop,payoff in sorted(queue,key=lambda x:(-x[0],-x[1],x[2])):
        w = research_weight(conservative_probability=p,net_payoff_ratio=min(payoff,100),
                stop_loss_fraction=stop,market_exposure_remaining=room,
                sector_exposure_remaining=max(0.0,sector_cap-sectors.get(k,0.0)),
                cash_available=cash,portfolio_risk_remaining=risk_room,drawdown=dd)
        room = max(0.0,room-w)
        cash = max(0.0,cash-w)
        risk_room = max(0.0,risk_room-w*stop)
        sectors[k] = sectors.get(k,0.0)+w
        results.append({"stock_id":s,"incremental_weight":w,
                        "reason":"RESEARCH_ONLY" if w>0 else "BUDGET_EXHAUSTED"})
    return {"candidates":sorted(results,key=lambda x:x["stock_id"]),
            "bin_evidence":evidence,"remaining_cash_budget":cash,
            "remaining_market_budget":room,"remaining_stop_risk_budget":risk_room,
            "research_incremental_total":fsum(r["incremental_weight"] for r in results),
            "source_provenance_verified":False,"confidence_bound_verified":False,
            "risk_parity_integrated":False,"portfolio_ledger_integrated":False,
            "survivorship_bias_possible":True,"model_release":"BLOCKED",
            "trading_approved":False}
