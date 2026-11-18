"""以已計算的技術指標產生可解釋的技術狀態標籤。

本模組只描述指標狀態，不構成買賣指令或報酬保證。
所有交叉訊號只比較當日與前一筆資料，不使用未來資料。
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Iterable

MA_WINDOWS = (5, 10, 13, 20, 34, 55, 60, 120, 240)
VOLUME_EXPANSION_MULTIPLIER = 1.5
RSI_OVERBOUGHT = 70.0
RSI_OVERSOLD = 30.0

CROSS_PAIRS = ((5, 20), (20, 60))


def _finite_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _cross_state(previous_short: float | None, previous_long: float | None,
                 current_short: float | None, current_long: float | None) -> str:
    if None in (previous_short, previous_long, current_short, current_long):
        return "insufficient_data"
    if previous_short <= previous_long and current_short > current_long:
        return "golden_cross"
    if previous_short >= previous_long and current_short < current_long:
        return "death_cross"
    return "no_cross"


def compute_signals(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """輸入單一股票依日期遞增的指標列，回傳每列技術狀態。"""
    source = list(rows)
    output: list[dict[str, Any]] = []

    for index, row in enumerate(source):
        ma = {window: _finite_number(row.get(f"ma{window}")) for window in MA_WINDOWS}
        valid_ma = all(value is not None for value in ma.values())
        bullish = valid_ma and all(ma[a] > ma[b] for a, b in zip(MA_WINDOWS, MA_WINDOWS[1:]))
        bearish = valid_ma and all(ma[a] < ma[b] for a, b in zip(MA_WINDOWS, MA_WINDOWS[1:]))

        previous = source[index - 1] if index else {}
        crosses = {}
        for short, long in CROSS_PAIRS:
            crosses[f"ma{short}_ma{long}_cross"] = _cross_state(
                _finite_number(previous.get(f"ma{short}")),
                _finite_number(previous.get(f"ma{long}")),
                ma[short],
                ma[long],
            )

        rsi = _finite_number(row.get("rsi14"))
        if rsi is None:
            rsi_state = "insufficient_data"
        elif rsi >= RSI_OVERBOUGHT:
            rsi_state = "overbought"
        elif rsi <= RSI_OVERSOLD:
            rsi_state = "oversold"
        else:
            rsi_state = "neutral"

        volume = _finite_number(row.get("volume"))
        volume_ma20 = _finite_number(row.get("volume_ma20"))
        volume_ratio = (
            volume / volume_ma20
            if volume is not None and volume_ma20 is not None and volume_ma20 > 0
            else None
        )
        volume_state = (
            "insufficient_data" if volume_ratio is None
            else "expanded" if volume_ratio >= VOLUME_EXPANSION_MULTIPLIER
            else "normal"
        )

        output.append({
            "market": row.get("market"),
            "stock_id": str(row.get("stock_id", "")),
            "trade_date": row.get("trade_date"),
            "ma_alignment": (
                "bullish" if bullish else "bearish" if bearish
                else "mixed_or_insufficient_data"
            ),
            **crosses,
            "rsi_state": rsi_state,
            "volume_ratio": volume_ratio,
            "volume_state": volume_state,
        })
    return output
