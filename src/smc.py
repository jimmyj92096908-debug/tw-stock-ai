"""以已確認的價格結構計算 SMC 事件；所有事件只在可知悉當日輸出。

定義：
- Swing pivot：左右各 pivot_left/pivot_right 根 K 棒的嚴格局部高低點。
- Pivot 只能在右側 K 棒完整後確認，事件可用日為確認日，不回填至 pivot 日。
- BOS：收盤價突破最近已確認且尚未被突破的 swing level。
- CHOCH：收盤價首次反向突破目前結構方向的 swing level。
- FVG：三根 K 棒形成的價格缺口。
- Order Block：BOS/CHOCH 前 lookback 根內，最近一根反向 K 棒；只在突破當日辨識。
- Liquidity sweep：影線越過已確認 swing level，但收盤回到 level 另一側。

這是規則化的技術分析近似，不代表市場存在唯一標準 SMC 定義。
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Iterable


def _num(value: Any, field: str, index: int) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"第 {index} 筆 {field} 不是有效數字") from exc
    if not isfinite(result):
        raise ValueError(f"第 {index} 筆 {field} 不是有限數字")
    return result


def compute_smc(
    rows: Iterable[dict[str, Any]],
    pivot_left: int = 3,
    pivot_right: int = 3,
    ob_lookback: int = 10,
) -> list[dict[str, Any]]:
    """輸入單一股票依日期遞增的 OHLC，逐日輸出 SMC 結構事件。"""
    if pivot_left < 1 or pivot_right < 1 or ob_lookback < 1:
        raise ValueError("pivot_left、pivot_right、ob_lookback 必須大於 0")

    source = list(rows)
    if not source:
        return []

    bars = []
    previous_date = None
    for index, row in enumerate(source):
        date = str(row["trade_date"])
        if previous_date is not None and date <= previous_date:
            raise ValueError("日 K 必須依 trade_date 嚴格遞增且不可重複")
        previous_date = date
        high = _num(row.get("high"), "high", index + 1)
        low = _num(row.get("low"), "low", index + 1)
        close = _num(row.get("close"), "close", index + 1)
        if high is not None and low is not None and high < low:
            raise ValueError(f"第 {index + 1} 筆 high 小於 low")
        if close is not None and high is not None and close > high:
            raise ValueError(f"第 {index + 1} 筆 close 高於 high")
        if close is not None and low is not None and close < low:
            raise ValueError(f"第 {index + 1} 筆 close 低於 low")
        bars.append({**row, "high": high, "low": low, "close": close})

    output = []
    swing_high = None
    swing_low = None
    high_broken = False
    low_broken = False
    trend = "neutral"

    for index, bar in enumerate(bars):
        date = str(bar["trade_date"])
        high, low, close = bar["high"], bar["low"], bar["close"]
        events: list[dict[str, Any]] = []
        pivot_high = None
        pivot_low = None

        # 在當日收盤時，右側 pivot_right 根已完整，才確認中心 K 棒。
        center = index - pivot_right
        if center >= pivot_left:
            window = bars[center - pivot_left : center + pivot_right + 1]
            center_bar = bars[center]
            if all(item["high"] is not None for item in window):
                center_high = center_bar["high"]
                if all(center_high > item["high"] for j, item in enumerate(window) if j != pivot_left):
                    pivot_high = {
                        "price": center_high,
                        "pivot_date": str(center_bar["trade_date"]),
                        "confirmed_date": date,
                    }
                    swing_high = pivot_high
                    high_broken = False
            if all(item["low"] is not None for item in window):
                center_low = center_bar["low"]
                if all(center_low < item["low"] for j, item in enumerate(window) if j != pivot_left):
                    pivot_low = {
                        "price": center_low,
                        "pivot_date": str(center_bar["trade_date"]),
                        "confirmed_date": date,
                    }
                    swing_low = pivot_low
                    low_broken = False

        if pivot_high:
            events.append({"type": "swing_high_confirmed", **pivot_high})
        if pivot_low:
            events.append({"type": "swing_low_confirmed", **pivot_low})

        # FVG：僅使用目前及前兩根 K 棒。
        if index >= 2:
            first, current = bars[index - 2], bar
            if first["high"] is not None and current["low"] is not None and current["low"] > first["high"]:
                events.append({
                    "type": "bullish_fvg",
                    "lower": first["high"],
                    "upper": current["low"],
                    "formed_date": date,
                })
            if first["low"] is not None and current["high"] is not None and current["high"] < first["low"]:
                events.append({
                    "type": "bearish_fvg",
                    "lower": current["high"],
                    "upper": first["low"],
                    "formed_date": date,
                })

        if high is not None and low is not None and close is not None:
            # Sweep 使用當日開始前已確認的 swing level。
            if swing_high and not high_broken and high > swing_high["price"] and close <= swing_high["price"]:
                events.append({
                    "type": "buy_side_liquidity_sweep",
                    "level": swing_high["price"],
                    "swing_pivot_date": swing_high["pivot_date"],
                    "event_date": date,
                })
            if swing_low and not low_broken and low < swing_low["price"] and close >= swing_low["price"]:
                events.append({
                    "type": "sell_side_liquidity_sweep",
                    "level": swing_low["price"],
                    "swing_pivot_date": swing_low["pivot_date"],
                    "event_date": date,
                })

            break_direction = None
            break_level = None
            if swing_high and not high_broken and close > swing_high["price"]:
                break_direction, break_level = "bullish", swing_high
                high_broken = True
            elif swing_low and not low_broken and close < swing_low["price"]:
                break_direction, break_level = "bearish", swing_low
                low_broken = True

            if break_direction:
                event_type = (
                    "choch"
                    if trend not in ("neutral", break_direction)
                    else "bos"
                )
                event = {
                    "type": event_type,
                    "direction": break_direction,
                    "level": break_level["price"],
                    "swing_pivot_date": break_level["pivot_date"],
                    "event_date": date,
                }

                # 最近一根反向 K 棒作為簡化 OB；只在突破當日提供。
                start = max(0, index - ob_lookback)
                for candidate_index in range(index - 1, start - 1, -1):
                    candidate = bars[candidate_index]
                    candidate_close, candidate_open = candidate.get("close"), candidate.get("open")
                    if candidate_close is None or candidate_open is None:
                        continue
                    is_opposing = (
                        candidate_close < candidate_open
                        if break_direction == "bullish"
                        else candidate_close > candidate_open
                    )
                    if is_opposing:
                        event["order_block"] = {
                            "source_date": str(candidate["trade_date"]),
                            "high": candidate["high"],
                            "low": candidate["low"],
                            "identified_date": date,
                        }
                        break
                events.append(event)
                trend = break_direction

        output.append({
            "market": bar.get("market"),
            "stock_id": str(bar.get("stock_id", "")),
            "trade_date": bar["trade_date"],
            "structure_trend": trend,
            "events": events,
        })

    return output
