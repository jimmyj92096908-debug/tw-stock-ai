"""以歷史日 K 計算九均線、RSI14、成交量均線與 ATR14。

所有指標只使用當日及以前的資料，不使用未來資料。
遇到停牌／無成交而缺少 OHLC 的日期，不虛構價格；價格指標略過該日，
並在該日輸出 None。有效交易日仍可持續累積計算窗口。
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Iterable

try:
    from .ohlc_quality import classify_ohlc_row
except ImportError:  # 支援以 src/ 作為 PYTHONPATH 的 GitHub Actions 執行方式
    from ohlc_quality import classify_ohlc_row

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
    """以有效觀測值計算移動平均，缺值日期保持 None。"""
    result: list[float | None] = [None] * len(values)
    valid = [(index, value) for index, value in enumerate(values) if value is not None]
    for position in range(window - 1, len(valid)):
        sample = [value for _, value in valid[position - window + 1 : position + 1]]
        result[valid[position][0]] = sum(sample) / window
    return result


def _wilder_rsi(closes: list[float | None], period: int = RSI_PERIOD) -> list[float | None]:
    result: list[float | None] = [None] * len(closes)
    valid = [(index, value) for index, value in enumerate(closes) if value is not None]
    if len(valid) <= period:
        return result

    prices = [value for _, value in valid]
    changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
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

    result[valid[period][0]] = value(avg_gain, avg_loss)
    for position in range(period + 1, len(valid)):
        change_index = position - 1
        avg_gain = ((avg_gain * (period - 1)) + gains[change_index]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[change_index]) / period
        result[valid[position][0]] = value(avg_gain, avg_loss)
    return result


def _wilder_atr(
    highs: list[float | None],
    lows: list[float | None],
    closes: list[float | None],
    period: int = ATR_PERIOD,
) -> list[float | None]:
    result: list[float | None] = [None] * len(highs)
    valid = [
        (index, high, low, closes[index])
        for index, (high, low) in enumerate(zip(highs, lows))
        if high is not None and low is not None and closes[index] is not None
    ]
    if len(valid) < period:
        return result

    true_ranges: list[float] = []
    for position, (_, high, low, _) in enumerate(valid):
        if position == 0:
            true_ranges.append(high - low)
        else:
            previous_close = valid[position - 1][3]
            true_ranges.append(max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close),
            ))

    current = sum(true_ranges[:period]) / period
    result[valid[period - 1][0]] = current
    for position in range(period, len(valid)):
        current = ((current * (period - 1)) + true_ranges[position]) / period
        result[valid[position][0]] = current
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
        quality = classify_ohlc_row(row)
        if quality.eligible_for_indicators:
            close = _number(row.get("close"), "close", index)
            high = _number(row.get("high"), "high", index)
            low = _number(row.get("low"), "low", index)
            volume = _number(row.get("volume"), "volume", index)
        else:
            # 缺價、來源缺價或 OHLC 不一致：保留該交易日輸出列，
            # 但不讓其價格或成交量污染任何價格／量能指標窗口。
            close = high = low = volume = None
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

