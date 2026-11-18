"""Fetch official daily margin/short data for the four pilot stocks.

Amounts are stored in the reporting unit used by the exchange endpoint.
TPEx is a latest-day snapshot and its Date must match the requested date.
"""
from __future__ import annotations
import argparse, os, re
from datetime import date
import psycopg
import requests

TWSE_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TaiwanStockResearch/1.0)"}
STOCKS = {"twse": {"6213", "4919", "7827"}, "tpex": {"8937"}}

def to_int(value):
    text = str(value if value is not None else "").replace(",", "").strip()
    if text in ("", "-", "--", "—", "None"):
        return 0
    if not re.fullmatch(r"[+-]?\d+(?:\\.0+)?", text):
        return None
    return int(float(text))

def roc_date(value):
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    if len(text) == 7 and text.isdigit():
        return f"{int(text[:3]) + 1911}-{text[3:5]}-{text[5:]}"
    return None

def _check_date(value, requested, source):
    actual = roc_date(value)
    if actual != requested:
        raise RuntimeError(f"{source} 日期不符：回傳 {actual or value!r}，要求 {requested}；拒絕寫入")

def _required(row, key, source):
    value = to_int(row.get(key))
    if value is None:
        raise RuntimeError(f"{source} 欄位 {key!r} 缺漏或格式改變")
    return value

def parse_twse(payload, trade_date):
    if payload.get("stat") != "OK":
        raise RuntimeError(f"TWSE MI_MARGN 無資料：{payload.get('stat')}")
    _check_date(payload.get("date"), trade_date, "TWSE MI_MARGN")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise RuntimeError("TWSE MI_MARGN data 格式異常")
    output = []
    fields = {
        "margin_buy": "融資買進", "margin_sell": "融資賣出",
        "margin_repayment": "融資現金償還", "margin_balance": "融資今日餘額",
        "short_buyback": "融券買進", "short_sell": "融券賣出",
        "short_repayment": "融券現券償還", "short_balance": "融券今日餘額",
    }
    quota_fields = {"margin_quota": "融資限額", "short_quota": "融券限額"}
    labels = payload.get("fields", [])
    if rows and isinstance(rows[0], list):
        if not isinstance(labels, list) or "證券代號" not in labels:
            raise RuntimeError("TWSE MI_MARGN 缺少 fields 欄位定義")
        for raw in rows:
            row = dict(zip(labels, raw))
            rows_dict = row
            code = str(rows_dict.get("證券代號", "")).strip()
            if code not in STOCKS["twse"]:
                continue
            values = {name: _required(rows_dict, key, f"TWSE {code}") for name, key in fields.items()}
            values.update({name: to_int(rows_dict.get(key)) for name, key in quota_fields.items()})
            output.append({"market": "twse", "stock_id": code, "trade_date": trade_date, **values})
    else:
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = str(row.get("股票代號", row.get("證券代號", ""))).strip()
            if code not in STOCKS["twse"]:
                continue
            values = {name: _required(row, key, f"TWSE {code}") for name, key in fields.items()}
            values.update({name: to_int(row.get(key)) for name, key in quota_fields.items()})
            output.append({"market": "twse", "stock_id": code, "trade_date": trade_date, **values})
    if {r["stock_id"] for r in output} != STOCKS["twse"]:
        raise RuntimeError("TWSE 目標股票資料不完整")
    return output

def parse_tpex(rows, trade_date):
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("TPEx margin balance API 回傳空資料")
    dates = {roc_date(row.get("Date")) for row in rows if isinstance(row, dict)}
    dates.discard(None)
    if dates != {trade_date}:
        raise RuntimeError(f"TPEx 僅提供最新快照，回傳日期 {sorted(dates)}，要求 {trade_date}；拒絕錯誤日期寫入")
    fields = {
        "margin_buy": "MarginPurchase", "margin_sell": "MarginSales",
        "margin_repayment": "CashRedemption", "margin_balance": "MarginPurchaseBalance",
        "short_buyback": "ShortConvering", "short_sell": "ShortSale",
        "short_repayment": "StockRedemption", "short_balance": "ShortSaleBalance",
    }
    quota_fields = {"margin_quota": ("MarginPurchaseLimit", "MarginPurchaseQuota"),
                    "short_quota": ("ShortSaleLimit", "ShortSaleQuota")}
    output = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("SecuritiesCompanyCode", "")).strip()
        if code not in STOCKS["tpex"]:
            continue
        values = {name: _required(row, key, f"TPEx {code}") for name, key in fields.items()}
        for name, candidates in quota_fields.items():
            values[name] = next((to_int(row.get(key)) for key in candidates if row.get(key) not in (None, "")), None)
        output.append({"market": "tpex", "stock_id": code, "trade_date": trade_date, **values})
    if {r["stock_id"] for r in output} != STOCKS["tpex"]:
        raise RuntimeError("TPEx 目標股票資料不完整")
    return output

def fetch_records(trade_date):
    session = requests.Session()
    twse = session.get(TWSE_URL, params={"date": trade_date.replace("-", ""), "selectType": "ALL", "response": "json"}, headers=HEADERS, timeout=30)
    twse.raise_for_status()
    tpex = session.get(TPEX_URL, headers=HEADERS, timeout=30)
    tpex.raise_for_status()
    return parse_twse(twse.json(), trade_date) + parse_tpex(tpex.json(), trade_date)

def save_records(records):
    sql = """
        INSERT INTO margin_short (
            market, stock_id, trade_date, margin_buy, margin_sell, margin_repayment,
            margin_balance, short_sell, short_buyback, short_repayment, short_balance,
            margin_quota, short_quota, source, retrieved_at
        ) VALUES (
            %(market)s, %(stock_id)s, %(trade_date)s, %(margin_buy)s, %(margin_sell)s,
            %(margin_repayment)s, %(margin_balance)s, %(short_sell)s, %(short_buyback)s,
            %(short_repayment)s, %(short_balance)s, %(margin_quota)s, %(short_quota)s,
            %(source)s, now()
        )
        ON CONFLICT (market, stock_id, trade_date) DO UPDATE SET
            margin_buy=EXCLUDED.margin_buy, margin_sell=EXCLUDED.margin_sell,
            margin_repayment=EXCLUDED.margin_repayment, margin_balance=EXCLUDED.margin_balance,
            short_sell=EXCLUDED.short_sell, short_buyback=EXCLUDED.short_buyback,
            short_repayment=EXCLUDED.short_repayment, short_balance=EXCLUDED.short_balance,
            margin_quota=EXCLUDED.margin_quota, short_quota=EXCLUDED.short_quota,
            source=EXCLUDED.source, retrieved_at=now()
    """
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            for record in records:
                record["source"] = "TWSE_MI_MARGN" if record["market"] == "twse" else "TPEX_tpex_mainboard_margin_balance"
                cur.execute(sql, record)
    return len(records)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="交易日期 YYYY-MM-DD")
    trade_date = date.fromisoformat(parser.parse_args().date).isoformat()
    records = fetch_records(trade_date)
    print(f"取得 {len(records)} 筆融資融券資料，交易日 {trade_date}")
    print(f"寫入 Neon：{save_records(records)} 筆")
    for row in records:
        print(row["market"], row["stock_id"], "融資餘額", row["margin_balance"], "融券餘額", row["short_balance"])

if __name__ == "__main__":
    main()
