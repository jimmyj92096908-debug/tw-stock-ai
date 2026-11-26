"""Bridge sealed retrospective forecasts to the close-state portfolio simulator.

Only mature, complete supplied cohorts can enter allocation evidence.
Index state and trailing risk histories are external research inputs, not
authenticated market data. No production database or live order access.
"""
from collections import defaultdict
from src.v3_allocated_portfolio_replay import replay_allocated_portfolio
from src.v3_purged_logistic_baseline import _hash, _symbol
from src.v3_probability_calibration import _day
from src.v3_capital_risk_research import _num
from src.v3_market_regime_archive import REGIMES
from src.v3_tuned_five_ensemble import walkforward_tuned_five_ensemble
from src.v3_portfolio_performance_acceptance import portfolio_performance_acceptance


def replay_forecast_archive(sessions, *, archive, regimes, histories_by_date,
                            sector_by_stock, **simulation_parameters):
    if not isinstance(sessions,list) or not sessions or not isinstance(histories_by_date,dict):
        raise ValueError("Invalid replay inputs")
    dates=[_day(s["date"]) for s in sessions]
    cutoff=_day(archive["archive_cutoff"])
    if any(a>=b for a,b in zip(dates,dates[1:])) or dates[-1]>cutoff:
        raise ValueError("Invalid replay dates")
    if not set(histories_by_date)<=set(d.isoformat() for d in dates):
        raise ValueError("Risk history outside replay")
    protocol=archive["protocol_sha256"]
    if (not isinstance(protocol,str) or len(protocol)!=64
            or any(c not in "0123456789abcdef" for c in protocol)):
        raise ValueError("Invalid protocol")
    if _hash(archive["predictions"])!=archive["forecast_sha256"]:
        raise ValueError("Forecast digest mismatch")
    if regimes["index_id"]!="TWSE_TAIEX" or _hash(regimes["states"])!=regimes["states_sha256"]:
        raise ValueError("Regime digest mismatch")
    states={}
    for r in regimes["states"]:
        day=_day(r["signal_date"])
        if (day in states or r["regime"] not in REGIMES or type(r["volatile_heuristic"]) is not bool
                or (r["regime"]!="UNKNOWN_HISTORY" and r["last_available_close"]!=day.isoformat())):
            raise ValueError("Invalid regime state")
        states[day]=r
    def key(r):
        signal=_day(r["signal_date"])
        if not _day(r["training_labels_through"])<signal<cutoff or r["protocol_sha256"]!=protocol:
            raise ValueError("Invalid forecast chronology or protocol")
        _num(r["probability"],"probability",0,1)
        return signal,r["market"],_symbol(r)
    predictions={}
    by_day=defaultdict(list)
    for r in archive["predictions"]:
        k=key(r)
        if k in predictions:
            raise ValueError("Duplicate forecast")
        predictions[k]=r
        by_day[k[0]].append(k)
    outcome_keys=set()
    cohorts=defaultdict(list)
    for r in archive["mature_outcomes"]:
        k=key(r)
        p=predictions.get(k)
        if k in outcome_keys or p is None or any(r[f]!=p[f] for f in ("probability","training_labels_through")):
            raise ValueError("Outcome does not match unique forecast")
        outcome_keys.add(k)
        ex,available,cohort=map(_day,(r["exit_date"],r["label_available_date"],r["cohort_available_date"]))
        if not k[0]<ex<=available<=cohort<cutoff:
            raise ValueError("Invalid outcome chronology")
        _num(r["net_return"],"net return",-1,1000)
        cohorts[k[0]].append((cohort,r))
    mature=[]
    for day,records in cohorts.items():
        if (len(records)!=len(by_day[day]) or len({a for a,_ in records})!=1
                or records[0][0]!=max(_day(r["label_available_date"]) for _,r in records)):
            raise ValueError("Partial or inconsistent outcome cohort")
        mature.append((records[0][0],day,[r for _,r in records]))
    mature.sort(key=lambda r:(r[0],r[1]))
    # Preflight decision coverage before any simulated account mutation.
    for day in set(dates)&set(by_day):
        if day not in states:
            raise ValueError("Missing decision-date regime")
        for k in by_day[day]:
            p=predictions[k]
            state=states[day]
            if any(f in p and p[f]!=state[f] for f in ("regime","volatile_heuristic")):
                raise ValueError("Forecast regime mismatch")
            if k[2] not in sector_by_stock or not isinstance(sector_by_stock[k[2]],str) or not sector_by_stock[k[2]].strip():
                raise ValueError("Missing sector")
    pointer=0
    history=[]
    evidence_log=[]
    def provider(value):
        nonlocal pointer
        day=_day(value)
        while pointer<len(mature) and mature[pointer][0]<day:
            history.extend(mature[pointer][2])
            pointer+=1
        if day not in by_day:
            return None
        state=states[day]
        rows=[dict(predictions[k],sector=sector_by_stock[k[2]],
                   stop_loss_fraction=simulation_parameters.get("stop_fraction",.05))
              for k in sorted(by_day[day])]
        evidence_log.append(dict(date=value,forecast_count=len(rows),mature_outcome_count=len(history),
                                 mature_signal_dates=pointer,regime=state["regime"],
                                 latest_cohort_available=mature[pointer-1][0].isoformat() if pointer else None))
        return dict(predictions=rows,outcomes=list(history),
                    regime=state["regime"],volatile_heuristic=state["volatile_heuristic"],
                    histories=histories_by_date.get(value,[]))
    result=replay_allocated_portfolio(sessions,daily_evidence={},evidence_provider=provider,
                    protocol_sha256=protocol,sector_by_stock=sector_by_stock,**simulation_parameters)
    result.update(forecast_archive_integrated=True,forecast_sha256=archive["forecast_sha256"],
                  evidence_log=evidence_log,evidence_log_sha256=_hash(evidence_log),
                  label_execution_parity_verified=False,source_provenance_verified=False,
                  pristine_holdout_verified=False,model_release="BLOCKED",trading_approved=False)
    return result


def run_tuned_portfolio_research(*,sessions,index_rows,histories_by_date,
                                 sector_by_stock,training_inputs,simulation_parameters=None):
    training=walkforward_tuned_five_ensemble(index_rows=index_rows,**training_inputs)
    if training["ensemble"] is None:
        return {"status":"INSUFFICIENT_TRAINING_EVIDENCE","training":training,"replay":None,
                "model_release":"BLOCKED","trading_approved":False}
    replay=replay_forecast_archive(sessions,archive=training["ensemble"],
               regimes=training["regime_archive"],histories_by_date=histories_by_date,
               sector_by_stock=sector_by_stock,**(simulation_parameters or {}))
    replay["walkforward_training_integrated"]=True
    performance=portfolio_performance_acceptance(replay)
    return {"status":"RETROSPECTIVE_TUNED_PORTFOLIO_RESEARCH","training":training,"replay":replay,"performance":performance,
            "model_release":"BLOCKED","trading_approved":False}
