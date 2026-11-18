"""Fetch daily institutional flows from official TWSE and TPEx sources.

All quantities are shares (股). Missing/invalid source data is never converted
to zero. The script writes only rows matching the existing stock_master universe.
"""
from __future__ import annotations

import argparse
import logging
import re
import time
from datetime import date, datetime
from typing import Any


TWSE_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"
TIMEOUT_SECONDS = 30
REQUEST_INTERVAL_SECONDS = 1.0
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; tw-stock-ai/0.1)",
    "Accept": "application/json",
}
logger = logging.getLogger(__name__)


def parse_number(value: Any) -> int | None:
    if value is None:
        return None
    raw = str(value).strip().replace(",", "").replace("股", "")
    if raw in {"", "--", "---", "-", "X", "N/A"}:
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError, OverflowError):
        return None


def _norm(value: Any) -> str:
    return re.sub(r"[\s\u3000()（）\[\]【】_\-：:，,]+", "", str(value)).lower()


def _find_value(row: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    normalized = {_norm(key): value for key, value in row.items()}
    for alias in aliases:
        key = _norm(alias)
        if key in normalized:
            return normalized[key]
    for alias in aliases:
        key = _norm(alias)
        for actual, value in normalized.items():
            if key and key in actual:
                return value
    return None


def _record(market: str, stock_id: Any, trade_date: date,
            foreign_buy: Any, foreign_sell: Any, trust_buy: Any, trust_sell: Any,
            dealer_buy: Any, dealer_sell: Any, total_net: Any, source: str,
            foreign_net: Any = None, trust_net: Any = None, dealer_net: Any = None) -> dict[str, Any] | None:
    code = str(stock_id).strip()
    if not re.fullmatch(r"\d{4,6}", code):
        return None
    values = [parse_number(v) for v in (
        foreign_buy, foreign_sell, trust_buy, trust_sell, dealer_buy, dealer_sell, total_net
    )]
    fb, fs, tb, ts, db, ds, tn = values
    if all(value is None for value in values):
        return None
    # Do not invent zero when a source field is absent.
    return {
        "market": market, "stock_id": code, "trade_date": trade_date,
        "foreign_buy": fb, "foreign_sell": fs,
        "foreign_net": parse_number(foreign_net) if foreign_net is not None else (fb - fs if fb is not None and fs is not None else None),
        "trust_buy": tb, "trust_sell": ts,
        "trust_net": parse_number(trust_net) if trust_net is not None else (tb - ts if tb is not None and ts is not None else None),
        "dealer_buy": db, "dealer_sell": ds,
        "dealer_net": parse_number(dealer_net) if dealer_net is not None else (db - ds if db is not None and ds is not None else None),
        "total_net": tn, "source": source,
    }


def _payload_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if not isinstance(payload, dict):
        raise ValueError("官方 API 回傳格式不是 JSON object/list")
    if payload.get("stat") not in (None, "OK", "ok", "成功"):
        logger.info("官方 API 無資料或非交易日：%s", payload.get("stat"))
        return []
    if isinstance(payload.get("data"), list):
        fields = payload.get("fields") or payload.get("titles") or []
        if fields and payload["data"] and not isinstance(payload["data"][0], dict):
            return [dict(zip(fields, row)) for row in payload["data"] if len(row) == len(fields)]
        return [r for r in payload["data"] if isinstance(r, dict)]
    for table in payload.get("tables", []):
        fields = table.get("fields") or table.get("titles") or []
        data = table.get("data") or []
        if fields and data:
            if isinstance(data[0], dict):
                return data
            return [dict(zip(fields, row)) for row in data if len(row) == len(fields)]
    return []


def parse_twse(payload: Any, trade_date: date) -> list[dict[str, Any]]:
    records = []
    for row in _payload_rows(payload):
        code = _find_value(row, ("證券代號", "證券代碼", "Code", "Security Code"))
        records.append(_record(
            "twse", code, trade_date,
            _find_value(row, ("外陸資買進股數(不含外資自營商)", "外陸資買進股數", "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Total Buy")),
            _find_value(row, ("外陸資賣出股數(不含外資自營商)", "外陸資賣出股數", "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Total Sell")),
            _find_value(row, ("投信買進股數", "Securities Investment Trust Companies-Total Buy")),
            _find_value(row, ("投信賣出股數", "Securities Investment Trust Companies-Total Sell")),
            _dealer_total(row, "buy"), _dealer_total(row, "sell"),
            _find_value(row, ("三大法人買賣超股數", "三大法人買賣超", "Total Difference")),
            "TWSE_T86",
        ))
    return [r for r in records if r is not None]


def _dealer_total(row: dict[str, Any], side: str) -> int | None:
    labels = (
        ("自營商買進股數(自行買賣)", "自營商買進股數(避險)", "自營商買進股數"),
        ("自營商賣出股數(自行買賣)", "自營商賣出股數(避險)", "自營商賣出股數"),
    )[0 if side == "buy" else 1]
    values = [parse_number(_find_value(row, (label,))) for label in labels[:2]]
    if all(v is None for v in values):
        direct = parse_number(_find_value(row, (labels[2],)))
        return direct
    return sum(v or 0 for v in values)


def parse_tpex(payload: Any, trade_date: date) -> list[dict[str, Any]]:
    records = []
    for row in _payload_rows(payload):
        # TPEx OpenAPI returns its own date in ROC calendar (e.g. 1151118).
        # Never label a latest-day snapshot as a different requested date.
        source_date = _find_value(row, ("Date", "資料日期", "交易日期"))
        if source_date not in (None, ""):
            digits = re.sub(r"\\D", "", str(source_date))
            if len(digits) == 7:
                source_ad_date = date(int(digits[:3]) + 1911, int(digits[3:5]), int(digits[5:7]))
            elif len(digits) == 8:
                source_ad_date = date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
            else:
                continue
            if source_ad_date != trade_date:
                continue
        code = _find_value(row, ("SecuritiesCompanyCode", "證券代號", "代號", "Code"))
        records.append(_record(
            "tpex", code, trade_date,
            _find_value(row, ("Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Total Buy",
                              "Foreign Investors-Total Buy", "外資及陸資買進股數")),
            _find_value(row, ("Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Total Sell",
                              "Foreign Investors-Total Sell", "外資及陸資賣出股數")),
            _find_value(row, ("SecuritiesInvestmentTrustCompanies-TotalBuy",
                              "Securities Investment Trust Companies-Total Buy", "投信買進股數")),
            _find_value(row, ("SecuritiesInvestmentTrustCompanies-TotalSell",
                              "Securities Investment Trust Companies-Total Sell", "投信賣出股數")),
            _find_value(row, ("Dealers-TotalBuy", "Dealers-Total Buy", "自營商買進股數")),
            _find_value(row, ("Dealers-TotalSell", "Dealers-Total Sell", "自營商賣出股數")),
            _find_value(row, ("TotalDifference", "Total Difference", "三大法人買賣超股數")),
            "TPEX_DAILY_TRADE",
            foreign_net=_find_value(row, (
                "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference",
                "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded) - Difference",
            )),
            trust_net=_find_value(row, (
                "SecuritiesInvestmentTrustCompanies-Difference",
                "Securities Investment Trust Companies-Difference",
            )),
            dealer_net=_find_value(row, ("Dealers-Difference", "Dealers - Difference")),
        ))
    return [r for r in records if r is not None]


def fetch_for_date(trade_date: date, session: Any = None) -> list[dict[str, Any]]:
    import requests
    client = session or requests.Session()
    date_text = trade_date.strftime("%Y%m%d")
    twse = client.get(TWSE_URL, params={
        "response": "json", "date": date_text, "selectType": "ALLBUT0999"
    }, headers=HEADERS, timeout=TIMEOUT_SECONDS)
    twse.raise_for_status()
    twse_rows = parse_twse(twse.json(), trade_date)
    time.sleep(REQUEST_INTERVAL_SECONDS)
    # Official TPEx OpenAPI is a latest-day snapshot; it has no historical
    # date parameter. parse_tpex validates each row's own Date field.
    tpex = client.get(TPEX_URL, headers=HEADERS, timeout=TIMEOUT_SECONDS)
    tpex.raise_for_status()
    tpex_rows = parse_tpex(tpex.json(), trade_date)
    logger.info("法人資料 %s：TWSE %s 檔，TPEx %s 檔", trade_date, len(twse_rows), len(tpex_rows))
    return twse_rows + tpex_rows


def sync_rows(rows: list[dict[str, Any]], database_url: str) -> int:
    import psycopg

    if not rows:
        return 0
    sql = """
    INSERT INTO public.institutional_flows (
        market, stock_id, trade_date, foreign_buy, foreign_sell, foreign_net,
        trust_buy, trust_sell, trust_net, dealer_buy, dealer_sell, dealer_net,
        total_net, source, retrieved_at
    )
    SELECT %(market)s::text, %(stock_id)s::varchar, %(trade_date)s::date, %(foreign_buy)s, %(foreign_sell)s,
           %(foreign_net)s, %(trust_buy)s, %(trust_sell)s, %(trust_net)s,
           %(dealer_buy)s, %(dealer_sell)s, %(dealer_net)s, %(total_net)s,
           %(source)s, NOW()
    WHERE EXISTS (
        SELECT 1 FROM public.stock_master
        WHERE market = %(market)s::text AND stock_id = %(stock_id)s::varchar
    )
    ON CONFLICT (market, stock_id, trade_date) DO UPDATE SET
        foreign_buy = EXCLUDED.foreign_buy, foreign_sell = EXCLUDED.foreign_sell,
        foreign_net = EXCLUDED.foreign_net, trust_buy = EXCLUDED.trust_buy,
        trust_sell = EXCLUDED.trust_sell, trust_net = EXCLUDED.trust_net,
        dealer_buy = EXCLUDED.dealer_buy, dealer_sell = EXCLUDED.dealer_sell,
        dealer_net = EXCLUDED.dealer_net, total_net = EXCLUDED.total_net,
        source = EXCLUDED.source, retrieved_at = NOW()
    """
    with psycopg.connect(database_url, connect_timeout=20) as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
            return cur.rowcount


def main() -> None:
    parser = argparse.ArgumentParser(description="同步 TWSE/TPEx 每日三大法人買賣超")
    parser.add_argument("--date", help="交易日期 YYYY-MM-DD；預設今天")
    args = parser.parse_args()
    trade_date = date.fromisoformat(args.date) if args.date else date.today()
    import os
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL 未設定，停止執行。")
    rows = fetch_for_date(trade_date)
    if not rows:
        logger.warning("%s 沒有法人資料；不寫入空白或零值。", trade_date)
        return
    count = sync_rows(rows, database_url)
    logger.info("法人資料同步完成：取得 %s 筆，符合 stock_master 並寫入 %s 筆", len(rows), count)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
