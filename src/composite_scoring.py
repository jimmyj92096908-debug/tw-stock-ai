"""Explainable 0-100 technical + SMC scoring; no future data or trade execution."""
from __future__ import annotations

from math import isfinite
from typing import Any

MA_WINDOWS = (5, 10, 13, 20, 34, 55, 60, 120, 240)
MODEL_WEIGHTS = {"technical": 0.50, "smc": 0.30, "chip": 0.20}


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _average(items: list[tuple[float, float]]) -> float | None:
    valid = [(score, weight) for score, weight in items if score is not None and weight > 0]
    if not valid:
        return None
    return sum(score * weight for score, weight in valid) / sum(weight for _, weight in valid)


def _relative_score(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return 75.0 if left > right else 25.0 if left < right else 50.0


def _rsi_score(rsi: float | None) -> float | None:
    if rsi is None or not 0 <= rsi <= 100:
        return None
    # Favors positive momentum without rewarding an extremely overbought reading.
    if rsi < 30:
        return 35.0
    if rsi < 45:
        return 45.0 + (rsi - 30.0) * (20.0 / 15.0)
    if rsi <= 65:
        return 65.0 + (rsi - 45.0) * 1.0
    if rsi <= 75:
        return 85.0 - (rsi - 65.0) * 2.5
    return max(20.0, 60.0 - (rsi - 75.0) * 2.0)


def _volume_score(ratio: float | None) -> float | None:
    if ratio is None or ratio < 0:
        return None
    if ratio >= 2.0:
        return 85.0
    if ratio >= 1.5:
        return 75.0
    if ratio >= 0.8:
        return 60.0
    return 45.0


def _direction_score(direction: int | None) -> float | None:
    if direction is None:
        return None
    return 80.0 if direction > 0 else 20.0 if direction < 0 else 50.0


def _event_score(row: dict[str, Any], positive: str, negative: str,
                 positive_score: float = 90.0, negative_score: float = 10.0) -> float | None:
    if row.get(positive):
        return positive_score
    if row.get(negative):
        return negative_score
    # No event is neutral, not missing.
    return 50.0


def _technical_scores(row: dict[str, Any]) -> dict[str, float | None]:
    close = _number(row.get("close"))
    ma = {n: _number(row.get(f"ma{n}")) for n in MA_WINDOWS}
    rsi = _rsi_score(_number(row.get("rsi14")))
    volume_ratio = None
    volume = _number(row.get("volume"))
    volume_ma20 = _number(row.get("volume_ma20"))
    if volume is not None and volume_ma20 is not None and volume_ma20 > 0:
        volume_ratio = _volume_score(volume / volume_ma20)

    short = _average([
        (v, w) for v, w in [
            (_relative_score(close, ma[5]), 2.0),
            (_relative_score(ma[5], ma[20]), 2.0),
            (rsi, 1.0),
            (volume_ratio, 1.0),
        ] if v is not None
    ])
    swing = _average([
        (v, w) for v, w in [
            (_relative_score(close, ma[20]), 2.0),
            (_relative_score(ma[20], ma[60]), 2.0),
            (rsi, 1.0),
            (volume_ratio, 0.5),
        ] if v is not None
    ])
    long = _average([
        (v, w) for v, w in [
            (_relative_score(close, ma[60]), 1.0),
            (_relative_score(ma[60], ma[120]), 1.5),
            (_relative_score(ma[120], ma[240]), 2.0),
        ] if v is not None
    ])
    overall = _average([
        (v, w) for v, w in [(short, 0.30), (swing, 0.35), (long, 0.35)]
        if v is not None
    ])
    return {"technical_score": overall, "short_technical": short,
            "swing_technical": swing, "long_technical": long}


def _smc_scores(row: dict[str, Any]) -> dict[str, float | None]:
    if row.get("trend_direction") is None:
        return {"smc_score": None, "short_smc": None, "swing_smc": None, "long_smc": None}
    trend = _direction_score(int(row["trend_direction"]))
    bos = _event_score(row, "bos_bullish", "bos_bearish")
    choch = _event_score(row, "choch_bullish", "choch_bearish", 85.0, 15.0)
    sweep = _event_score(row, "liquidity_sweep_low", "liquidity_sweep_high", 70.0, 30.0)
    fvg_type = row.get("fvg_type")
    fvg = 70.0 if fvg_type == "bullish" else 30.0 if fvg_type == "bearish" else 50.0
    ob_type = row.get("order_block_type")
    ob = 70.0 if ob_type == "bullish" else 30.0 if ob_type == "bearish" else 50.0

    short = _average([(bos, 2.0), (choch, 1.5), (sweep, 1.0), (trend, 1.0)])
    swing = _average([(trend, 2.0), (bos, 2.0), (choch, 1.5), (fvg, 1.0), (ob, 1.0)])
    long = _average([(trend, 3.0), (bos, 1.0), (choch, 1.0)])
    overall = _average([(v, w) for v, w in [(short, 0.25), (swing, 0.40), (long, 0.35)] if v is not None])
    return {"smc_score": overall, "short_smc": short, "swing_smc": swing, "long_smc": long}


def compute_composite_score(row: dict[str, Any]) -> dict[str, Any]:
    """Return explainable technical + SMC + chip scores with explicit coverage."""
    technical = _technical_scores(row)
    smc = _smc_scores(row)

    raw_chip = _number(row.get("chip_score"))
    raw_chip_coverage = _number(row.get("chip_coverage_weight"))
    chip_coverage = max(0.0, min(1.0, raw_chip_coverage or 0.0))
    chip = raw_chip if raw_chip is not None and chip_coverage >= 0.50 else None
    chip_status = (
        "available" if chip is not None
        else "insufficient_coverage" if chip_coverage > 0
        else "not_available"
    )

    horizon_scores: dict[str, float | None] = {}
    horizon_coverages: dict[str, float] = {}
    for horizon in ("short", "swing", "long"):
        t = technical[f"{horizon}_technical"]
        s = smc[f"{horizon}_smc"]
        horizon_scores[horizon] = _average([
            (t, MODEL_WEIGHTS["technical"]),
            (s, MODEL_WEIGHTS["smc"]),
            (chip, MODEL_WEIGHTS["chip"]),
        ])
        horizon_coverages[horizon] = round(
            (MODEL_WEIGHTS["technical"] if t is not None else 0.0)
            + (MODEL_WEIGHTS["smc"] if s is not None else 0.0)
            + (MODEL_WEIGHTS["chip"] * chip_coverage if chip is not None else 0.0),
            4,
        )

    overall = _average([
        (horizon_scores["short"], 0.30),
        (horizon_scores["swing"], 0.35),
        (horizon_scores["long"], 0.35),
    ])
    available_model_weight = round(
        (MODEL_WEIGHTS["technical"] if technical["technical_score"] is not None else 0.0)
        + (MODEL_WEIGHTS["smc"] if smc["smc_score"] is not None else 0.0)
        + (MODEL_WEIGHTS["chip"] * chip_coverage if chip is not None else 0.0),
        4,
    )
    if available_model_weight < 0.50:
        overall = None

    return {
        "total_score": overall,
        "technical_score": technical["technical_score"],
        "smc_score": smc["smc_score"],
        "chip_score": chip,
        "short_term_score": horizon_scores["short"],
        "swing_score": horizon_scores["swing"],
        "long_term_score": horizon_scores["long"],
        "coverage_weight": available_model_weight,
        "short_coverage": horizon_coverages["short"],
        "swing_coverage": horizon_coverages["swing"],
        "long_coverage": horizon_coverages["long"],
        "component_status": {
            "technical": "available" if technical["technical_score"] is not None else "insufficient_data",
            "smc": "available" if smc["smc_score"] is not None else "insufficient_data",
            "chip": chip_status,
            "chip_source_coverage": chip_coverage,
            "model_weights": MODEL_WEIGHTS,
            "scoring_version": "v2",
        },
    }
