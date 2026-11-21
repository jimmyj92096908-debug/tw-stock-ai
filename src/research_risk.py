"""Descriptive research-only risk metrics; never a live trading or risk approval.

Returns are externally verified, non-overlapping forward *research outcomes*.
No leverage, executable price, portfolio fills or annualization is inferred.
"""
from __future__ import annotations

from datetime import date
import math
from statistics import mean, pstdev


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def _day(value: object) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    raise ValueError("Date is required")


def nonoverlapping_path(outcomes: list[dict]) -> dict:
    """Compound a sequence of non-overlapping baskets, not overlapping daily bets.

    net_return is a decimal net round-trip outcome (e.g. -.05), not a
    percent. Missing labels and overlapping holding windows fail closed.
    """
    peak = 1.0
    wealth = 1.0
    max_drawdown = 0.0
    last_exit = None
    returns = []
    excess = []
    baseline = []
    benchmark = []
    for item in outcomes:
        start = _day(item["signal_date"])
        end = _day(item["exit_date"])
        if end <= start or (last_exit is not None and start <= last_exit):
            raise ValueError("Overlapping or out-of-order forward holding windows")
        last_exit = end
        ret = _finite(item["net_return"], "net_return")
        exc = _finite(item["excess_vs_universe"], "excess_vs_universe")
        base = _finite(item["baseline_net_return"], "baseline_net_return")
        if any(x < -1 for x in (ret, base)):
            raise ValueError("Return below -100 percent")
        if ("benchmark_net_return" in item) and item["benchmark_net_return"] is not None:
            bm = _finite(item["benchmark_net_return"], "benchmark_net_return")
            if bm < -1:
                raise ValueError("Benchmark return below -100 percent")
            benchmark.append(bm)
        returns.append(ret)
        excess.append(exc)
        baseline.append(base)
        wealth *= 1 + ret
        peak = max(peak, wealth)
        max_drawdown = max(max_drawdown, 1 - wealth / peak)
    return {
        "observations": len(returns),
        "compounded_net_return": round(wealth - 1, 8) if returns else None,
        "maximum_drawdown": round(max_drawdown, 8) if returns else None,
        "per_observation_volatility": round(pstdev(returns), 8) if returns else None,
        "positive_net_return_fraction": round(sum(x > 0 for x in returns) / len(returns), 6) if returns else None,
        "mean_net_return": round(mean(returns), 8) if returns else None,
        "mean_net_excess_vs_universe": round(mean(excess), 8) if returns else None,
        "mean_original_score_net_return": round(mean(baseline), 8) if returns else None,
        "worst_net_return": round(min(returns), 8) if returns else None,
        "external_benchmark_mean_net_return": (
            round(mean(benchmark), 8) if len(benchmark) == len(returns) and benchmark else None
        ),
        "external_benchmark_complete": bool(returns) and len(benchmark) == len(returns),
        "annualized": False,
        "not_an_executable_backtest": True,
        "trading_approved": False,
    }


def concentration(holdings: list[dict]) -> dict:
    """Concentration only; no holding weights are invented when absent."""
    if not holdings:
        return {"known": False, "reason": "no_verified_portfolio_weights"}
    seen = set()
    weights = []
    for item in holdings:
        ident = (item.get("market"), str(item.get("stock_id", "")))
        if not all(ident) or ident in seen:
            raise ValueError("Duplicate or invalid portfolio symbol")
        seen.add(ident)
        w = _finite(item.get("weight"), "weight")
        if w < 0 or w > 1:
            raise ValueError("Portfolio weight must be in [0, 1]")
        weights.append(w)
    if abs(sum(weights) - 1.0) > 1e-6:
        raise ValueError("Portfolio weights must sum to exactly 1")
    hhi = sum(w*w for w in weights)
    return {"known": True, "holding_count": len(holdings),
            "max_single_weight": round(max(weights), 8),
            "top_five_weight": round(sum(sorted(weights, reverse=True)[:5]), 8),
            "herfindahl_index": round(hhi, 8),
            "effective_number_of_holdings": round(1/hhi, 4) if hhi else None,
            "not_a_loss_forecast": True}


def market_regime(prices: list[dict], *, as_of_date: str,
                  long_window: int = 60, slope_window: int = 20) -> dict:
    """Pure trailing-close market classification (NOT a stock buy/sell signal).

    Input must be a *verified market-index* time series, never an arbitrary
    stock or an unlabelled synthetic market proxy. Only prices <= as_of_date
    can affect the output. Missing history returns unknown.
    """
    if long_window < 20 or slope_window < 2:
        raise ValueError("Market regime windows too short")
    cutoff = _day(as_of_date)
    rows = []
    previous = None
    for item in prices:
        day = _day(item["date"])
        close = _finite(item["close"], "close")
        if close <= 0 or (previous is not None and day <= previous):
            raise ValueError("Non-positive, duplicated or unsorted index close")
        previous = day
        if day <= cutoff:
            rows.append((day, close))
    required = long_window + slope_window
    if len(rows) < required:
        return {"regime": "UNKNOWN_HISTORY", "observations": len(rows),
                "required": required, "as_of_date": cutoff.isoformat(),
                "trading_approved": False}
    close = rows[-1][1]
    latest_ma = mean(v for _, v in rows[-long_window:])
    previous_ma = mean(v for _, v in rows[-long_window-slope_window:-slope_window])
    returns = [rows[i][1] / rows[i-1][1] - 1 for i in range(len(rows)-slope_window, len(rows))]
    vol = pstdev(returns)
    if close > latest_ma and latest_ma > previous_ma:
        state = "UPTREND"
    elif close < latest_ma and latest_ma < previous_ma:
        state = "DOWNTREND"
    else:
        state = "RANGE_OR_TRANSITION"
    return {"regime": state, "as_of_date": rows[-1][0].isoformat(),
            "observations": len(rows), "ma_long": round(latest_ma, 6),
            "ma_long_previous": round(previous_ma, 6),
            "trailing_volatility_per_session": round(vol, 8),
            "volatile_heuristic": vol >= 0.03,
            "verified_index_provenance_required": True,
            "is_descriptive_not_predictive": True,
            "trading_approved": False}
