"""以歷史日 K 計算九均線、RSI14、成交量均線與 ATR14。

所有指標只使用當日及以前的資料，不使用未來資料。
資料不足時回傳 None，不填補或猜測指標值。
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Iterable

MA_WINDOWS = (5, 10, 13, 20, 34, 55, 60, 120, 240)
RSI_PERIOD = 14
ATR_PERIOD = 14


def _number(value: Any, field: str, index: int) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"第 {index} 筆 {field} 不是有效數字：{value!r}") from exc
    if not isfinite(result):
        raise ValueError(f"第 {index} 筆 {field} 不是有限數字")
    return result


def _rolling_mean(values: list[float | None], window: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    for end in range(window - 1, len(values)):
        sample = values[end - window + 1 : end + 1]
        if all(value is not None for value in sample):
            result[end] = sum(value for value in sample if value is not None) / window
    return result


def _wilder_rsi(closes: list[float | None], period: int = RSI_PERIOD) -> list[float | None]:
    result: list[float | None] = [None] * len(closes)
    if len(closes) <= period or any(value is None for value in closes):
        # Missing closes invalidate the sequence rather than silently bridging gaps.
        if any(value is None for value in closes):
            return result
    if len(closes) <= period:
        return result

    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]  # type: ignore[operator]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def value(gain: float, loss: float) -> float:
        if loss == 0:
            return 50.0 if gain == 0 else 100.0
        if gain == 0:
            return 0.0
        rs = gain / loss
        return 100.0 - (100.0 / (1.0 + rs))

    result[period] = value(avg_gain, avg_loss)
    for index in range(period + 1, len(closes)):
        avg_gain = ((avg_gain * (period - 1)) + gains[index - 1]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[index - 1]) / period
        result[index] = value(avg_gain, avg_loss)
    return result


def _wilder_atr(
    highs: list[float | None],
    lows: list[float | None],
    closes: list[float | None],
    period: int = ATR_PERIOD,
) -> list[float | None]:
    result: list[float | None] = [None] * len(highs)
    if len(highs) < period:
        return result

    true_ranges: list[float] = []
    for index, (high, low) in enumerate(zip(highs, lows)):
        if high is None or low is None:
            return result
        if index == 0:
            true_ranges.append(high - low)
        else:
            previous_close = closes[index - 1]
            if previous_close is None:
                return result
            true_ranges.append(max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close),
            ))

    current = sum(true_ranges[:period]) / period
    result[period - 1] = current
    for index in range(period, len(true_ranges)):
        current = ((current * (period - 1)) + true_ranges[index]) / period
        result[index] = current
    return result


def compute_indicators(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """輸入單一股票按日期遞增的日 K，回傳每個交易日的指標欄位。"""
    source = list(rows)
    if not source:
        return []

    dates: list[str] = []
    closes: list[float | None] = []
    highs: list[float | None] = []
    lows: list[float | None] = []
    volumes: list[float | None] = []

    for index, row in enumerate(source, start=1):
        trade_date = str(row["trade_date"])
        if dates and trade_date <= dates[-1]:
            raise ValueError("日 K 必須依 trade_date 嚴格遞增且不可重複")
        dates.append(trade_date)
        close = _number(row.get("close"), "close", index)
        high = _number(row.get("high"), "high", index)
        low = _number(row.get("low"), "low", index)
        volume = _number(row.get("volume"), "volume", index)
        if high is not None and low is not None and high < low:
            raise ValueError(f"第 {index} 筆 high 小於 low")
        if close is not None and high is not None and close > high:
            raise ValueError(f"第 {index} 筆 close 高於 high")
        if close is not None and low is not None and close < low:
            raise ValueError(f"第 {index} 筆 close 低於 low")
        closes.append(close)
        highs.append(high)
        lows.append(low)
        volumes.append(volume)

    indicators: dict[str, list[float | None]] = {
        f"ma{window}": _rolling_mean(closes, window) for window in MA_WINDOWS
    }
    indicators["rsi14"] = _wilder_rsi(closes)
    indicators["volume_ma5"] = _rolling_mean(volumes, 5)
    indicators["volume_ma20"] = _rolling_mean(volumes, 20)
    indicators["atr14"] = _wilder_atr(highs, lows, closes)

    output = []
    for index, row in enumerate(source):
        output.append({
            "market": row["market"],
            "stock_id": str(row["stock_id"]),
            "trade_date": row["trade_date"],
            **{name: values[index] for name, values in indicators.items()},
        })
    return output
