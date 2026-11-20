"""Build and optionally push a daily Taiwan-stock data report through LINE."""
from __future__ import annotations

import argparse
import hashlib
import os
from datetime import date
from typing import Any

import psycopg
import requests
from psycopg.rows import dict_row

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


def load_report(database_url: str) -> dict[str, Any]:
    with psycopg.connect(database_url, connect_timeout=20, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(trade_date) AS trade_date FROM public.daily_prices")
            latest = cur.fetchone()["trade_date"]
            if latest is None:
                raise RuntimeError("daily_prices 尚無行情，無法產生通知")
            cur.execute("""
                SELECT market, COUNT(*) AS stocks
                FROM public.stock_master GROUP BY market ORDER BY market
            """)
            universe = {r["market"]: int(r["stocks"]) for r in cur.fetchall()}
            cur.execute("""
                SELECT market, COUNT(DISTINCT stock_id) AS stocks
                FROM public.daily_prices
                WHERE trade_date=%s AND close IS NOT NULL
                GROUP BY market ORDER BY market
            """, (latest,))
            prices = {r["market"]: int(r["stocks"]) for r in cur.fetchall()}
            # The price ingestion and composite-score jobs finish at different
            # times. Use the latest completed score date, never silently
            # mislabel yesterday's ratings as today's.
            cur.execute("""
                SELECT MAX(as_of_date) AS score_date
                FROM public.daily_composite_scores
                WHERE as_of_date <= %s AND total_score IS NOT NULL
            """, (latest,))
            score_date = cur.fetchone()["score_date"]
            cur.execute("""
                SELECT COUNT(*) AS rows,
                       COUNT(*) FILTER (WHERE total_score IS NOT NULL) AS scored,
                       COUNT(*) FILTER (WHERE chip_score IS NOT NULL
                           AND total_score IS NOT NULL) AS chip_integrated,
                       AVG(coverage_weight) FILTER (
                           WHERE total_score IS NOT NULL) AS avg_coverage
                FROM public.daily_composite_scores WHERE as_of_date=%s
            """, (score_date,))
            score_stats = cur.fetchone()
            cur.execute("""
                SELECT MAX(trade_date) AS latest_date, COUNT(*) AS rows
                FROM public.institutional_flows
                WHERE trade_date=(SELECT MAX(trade_date) FROM public.institutional_flows)
            """)
            institutional = cur.fetchone()
            cur.execute("""
                SELECT MAX(trade_date) AS latest_date, COUNT(*) AS rows
                FROM public.margin_short
                WHERE trade_date=(SELECT MAX(trade_date) FROM public.margin_short)
            """)
            margin = cur.fetchone()
            cur.execute("""
                SELECT p.market,p.stock_id,sm.stock_name,p.close,p.price_change,
                       c.total_score,c.short_term_score,c.swing_score,c.long_term_score,
                       c.coverage_weight,c.component_status
                FROM public.daily_prices p
                JOIN public.stock_master sm USING (market,stock_id)
                LEFT JOIN public.daily_composite_scores c
                  ON c.market=p.market AND c.stock_id=p.stock_id AND c.as_of_date=p.trade_date
                WHERE p.trade_date=%s AND p.close IS NOT NULL AND c.total_score IS NOT NULL
                ORDER BY c.total_score DESC, p.market, p.stock_id
                LIMIT 10
            """, (score_date,))
            top = cur.fetchall()
            cur.execute("""
                SELECT DISTINCT line_user_id
                FROM public.line_messages
                WHERE line_user_id IS NOT NULL AND message_type='text'
            """)
            recipients = [r["line_user_id"] for r in cur.fetchall()]
    return {
        "trade_date": latest, "score_date": score_date,
        "universe": universe, "prices": prices,
        "scores": dict(score_stats), "institutional": dict(institutional),
        "margin": dict(margin), "top": [dict(r) for r in top],
        "recipients": recipients,
    }


def _fmt_num(value: Any, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{float(value):,.{digits}f}"


def format_report(data: dict[str, Any]) -> str:
    trade_date = data["trade_date"]
    if isinstance(trade_date, date):
        trade_date = trade_date.isoformat()
    universe, prices = data["universe"], data["prices"]
    total_universe = sum(universe.values())
    total_prices = sum(prices.values())
    scores = data["scores"]
    score_date = data.get("score_date", data["trade_date"])
    if isinstance(score_date, date):
        score_date = score_date.isoformat()
    score_label = str(score_date) if score_date else "尚無可用評分"
    avg_cov = float(scores["avg_coverage"] or 0) * 100
    inst = data["institutional"]
    margin = data["margin"]

    lines = [
        "AI 台股投資作戰系統｜每日資料報告",
        f"行情交易日：{trade_date}",
        f"綜合評分資料日：{score_label}",
        "",
        f"行情覆蓋：{total_prices:,}/{total_universe:,} 檔股票",
        f"  上市：{prices.get('twse', 0):,}/{universe.get('twse', 0):,}",
        f"  上櫃：{prices.get('tpex', 0):,}/{universe.get('tpex', 0):,}",
        f"已評分：{int(scores['scored'] or 0):,} 檔；平均因子覆蓋率：{avg_cov:.0f}%",
        (f"籌碼因子已納入：{int(scores['chip_integrated'])} 檔" if int(scores["chip_integrated"] or 0) > 0 else "籌碼因子尚未達可用門檻，暫不納入總分"),
        f"三大法人：{inst['latest_date'] or '無資料'}，{int(inst['rows'] or 0):,} 筆",
        f"融資融券：{margin['latest_date'] or '無資料'}，{int(margin['rows'] or 0):,} 筆",
        "",
        "綜合分數觀察名單（非買賣指令）：",
    ]
    if not data["top"]:
        lines.append("目前沒有符合條件且有完整收盤價的評分資料。")
    else:
        for i, row in enumerate(data["top"], 1):
            market = "上市" if row["market"] == "twse" else "上櫃"
            change = row["price_change"]
            change_text = "—" if change is None else f"{float(change):+.2f}"
            lines.append(
                f"{i}. {row['stock_id']} {row['stock_name']}（{market}）"
                f" 收盤 {_fmt_num(row['close'], 2)} 漲跌 {change_text}"
                f"｜總分 {_fmt_num(row['total_score'])}"
                f" 短/波/長 {_fmt_num(row['short_term_score'])}/"
                f"{_fmt_num(row['swing_score'])}/{_fmt_num(row['long_term_score'])}"
            )
    if score_date and str(score_date) != str(trade_date):
        lines += [
            "",
            "注意：最新評分與最新行情不是同一交易日；清單收盤價採評分當日資料。",
        ]
    lines += [
        "",
        "注意：目前日 K 僅覆蓋部分股票；分數不是獲利保證或自動交易指令。",
        "資料可能因交易所公告時間而延遲，請以官方公告及最新資料日期為準。",
    ]
    message = "\n".join(lines)
    if len(message) > 4900:
        raise RuntimeError("LINE 報告超過單則訊息長度限制")
    return message


def _already_sent(conn, event_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM public.line_messages WHERE event_id=%s", (event_id,))
        return cur.fetchone() is not None


def send_report(database_url: str, token: str, data: dict[str, Any], message: str) -> int:
    if not token:
        raise RuntimeError("缺少 LINE_CHANNEL_ACCESS_TOKEN；請在 GitHub Actions Secrets 設定")
    if not data["recipients"]:
        raise RuntimeError("line_messages 沒有可通知的 LINE 使用者；請先傳訊息給官方帳號")
    sent = 0
    with psycopg.connect(database_url, connect_timeout=20) as conn:
        for user_id in data["recipients"]:
            digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:16]
            event_id = f"daily-report:{data['trade_date']}:{digest}"
            if _already_sent(conn, event_id):
                print(f"已發送過 {data['trade_date']} 每日報告，略過一位收件者")
                continue
            response = requests.post(
                LINE_PUSH_URL,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"to": user_id, "messages": [{"type": "text", "text": message}]},
                timeout=30,
            )
            if response.status_code >= 300:
                raise RuntimeError(
                    f"LINE Push API 失敗：HTTP {response.status_code}；"
                    "請確認 Channel Access Token、好友狀態與 LINE 配額"
                )
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO public.line_messages
                      (event_id,line_user_id,message_type,message_text)
                    VALUES (%s,%s,'outgoing_daily_report',%s)
                    ON CONFLICT (event_id) DO NOTHING
                """, (event_id, user_id, message))
            conn.commit()
            sent += 1
    return sent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只產生報告，不推送 LINE")
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("缺少 DATABASE_URL")
    data = load_report(database_url)
    message = format_report(data)
    print(message)
    if args.dry_run:
        print("\nDRY RUN：未發送 LINE。")
        return
    sent = send_report(database_url, os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", ""), data, message)
    print(f"LINE 每日報告已送出：{sent} 位收件者")


if __name__ == "__main__":
    main()
