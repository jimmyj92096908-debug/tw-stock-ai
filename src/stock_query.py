"""LINE stock lookup and analysis response helpers (read-only, parameterized)."""
from __future__ import annotations

from typing import Any


def normalize_query(text: str) -> str:
    value = (text or "").strip()
    for prefix in ("分析", "查詢", "股票"):
        if value.startswith(prefix):
            value = value[len(prefix):].strip()
            break
    return value


def resolve_stock(conn: Any, user_text: str, limit: int = 6) -> list[dict[str, Any]]:
    """Resolve exact code/name first, then partial name; return candidates."""
    query = normalize_query(user_text)
    if not query or len(query) > 30:
        return []
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT market, stock_id, stock_name, industry
            FROM stock_master
            WHERE stock_id = %s OR stock_name = %s
            ORDER BY CASE WHEN stock_id = %s THEN 0 ELSE 1 END, market
            LIMIT %s
            """,
            (query, query, query, limit),
        )
        rows = _rows(cursor)
        if rows:
            return rows
        cursor.execute(
            """
            SELECT market, stock_id, stock_name, industry
            FROM stock_master
            WHERE stock_name ILIKE %s
            ORDER BY stock_id, market
            LIMIT %s
            """,
            (f"%{query}%", limit),
        )
        return _rows(cursor)
    finally:
        cursor.close()


def fetch_latest_analysis(conn: Any, market: str, stock_id: str) -> dict[str, Any] | None:
    """Fetch latest available bar and same/previously available analysis records."""
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            WITH latest_price AS (
              SELECT p.*
              FROM daily_prices p
              WHERE p.market = %s AND p.stock_id = %s
              ORDER BY p.trade_date DESC
              LIMIT 1
            )
            SELECT
              p.market, p.stock_id, p.trade_date, p.open, p.high, p.low,
              p.close, p.volume, p.price_change, p.turnover,
              sm.stock_name, sm.industry,
              t.ma5, t.ma10, t.ma13, t.ma20, t.ma34, t.ma55, t.ma60,
              t.ma120, t.ma240, t.rsi14, t.volume_ma5, t.volume_ma20, t.atr14,
              s.trend_direction, s.bos_bullish, s.bos_bearish,
              s.choch_bullish, s.choch_bearish,
              s.liquidity_sweep_high, s.liquidity_sweep_low,
              s.order_block_type, s.order_block_high, s.order_block_low,
              s.fvg_type, s.fvg_high, s.fvg_low,
              c.total_score, c.technical_score, c.smc_score, c.chip_score,
              c.short_term_score, c.swing_score, c.long_term_score,
              c.coverage_weight, c.short_coverage, c.swing_coverage, c.long_coverage,
              c.component_status,
              f.foreign_net, f.trust_net, f.dealer_net, f.total_net,
              f.trade_date AS flow_date,
              m.margin_balance, m.short_balance, m.margin_buy, m.margin_sell,
              m.short_sell, m.short_buyback, m.trade_date AS margin_date
            FROM latest_price p
            LEFT JOIN stock_master sm
              ON sm.market = p.market AND sm.stock_id = p.stock_id
            LEFT JOIN daily_technicals t
              ON t.market = p.market AND t.stock_id = p.stock_id AND t.trade_date = p.trade_date
            LEFT JOIN daily_smc s
              ON s.market = p.market AND s.stock_id = p.stock_id AND s.trade_date = p.trade_date
            LEFT JOIN daily_composite_scores c
              ON c.market = p.market AND c.stock_id = p.stock_id AND c.as_of_date = p.trade_date
            LEFT JOIN LATERAL (
              SELECT *
              FROM institutional_flows x
              WHERE x.market = p.market AND x.stock_id = p.stock_id
                AND x.trade_date <= p.trade_date
              ORDER BY x.trade_date DESC LIMIT 1
            ) f ON TRUE
            LEFT JOIN LATERAL (
              SELECT *
              FROM margin_short x
              WHERE x.market = p.market AND x.stock_id = p.stock_id
                AND x.trade_date <= p.trade_date
              ORDER BY x.trade_date DESC LIMIT 1
            ) m ON TRUE
            """,
            (market, str(stock_id)),
        )
        rows = _rows(cursor)
        return rows[0] if rows else None
    finally:
        cursor.close()


def _rows(cursor: Any) -> list[dict[str, Any]]:
    rows = cursor.fetchall()
    if not rows:
        return []
    if isinstance(rows[0], dict):
        return rows
    names = [col[0] for col in cursor.description]
    return [dict(zip(names, row)) for row in rows]


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
        return f"{number:,.{digits}f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def _flag(value: Any) -> str:
    return "是" if value else "否"


def format_analysis_message(row: dict[str, Any]) -> str:
    """Format a concise Traditional Chinese LINE response; not a trade signal."""
    name = row.get("stock_name") or row.get("stock_id")
    date = row.get("trade_date") or "日期未知"
    change = row.get("price_change")
    price = _fmt(row.get("close"))
    change_text = "—" if change is None else f"{_fmt(change)}"
    ma_keys = ("ma5", "ma10", "ma13", "ma20", "ma34", "ma55", "ma60", "ma120", "ma240")
    ma_text = " / ".join(_fmt(row.get(key)) for key in ma_keys)
    volume_ratio = None
    if row.get("volume") is not None and row.get("volume_ma20"):
        volume_ratio = float(row["volume"]) / float(row["volume_ma20"])
    smc_trend = {1: "偏多", -1: "偏空", 0: "盤整"}.get(row.get("trend_direction"), "缺資料")
    lines = [
        f"{name}（{row.get('stock_id')}）｜{row.get('market')}",
        f"資料日期：{date}",
        f"收盤：{price}｜漲跌：{change_text}",
        f"九均線 MA5/10/13/20/34/55/60/120/240：{ma_text}",
        f"RSI14：{_fmt(row.get('rsi14'))}｜量/20日均量：{_fmt(volume_ratio)}倍",
        f"SMC趨勢：{smc_trend}｜BOS↑/↓：{_flag(row.get('bos_bullish'))}/{_flag(row.get('bos_bearish'))}",
        f"CHOCH↑/↓：{_flag(row.get('choch_bullish'))}/{_flag(row.get('choch_bearish'))}",
        f"掃高/掃低：{_flag(row.get('liquidity_sweep_high'))}/{_flag(row.get('liquidity_sweep_low'))}",
        f"FVG：{row.get('fvg_type') or '缺資料'}｜OB：{row.get('order_block_type') or '缺資料'}",
        f"法人淨額（外資/投信/自營）：{_fmt(row.get('foreign_net'),0)}/{_fmt(row.get('trust_net'),0)}/{_fmt(row.get('dealer_net'),0)}（{row.get('flow_date') or '缺資料'}）",
        f"融資餘額：{_fmt(row.get('margin_balance'),0)}｜融券餘額：{_fmt(row.get('short_balance'),0)}（{row.get('margin_date') or '缺資料'}）",
        f"評分 短/波段/長：{_fmt(row.get('short_term_score'))}/{_fmt(row.get('swing_score'))}/{_fmt(row.get('long_term_score'))}",
        f"總分：{_fmt(row.get('total_score'))}｜覆蓋率：{_fmt(float(row.get('coverage_weight') or 0)*100,1)}%",
        "註：僅供研究參考，不構成買賣建議；缺值代表資料尚未提供。",
    ]
    return chr(10).join(lines)
