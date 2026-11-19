"""Rule-based Smart Money Concepts (SMC) indicators for daily OHLC bars.

Swing points are only exposed after right-side confirmation, preventing look-ahead
bias. BOS/CHOCH, order blocks, fair-value gaps and liquidity sweeps are heuristics,
not a claim about institutional orders or guaranteed trading signals.
"""
from __future__ import annotations

from typing import Any, Iterable

try:
    from .ohlc_quality import classify_ohlc_row
except ImportError:  # 支援以 src/ 作為 PYTHONPATH 的 GitHub Actions 執行方式
    from ohlc_quality import classify_ohlc_row

def _valid_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _pivot(values: list[float | None], index: int, left: int, right: int, high: bool) -> bool:
    candidate = values[index]
    if candidate is None or index < left or index + right >= len(values):
        return False
    window = values[index-left:index+right+1]
    if any(value is None for value in window):
        return False
    peers = window[:left] + window[left+1:]
    return all(candidate > value for value in peers) if high else all(candidate < value for value in peers)


def compute_smc(
    rows: Iterable[dict[str, Any]],
    swing_left: int = 3,
    swing_right: int = 3,
    ob_lookback: int = 20,
) -> list[dict[str, Any]]:
    """Input one stock's daily bars in strictly ascending trade_date order."""
    source = list(rows)
    if swing_left < 1 or swing_right < 1 or ob_lookback < 1:
        raise ValueError("swing_left、swing_right、ob_lookback 必須大於 0")
    dates: list[str] = []
    opens: list[float | None] = []
    highs: list[float | None] = []
    lows: list[float | None] = []
    closes: list[float | None] = []
    for row in source:
        date = str(row["trade_date"])
        if dates and date <= dates[-1]:
            raise ValueError("日 K 必須依 trade_date 嚴格遞增且不可重複")
        dates.append(date)
        quality = classify_ohlc_row(row)
        if quality.eligible_for_indicators:
            o, h, l, c = (_valid_number(row.get(k)) for k in ("open","high","low","close"))
        else:
            o = h = l = c = None
        if None not in (o,h,l,c) and (h < l or h < max(o,c) or l > min(o,c)):
            raise ValueError(f"{date} OHLC 價格關係不合理")
        opens.append(o); highs.append(h); lows.append(l); closes.append(c)

    result: list[dict[str, Any]] = []
    last_swing_high: float | None = None
    last_swing_low: float | None = None
    previous_close: float | None = None
    trend = 0  # 1 bullish, -1 bearish, 0 not established
    for i, row in enumerate(source):
        confirmed_high = confirmed_low = None
        # 缺價／無效 OHLC 是結構斷點：不跨越缺口產生 BOS/CHOCH、掃流動性或 FVG。
        if None in (opens[i], highs[i], lows[i], closes[i]):
            last_swing_high = last_swing_low = None
            previous_close = None
            trend = 0
            result.append({
                "market": row["market"], "stock_id": str(row["stock_id"]), "trade_date": row["trade_date"],
                "swing_high": None, "swing_low": None,
                "bos_bullish": False, "bos_bearish": False,
                "choch_bullish": False, "choch_bearish": False,
                "trend_direction": 0,
                "liquidity_sweep_high": False, "liquidity_sweep_low": False,
                "order_block_type": None, "order_block_high": None, "order_block_low": None,
                "fvg_type": None, "fvg_high": None, "fvg_low": None,
            })
            continue
        candidate = i - swing_right
        if candidate >= swing_left:
            if _pivot(highs, candidate, swing_left, swing_right, True):
                confirmed_high = highs[candidate]
                last_swing_high = confirmed_high
            if _pivot(lows, candidate, swing_left, swing_right, False):
                confirmed_low = lows[candidate]
                last_swing_low = confirmed_low

        close, high, low = closes[i], highs[i], lows[i]
        bullish_break = bool(close is not None and previous_close is not None and last_swing_high is not None
                             and previous_close <= last_swing_high < close)
        bearish_break = bool(close is not None and previous_close is not None and last_swing_low is not None
                             and previous_close >= last_swing_low > close)
        bullish_choch = bullish_break and trend == -1
        bearish_choch = bearish_break and trend == 1
        bullish_bos = bullish_break and not bullish_choch
        bearish_bos = bearish_break and not bearish_choch
        if bullish_break:
            trend = 1
        elif bearish_break:
            trend = -1

        bullish_sweep = bool(high is not None and close is not None and last_swing_high is not None
                             and high > last_swing_high and close < last_swing_high)
        bearish_sweep = bool(low is not None and close is not None and last_swing_low is not None
                             and low < last_swing_low and close > last_swing_low)

        ob_high = ob_low = None
        ob_type = None
        if bullish_break or bearish_break:
            start = max(0, i - ob_lookback)
            for j in range(i - 1, start - 1, -1):
                if None in (opens[j], closes[j], highs[j], lows[j]):
                    continue
                opposite = (bullish_break and closes[j] < opens[j]) or (bearish_break and closes[j] > opens[j])
                if opposite:
                    ob_type = "bullish" if bullish_break else "bearish"
                    ob_high, ob_low = highs[j], lows[j]
                    break

        fvg_type = None
        fvg_high = fvg_low = None
        if i >= 2 and None not in (highs[i-2], lows[i-2], highs[i], lows[i]):
            if lows[i] > highs[i-2]:
                fvg_type, fvg_high, fvg_low = "bullish", lows[i], highs[i-2]
            elif highs[i] < lows[i-2]:
                fvg_type, fvg_high, fvg_low = "bearish", lows[i-2], highs[i]

        result.append({
            "market": row["market"], "stock_id": str(row["stock_id"]), "trade_date": row["trade_date"],
            "swing_high": confirmed_high, "swing_low": confirmed_low,
            "bos_bullish": bullish_bos, "bos_bearish": bearish_bos,
            "choch_bullish": bullish_choch, "choch_bearish": bearish_choch,
            "trend_direction": trend,
            "liquidity_sweep_high": bullish_sweep, "liquidity_sweep_low": bearish_sweep,
            "order_block_type": ob_type, "order_block_high": ob_high, "order_block_low": ob_low,
            "fvg_type": fvg_type, "fvg_high": fvg_high, "fvg_low": fvg_low,
        })
        if close is not None:
            previous_close = close
    return result
