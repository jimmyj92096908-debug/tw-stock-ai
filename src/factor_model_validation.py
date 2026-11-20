"""Point-in-time cross-sectional factor-model evaluator (research only).

The existing daily_composite_scores is the MODEL; this module evaluates a fixed
ranking rule, not a fitted or retrospectively optimized trading strategy.
A signal known after session t CLOSE enters at t+1 CLOSE and exits at t+6
CLOSE (five full subsequent close-to-close sessions). This removes same-close
fills but is NOT executable brokerage simulation, and ignores fees/slippage.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
import math
from statistics import mean

MODEL_VERSION = "composite-rank-v1"
MIN_COVERAGE = 0.50
MIN_PER_DATE = 5
TOP_FRACTION = 0.20
HOLDING_SESSIONS = 5

# Window is computed over complete stored stock history BEFORE date filtering.
# A score must have a real closing price on the SAME signal date. No future
# close is used in ranking or score construction.
EVALUATION_SQL = """
WITH closes AS (
 SELECT market, stock_id, trade_date, close,
        LEAD(close,1) OVER w AS entry_close,
        LEAD(close,6) OVER w AS exit_close
 FROM public.daily_prices
 WHERE close IS NOT NULL AND close>0
 WINDOW w AS (PARTITION BY market, stock_id ORDER BY trade_date)
)
SELECT s.market, s.stock_id, s.as_of_date, s.total_score,
       s.coverage_weight, c.close AS signal_close,
       c.entry_close, c.exit_close
FROM public.daily_composite_scores s
JOIN closes c ON c.market=s.market AND c.stock_id=s.stock_id
 AND c.trade_date=s.as_of_date
WHERE s.total_score IS NOT NULL
 AND s.coverage_weight >= %s
 AND s.as_of_date >= %s
 AND s.as_of_date <= %s
ORDER BY s.as_of_date,s.market,s.stock_id
"""

def _iso(value):
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    return str(value)[:10]

def evaluate_rows(rows, *, min_per_date=MIN_PER_DATE, top_fraction=TOP_FRACTION):
    """Return date-level top-vs-universe outcomes and honest exclusion counts.

    Ranking uses only score and coverage known at t. Compare each selected
    cohort against the same day's evaluable universe; insufficient or missing
    forward prices mean a date cannot be judged as successful.
    """
    if min_per_date < 2 or not 0 < top_fraction <= 1:
        raise ValueError("invalid evaluation parameters")
    dates = defaultdict(list)
    excluded = {"invalid_or_missing": 0, "insufficient_coverage": 0,
                "missing_future_price": 0, "duplicate_key": 0}
    seen = set()
    for row in rows:
        day = _iso(row["as_of_date"])
        key = (row["market"], row["stock_id"], day)
        if key in seen:
            excluded["duplicate_key"] += 1
            continue
        seen.add(key)
        try:
            score = float(row["total_score"])
            coverage = float(row["coverage_weight"])
            entry = float(row["entry_close"])
            exit_ = float(row["exit_close"])
        except (TypeError, ValueError, KeyError):
            excluded["invalid_or_missing"] += 1
            continue
        if not all(map(math.isfinite, (score, coverage, entry, exit_))) or not 0 <= score <= 100 or entry <= 0 or exit_ <= 0:
            excluded["invalid_or_missing"] += 1
            continue
        if coverage < MIN_COVERAGE or coverage > 1:
            excluded["insufficient_coverage"] += 1
            continue
        # The score is computed at t; only use t+1 and t+6 here as labels.
        result = exit_ / entry - 1
        dates[day].append((score, coverage, row["market"], row["stock_id"], result))
    periods = []
    skipped_small = 0
    for day, securities in sorted(dates.items()):
        if len(securities) < min_per_date:
            skipped_small += 1
            continue
        # Fixed deterministic tie-break to prevent input row order leakage.
        ranked = sorted(securities, key=lambda a: (-a[0], -a[1], a[2], a[3]))
        n = max(1, math.ceil(len(ranked) * top_fraction))
        top = ranked[:n]
        base = mean(x[-1] for x in ranked)
        top_return = mean(x[-1] for x in top)
        periods.append({
            "as_of_date": day, "universe": len(ranked), "selected": n,
            "top_mean_return": round(top_return, 8),
            "universe_mean_return": round(base, 8),
            "excess_return": round(top_return - base, 8),
            "top_hit_rate": round(mean(x[-1] > 0 for x in top), 6),
        })
    return {
        "model_version": MODEL_VERSION,
        "evaluation": "forward 5 sessions; entry at next available close",
        "periods": periods,
        "signal_dates": len(periods),
        "skipped_small_universe_dates": skipped_small,
        "excluded_rows": excluded,
        "mean_top_return": round(mean(p["top_mean_return"] for p in periods), 8) if periods else None,
        "mean_universe_return": round(mean(p["universe_mean_return"] for p in periods), 8) if periods else None,
        "mean_excess_return": round(mean(p["excess_return"] for p in periods), 8) if periods else None,
        "positive_excess_date_fraction": round(mean(p["excess_return"] > 0 for p in periods), 6) if periods else None,
        "production_validated": False,
        "limitations": [
            "Not live executable, not a portfolio CAGR or Sharpe ratio",
            "Overlapping rolling five-session labels are serially dependent",
            "Survivorship and coverage selection bias; missing delisted assets",
            "No exchange holidays alignment across suspended tickers",
            "No trading fees, liquidity filter, spreads or slippage",
            "No calibration or independent out-of-sample hyperparameter selection",
        ],
    }
