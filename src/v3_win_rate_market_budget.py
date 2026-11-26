"""Offline V3 date-block bootstrap and incremental exposure policy.

The bootstrap describes sensitivity to historical dependence. It cannot
establish independent observations, authentic provenance or future coverage.
No outputs authorize live trading or provide a verified sizing probability.
"""
from __future__ import annotations

import random
from src.v3_capital_risk_research import _num
from src.v3_probability_calibration import _day


def block_win_rate_research(rows, *, decision_date):
    """Resample contiguous groups of signal dates, retaining whole cohorts.

    Fixed 5/10/20-date moving blocks, 1000 draws each, fixed seeds.
    Reject immature labels and duplicate signals. Require at least 500
    outcomes and 100 signal dates. Date blocks are not verified trading
    sessions, and may not capture longer dependence or regime changes.
    """
    cutoff = _day(decision_date)
    if not isinstance(rows, list) or not rows or len(rows) > 200000:
        raise ValueError("Require bounded nonempty outcome records")
    groups, seen = {}, set()
    for row in rows:
        signal, end, trained = map(_day, (row["signal_date"], row["exit_date"],
                                          row["training_labels_through"]))
        if not trained < signal < end < cutoff:
            raise ValueError("Immature or in-sample outcome")
        market, stock = row["market"], row["stock_id"]
        if (market not in ("TWSE", "TPEx") or not isinstance(stock, str)
                or not stock.isascii() or not stock.isdigit() or stock == "1589"
                or row.get("currently_listed") is not True):
            raise ValueError("Invalid or excluded instrument")
        key = (market, stock, signal)
        if key in seen:
            raise ValueError("Duplicate signal")
        seen.add(key)
        net = _num(row["net_return"], "net return", -1, 1000)
        w, n = groups.get(signal, (0, 0))
        groups[signal] = (w + int(net > 0), n+1)
    cohorts = [groups[d] for d in sorted(groups)]
    count = len(rows)
    m = len(cohorts)
    point = sum(w for w,n in cohorts)/count
    bounds = {}
    if count >= 500 and m >= 100:
        for block in (5,10,20):
            rng = random.Random(20261126 + block)
            rates = []
            for _ in range(1000):
                wins = total = used = 0
                while used < m:
                    i = rng.randrange(m-block+1)
                    take = min(block, m-used)
                    for w,n in cohorts[i:i+take]:
                        wins += w
                        total += n
                    used += take
                rates.append(wins/total)
            rates.sort()
            bounds[str(block)] = rates[49]
    lower = min([point, *bounds.values()]) if bounds else None
    return {"observations": count, "signal_dates": m, "point_win_rate": point,
            "block_lower_percentile_5": bounds,
            "sensitivity_lower_estimate": lower,
            "research_80pct_screen": lower is not None and lower >= 0.80,
            "verified_confidence_bound": False,
            "dependence_verified": False, "provenance_verified": False,
            "survivorship_bias_possible": True,
            "conservative_probability_for_sizing": None,
            "model_release": "BLOCKED", "trading_approved": False}


def incremental_market_budget(*, regime, volatile_heuristic,
                              existing_gross_exposure, cash_available, drawdown):
    """Research-only long exposure ceiling; caller verifies regime evidence.

    Does not sell existing holdings, infer liquidity, or approve a trade.
    Unknown or extreme regimes allow no new exposure.
    """
    ceilings = {"UPTREND": 0.8, "RANGE_OR_TRANSITION": 0.4,
                "DOWNTREND": 0.2, "UNKNOWN_HISTORY": 0.0,
                "EXTREME_RISK": 0.0}
    if regime not in ceilings or type(volatile_heuristic) is not bool:
        raise ValueError("Invalid market regime")
    current = _num(existing_gross_exposure, "existing exposure", 0, 1)
    cash = _num(cash_available, "cash available", 0, 1)
    dd = _num(drawdown, "drawdown", 0, 1)
    if current + cash > 1 + 1e-9:
        raise ValueError("Exposure and available cash exceed account equity")
    ceiling = ceilings[regime] * (0.5 if volatile_heuristic else 1)
    if dd >= 0.10:
        ceiling = 0.0
    elif dd >= 0.05:
        ceiling *= 0.5
    return {"research_gross_ceiling": ceiling,
            "incremental_exposure_budget": min(cash, max(0.0, ceiling-current)),
            "existing_exposure_above_ceiling": current > ceiling,
            "forced_sale": False, "regime_provenance_verified": False,
            "model_release": "BLOCKED", "trading_approved": False}
