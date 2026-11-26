"""V3 offline fixed-bin calibration diagnostics with chronological embargo.

Caller supplies out-of-fold predictions with net realized returns. This
module checks timestamps and computes descriptive bin statistics; it cannot
authenticate provenance, probability quality, or statistical independence.
No training, live recommendations or release approval.
"""
from __future__ import annotations

from datetime import date
from math import fsum
from src.v3_capital_risk_research import _num


def _day(value):
    if not isinstance(value, str):
        raise ValueError("ISO date required")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("Canonical ISO date required")
    return parsed


def fixed_bin_calibration(rows, *, decision_date, probability):
    """Use only completed historical outcomes strictly before decision date.

    Fixed deciles, no optimizing thresholds on evaluation outcomes.
    Require 100 observations and 20 distinct signal dates in a bin before
    returning its empirical rate. These are adequacy screens, not effective
    independent sample size. Do not interpret rate as a lower confidence bound.
    """
    cutoff = _day(decision_date)
    p = _num(probability, "probability", 0, 1)
    if not isinstance(rows, (tuple, list)):
        raise ValueError("Expected prediction records")
    bins = [[] for _ in range(10)]
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid record")
        signal, exit_day, trained = map(_day, (
            row["signal_date"], row["exit_date"], row["training_labels_through"]))
        if not trained < signal < exit_day < cutoff:
            raise ValueError("Calibration requires mature out-of-fold outcomes")
        market, stock = row["market"], row["stock_id"]
        if market not in ("TWSE", "TPEx") or not isinstance(stock, str) or not stock.isascii() or not stock.isdigit() or stock == "1589":
            raise ValueError("Invalid or excluded stock")
        if row.get("currently_listed") is not True:
            raise ValueError("Current listed universe required")
        key = (market, stock, signal)
        if key in seen:
            raise ValueError("Duplicate stock signal")
        seen.add(key)
        pred = _num(row["probability"], "historical probability", 0, 1)
        net = _num(row["net_return"], "net return", -1, 1000)
        bins[min(9, int(pred * 10))].append((signal, pred, int(net > 0)))
    target = min(9, int(p * 10))
    group = bins[target]
    n = len(group)
    dates = len({x[0] for x in group})
    rate = fsum(x[2] for x in group) / n if n else None
    enough = n >= 100 and dates >= 20
    return {
        "bin_index": target, "observations": n, "distinct_signal_dates": dates,
        "empirical_net_win_rate": rate,
        "mean_predicted_probability": fsum(x[1] for x in group) / n if n else None,
        "brier_score": fsum((x[1] - x[2]) ** 2 for x in group) / n if n else None,
        "descriptive_rate_available": enough,
        "conservative_probability_for_sizing": None,
        "independence_verified": False, "provenance_verified": False,
        "survivorship_bias_possible": True,
        "model_release": "BLOCKED", "trading_approved": False,
    }
