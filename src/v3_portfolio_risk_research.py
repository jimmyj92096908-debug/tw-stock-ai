"""Offline V3 aligned-return covariance and equal-risk-contribution research.

Uses supplied trailing returns only; no independent source authentication,
orders, production integration or inference of future risk. All units decimal.
"""
from __future__ import annotations

from math import fsum, sqrt
from src.v3_capital_risk_research import _num
from src.v3_probability_calibration import _day

MIN_SESSIONS = 60
SHRINKAGE = 0.10
MAX_ITERATIONS = 2000
TOL = 1e-8


def portfolio_risk_research(histories, *, decision_date, gross_budget, cash_budget):
    """Long-only equal-risk-contribution reference using 10% diagonal shrinkage.

    Require identical observed dates across all assets, strictly before the
    decision date. Caller must independently verify exchange-calendar coverage,
    point-in-time corporate actions, listings and data availability. Gross and
    cash budgets are incremental fractions of account equity. Existing holdings
    and sector/stop-risk constraints are NOT modeled here; output is a research
    reference only, not deployable weights.
    """
    cutoff = _day(decision_date)
    gross = _num(gross_budget, "gross budget", 0, 1)
    cash = _num(cash_budget, "cash budget", 0, 1)
    if not isinstance(histories, list) or not 2 <= len(histories) <= 50:
        raise ValueError("Require 2 to 50 histories")
    ids, series, dates = [], [], None
    for h in histories:
        market, stock = h["market"], h["stock_id"]
        if (market not in ("TWSE", "TPEx") or not isinstance(stock, str)
                or not stock.isascii() or not stock.isdigit() or stock == "1589"
                or h.get("currently_listed") is not True):
            raise ValueError("Invalid or excluded instrument")
        key = (market, stock)
        if key in ids or any(stock == k[1] for k in ids):
            raise ValueError("Duplicate instrument")
        observations = h["returns"]
        if not isinstance(observations, list) or not MIN_SESSIONS <= len(observations) <= 1260:
            raise ValueError("Insufficient or excessive return history")
        ds, values = [], []
        for row in observations:
            d = _day(row["date"])
            if d >= cutoff or (ds and d <= ds[-1]):
                raise ValueError("Future, duplicate or unordered return date")
            ds.append(d)
            values.append(_num(row["return"], "daily return", -1, 100))
        if dates is not None and dates != ds:
            raise ValueError("Unaligned return calendars")
        dates = ds
        ids.append(key)
        series.append(values)
    n, m = len(ids), len(dates)
    centered = [[v - fsum(s) / m for v in s] for s in series]
    # Standardize before the solver to avoid scale-dependent convergence.
    sd = [sqrt(fsum(v*v for v in s) / (m-1)) for s in centered]
    if any(v <= 1e-10 for v in sd):
        raise ValueError("Zero or near-zero historical volatility")
    z = [[v / sd[i] for v in s] for i, s in enumerate(centered)]
    corr = [[max(-1.0, min(1.0, fsum(a*b for a,b in zip(z[i],z[j]))/(m-1)))
             for j in range(n)] for i in range(n)]
    # Diagonal shrinkage makes the empirical correlation positive definite.
    c = [[1.0 if i == j else (1-SHRINKAGE)*corr[i][j]
          for j in range(n)] for i in range(n)]
    # Coordinate descent on 0.5*y'C*y - sum(log(y_i))/n.
    # With x_i=y_i/sd_i, normalized x has equal risk contributions.
    y = [1/sqrt(n)] * n
    for iteration in range(1, MAX_ITERATIONS+1):
        for i in range(n):
            a = fsum(c[i][j]*y[j] for j in range(n) if j != i)
            root = sqrt(a*a + 4/n)
            y[i] = (2/n)/(root+a) if a >= 0 else (root-a)/2
        rc = [y[i]*fsum(c[i][j]*y[j] for j in range(n)) for i in range(n)]
        if max(abs(v-1/n) for v in rc) <= TOL:
            break
    else:
        raise ValueError("Risk contribution solver did not converge")
    x = [y[i]/sd[i] for i in range(n)]
    total = fsum(x)
    w = [v/total for v in x]
    # Uniform scaling preserves relative ERC weights and leaves unused cash.
    # It does not implement a fully constrained risk parity optimization.
    exposure = min(gross, cash, 0.10/max(w))
    cov = [[c[i][j]*sd[i]*sd[j] for j in range(n)] for i in range(n)]
    contributions = [w[i]*fsum(cov[i][j]*w[j] for j in range(n)) for i in range(n)]
    var = fsum(contributions)
    if var <= 0:
        raise ValueError("Invalid portfolio variance")
    pairs = [{"a": list(ids[i]), "b": list(ids[j]), "correlation": corr[i][j]}
             for i in range(n) for j in range(i+1,n) if corr[i][j] >= 0.80]
    return {
        "observations": m, "last_return_date": dates[-1].isoformat(),
        "shrinkage": SHRINKAGE, "solver_iterations": iteration,
        "high_positive_correlation_pairs": pairs,
        "reference_daily_volatility": sqrt(var)*exposure,
        "reference_gross_exposure": exposure, "unallocated_account_fraction": 1-exposure,
        "weights": [{"market": k[0], "stock_id": k[1],
                     "relative_risky_weight": w[i], "reference_account_weight": w[i]*exposure,
                     "relative_variance_contribution": contributions[i]/var}
                    for i,k in enumerate(ids)],
        "existing_holdings_integrated": False, "sector_stop_constraints_integrated": False,
        "source_provenance_verified": False, "calendar_completeness_verified": False,
        "model_release": "BLOCKED", "trading_approved": False,
    }
