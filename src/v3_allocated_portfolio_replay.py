"""Offline V3 daily research replay using actual simulated close-state budgets.

Predictions, outcomes, regime and risk histories are externally supplied for
each decision date. No data authentication, training or live trade approval.
"""
from __future__ import annotations

from src.v3_portfolio_accounting import simulate_portfolio
from src.v3_risk_allocation_overlay import allocate_with_risk_overlay
from src.v3_capital_risk_research import _num
from src.v3_probability_calibration import _day


def replay_allocated_portfolio(sessions, *, daily_evidence, protocol_sha256,
                               sector_by_stock, starting_cash=1000000,
                               lot_size=1000, commission=0.001425,
                               sell_tax=0.003, slippage=0.001,
                               stop_fraction=0.05, profit_fraction=0.10,
                               trailing_fraction=0.05, corporate_action_mode=False):
    """Run allocation at close, freeze incremental dollar budgets for next open.

    No resize or forced sell of existing holdings based on allocation alone.
    Pending exits block all new allocation. Daily evidence must already be
    point-in-time prepared; supplied regime and liquidity remain unverified.
    Close-state sector, market and stop budgets may drift after opening gaps.
    """
    if not isinstance(sessions,list) or not isinstance(daily_evidence,dict) or not isinstance(sector_by_stock,dict):
        raise ValueError("Invalid replay input")
    dates=[_day(s["date"]).isoformat() for s in sessions]
    if not set(daily_evidence)<=set(dates):
        raise ValueError("Evidence outside replay dates")
    fee,tax,slip=(_num(v,"cost",0,0.1) for v in (commission,sell_tax,slippage))
    stop=_num(stop_fraction,"stop",0.0001,0.99)
    # Avoid cancellation at exact lot boundaries (zero costs => exact stop).
    exit_ratio=(1-slip)*(1-fee-tax)/(1+fee)
    cost_stop=stop+(1-stop)*(1-exit_ratio)
    diagnostics=[]
    def allocate(snapshot):
        day=snapshot["date"]
        evidence=daily_evidence.get(day)
        if evidence is None or any(p["pending_exit"] for p in snapshot["positions"]):
            diagnostics.append({"date":day,"status":"NO_EVIDENCE_OR_PENDING_EXIT"})
            return {}
        existing=[dict(p,sector=sector_by_stock[p["stock_id"]],currently_listed=True)
                  for p in snapshot["positions"]]
        predictions=[]
        for row in evidence["predictions"]:
            if row["sector"]!=sector_by_stock[row["stock_id"]]:
                raise ValueError("Sector mapping mismatch")
            p=dict(row)
            p["stop_loss_fraction"]=max(cost_stop,_num(row["stop_loss_fraction"],"declared stop",0.0001,1))
            predictions.append(p)
        result=allocate_with_risk_overlay(
            decision_date=day,protocol_sha256=protocol_sha256,
            predictions=predictions,outcomes=evidence["outcomes"],
            existing_positions=existing,cash_available=snapshot["cash_available"],
            drawdown=snapshot["drawdown"],regime=evidence["regime"],
            volatile_heuristic=evidence["volatile_heuristic"],histories=evidence["histories"])
        diagnostics.append({"date":day,"status":result["status"],
                            "weights":dict(result["weights"]),
                            "bin_evidence":result["base"]["bin_evidence"]})
        return result["weights"]
    report=simulate_portfolio(sessions,starting_cash=starting_cash,lot_size=lot_size,
              commission=fee,sell_tax=tax,slippage=slip,stop_fraction=stop,
              profit_fraction=profit_fraction,trailing_fraction=trailing_fraction,
              corporate_action_mode=corporate_action_mode,exit_stress_mode=True,
              close_allocator=allocate)
    report.update(allocation_diagnostics=diagnostics,real_model_trained=False,
                  walkforward_training_integrated=False,opening_sector_risk_rechecked=False,
                  model_release="BLOCKED",trading_approved=False)
    return report
