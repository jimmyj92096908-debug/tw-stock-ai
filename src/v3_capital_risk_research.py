"""Offline V3 research sizing and outcome diagnostics, not trading approval.

All rates are decimal fractions. Inputs must be frozen before outcomes.
This module does not independently authenticate input evidence.
"""
from __future__ import annotations

import math
from statistics import mean


def _num(x, name, lo, hi):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not lo <= x <= hi:
        raise ValueError("Invalid " + name)
    return float(x)


def research_weight(*, conservative_probability, net_payoff_ratio, stop_loss_fraction,
                    market_exposure_remaining, sector_exposure_remaining,
                    cash_available, portfolio_risk_remaining, drawdown):
    """Long-only proposed research weight; never executable position sizing.

    Probability must be externally calibrated, payoff ratio net of costs.
    Limits: quarter Kelly, 10% single name, 0.5% account stop risk.
    At 10% account drawdown, no new exposure. Remaining budgets must account
    for all existing positions and are supplied by the caller, not inferred.
    Stops are estimates; gaps and liquidity can exceed them.
    """
    p = _num(conservative_probability, "probability", 0, 1)
    b = _num(net_payoff_ratio, "payoff", 0.01, 100)
    s = _num(stop_loss_fraction, "stop risk", 0.0001, 1)
    budgets = [_num(x, "remaining budget", 0, 1) for x in
               (market_exposure_remaining, sector_exposure_remaining, cash_available)]
    risk = _num(portfolio_risk_remaining, "remaining risk", 0, 1)
    dd = _num(drawdown, "drawdown", 0, 1)
    kelly = max(0.0, p - (1 - p) / b)
    # Threshold is a research hypothesis, NOT proof of realized win rate.
    if p < 0.8 or dd >= 0.10:
        return 0.0
    scale = 0.5 if dd >= 0.05 else 1.0
    return scale * min(0.25 * kelly, 0.10, 0.005 / s, risk / s, *budgets)


def outcome_diagnostics(net_returns):
    """Describe individual closed trades; zero return counts as non-win.

    Correlated trades are not independent. No binomial CI is reported.
    No inferred portfolio equity curve, Sharpe, drawdown or approval.
    """
    if not isinstance(net_returns, (list, tuple)) or not net_returns:
        raise ValueError("Nonempty realized net returns required")
    values = [_num(v, "net return", -1, 1000) for v in net_returns]
    wins = [v for v in values if v > 0]
    losses = [-v for v in values if v < 0]
    n = len(values)
    rate = len(wins) / n
    payoff = mean(wins) / mean(losses) if wins and losses else None
    pf = sum(wins) / sum(losses) if losses else None
    return {
        "trade_count": n, "wins": len(wins), "losses": len(losses),
        "flat": n - len(wins) - len(losses), "net_win_rate": rate,
        "mean_net_return": mean(values), "net_payoff_ratio": payoff,
        "profit_factor": pf,
        "point_targets_met": (n >= 500 and rate >= 0.8 and
                              payoff is not None and payoff >= 2 and
                              pf is not None and pf >= 2 and mean(values) > 0),
        "independence_verified": False, "holdout_verified": False,
        "portfolio_drawdown_verified": False,
        "model_release": "BLOCKED", "trading_approved": False,
    }
