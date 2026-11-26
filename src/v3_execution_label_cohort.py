"""Execution-aligned label research using the very same portfolio simulator.

Each candidate is an isolated hypothetical account, not a simultaneous
portfolio. A whole supplied signal cohort abstains if any candidate fails
to enter or close within the fixed observation horizon. This prevents
silently dropping unresolved labels from a cohort. No forced terminal
liquidation, data authentication, or production access.
"""
from __future__ import annotations

from src.v3_portfolio_accounting import simulate_portfolio
from src.v3_purged_logistic_baseline import _hash, _symbol
from src.v3_probability_calibration import _day
from src.v3_capital_risk_research import _num


def execution_label_cohort(*, candidates, sessions, label_available_date,
                           horizon_sessions=20, starting_cash=1000000,
                           lot_size=1000, commission=.001425, sell_tax=.003,
                           slippage=.001, stop_fraction=.05, profit_fraction=.10,
                           trailing_fraction=.05, corporate_action_mode=False):
    """Generate all-or-none labels via the same next-open/exit accounting.

    sessions contains the signal close plus exactly horizon_sessions later
    sessions, in chronological order. Availability is no earlier than the
    last supplied session, even when the position closed sooner. All source
    availability and calendar declarations still require independent proof.
    """
    if type(horizon_sessions) is not int or not 2<=horizon_sessions<=60:
        raise ValueError("Invalid fixed observation horizon")
    if not isinstance(sessions,list) or len(sessions)!=horizon_sessions+1:
        raise ValueError("Require exact signal plus horizon sessions")
    if not isinstance(candidates,list) or not 1<=len(candidates)<=2000:
        raise ValueError("Invalid candidate cohort")
    days=[_day(s["date"]) for s in sessions]
    available=_day(label_available_date)
    if any(a>=b for a,b in zip(days,days[1:])) or available<days[-1]:
        raise ValueError("Invalid label chronology")
    if any(s.get("close_targets") is not None for s in sessions):
        raise ValueError("External targets not allowed")
    if type(corporate_action_mode) is not bool:
        raise ValueError("Invalid action mode")
    settings=dict(starting_cash=_num(starting_cash,"cash",1,1e12),
                  lot_size=lot_size,commission=_num(commission,"fee",0,.1),
                  sell_tax=_num(sell_tax,"tax",0,.1),slippage=_num(slippage,"slip",0,.1),
                  stop_fraction=_num(stop_fraction,"stop",.0001,.99),
                  profit_fraction=_num(profit_fraction,"profit",.0001,10),
                  trailing_fraction=_num(trailing_fraction,"trail",.0001,.99),
                  corporate_action_mode=corporate_action_mode,exit_stress_mode=True)
    if type(lot_size) is not int or lot_size not in (1,1000):
        raise ValueError("Invalid lot size")
    protocol=_hash(dict(recipe="isolated_portfolio_execution_label_v1",
                       horizon_sessions=horizon_sessions,entry_weight=.1,
                       availability="no_earlier_than_horizon_end",parameters=settings))
    seen=set()
    labeled=[]
    diagnostics=[]
    fields=("stock_id","market","currently_listed","signal_date",
            "feature_available_date","feature_vintage_declared","features")
    for candidate in sorted(candidates,key=lambda r:r["stock_id"]):
        stock=_symbol(candidate)
        if (stock in seen or _day(candidate["signal_date"])!=days[0]
                or _day(candidate["feature_available_date"])>days[0]
                or candidate["feature_vintage_declared"] is not True
                or set(candidate)&{"net_return","exit_date","label_available_date","label","target","future_return"}):
            raise ValueError("Invalid or outcome-bearing candidate")
        seen.add(stock)
        isolated=[]
        for session in sessions:
            if stock not in session["bars"] or session["bars"][stock]["market"]!=candidate["market"]:
                raise ValueError("Missing or mismatched candidate bar")
            row={"date":session["date"],"bars":{stock:session["bars"][stock]}}
            if corporate_action_mode:
                if "corporate_actions" not in session:
                    raise ValueError("Missing action list")
                row["corporate_actions"]=[a for a in session["corporate_actions"] if a["stock_id"]==stock]
            elif any(a["stock_id"]==stock for a in session.get("corporate_actions",[])):
                raise ValueError("Corporate action mode disabled")
            isolated.append(row)
        def allocate(snapshot):
            return {stock:.1} if snapshot["date"]==days[0].isoformat() else {}
        replay=simulate_portfolio(isolated,close_allocator=allocate,**settings)
        buys=[f for f in replay["fills"] if f["side"]=="BUY"]
        closed=replay["closed_position_episodes"]
        status="CLOSED" if len(buys)==1 and len(closed)==1 and replay["open_position_count"]==0 else (
               "NO_ENTRY" if not buys else "UNRESOLVED_EXIT")
        diagnostics.append(dict(stock_id=stock,status=status,fill_count=len(replay["fills"])))
        if status!="CLOSED":
            continue
        if buys[0]["date"]!=days[1].isoformat() or closed[0]["entry_date"]!=buys[0]["date"]:
            raise AssertionError("Unexpected execution chronology")
        labeled.append(dict({k:candidate[k] for k in fields},
                       exit_date=closed[0]["exit_date"],label_available_date=available.isoformat(),
                       label_protocol_sha256=protocol,net_return=closed[0]["net_return"]))
    complete=len(labeled)==len(candidates)
    return {"status":"COMPLETE_SUPPLIED_COHORT" if complete else "INCOMPLETE_COHORT_BLOCKED",
            "label_protocol_sha256":protocol,"training_rows":labeled if complete else [],
            "candidate_count":len(candidates),"closed_candidate_count":len(labeled),
            "diagnostics":diagnostics,"shared_execution_engine":True,
            "isolated_account_labels":True,"whole_portfolio_execution_parity_verified":False,
            "source_provenance_verified":False,"calendar_completeness_verified":False,
            "model_release":"BLOCKED","trading_approved":False}
