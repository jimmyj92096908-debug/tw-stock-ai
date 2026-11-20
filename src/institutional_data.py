"""Fetch official daily institutional flows for selected TWSE/TPEx stocks.

All quantities are shares (股). TPEx OpenAPI is a latest-day snapshot; the
requested date is checked against its Date field to prevent misdated imports.
"""
from __future__ import annotations

import argparse
import os
import re
from datetime import date
from typing import Any

import psycopg
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

TWSE_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TaiwanStockResearch/1.0)"}


def _session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=4, connect=4, read=4, backoff_factor=2,
                  status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=frozenset({"GET"}),
                  respect_retry_after_header=True)
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session
STOCKS = {"twse": {"2330", "6213", "4919", "7827"}, "tpex": {"8937"}}

TWSE_FIELDS = {
    "foreign_buy": "外陸資買進股數(不含外資自營商)",
    "foreign_sell": "外陸資賣出股數(不含外資自營商)",
    "foreign_net": "外陸資買賣超股數(不含外資自營商)",
    "trust_buy": "投信買進股數",
    "trust_sell": "投信賣出股數",
    "trust_net": "投信買賣超股數",
    "dealer_self_buy": "自營商買進股數(自行買賣)",
    "dealer_self_sell": "自營商賣出股數(自行買賣)",
    "dealer_hedge_buy": "自營商買進股數(避險)",
    "dealer_hedge_sell": "自營商賣出股數(避險)",
    "dealer_net": "自營商買賣超股數",
    "total_net": "三大法人買賣超股數",
}
TPEX_BASES = {
    "foreign": "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)",
    "trust": "SecuritiesInvestmentTrustCompanies",
    "dealer": "Dealers",
}


def to_int(value: Any) -> int | None:
    text = str(value if value is not None else "").replace(",", "").strip()
    if text in ("", "-", "--", "—", "None"):
        return None
    if not re.fullmatch(r"[+-]?\d+(?:\.0+)?", text):
        return None
    return int(float(text))


def ad_date(value: Any) -> str | None:
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    if len(text) == 7 and text.isdigit():
        return f"{int(text[:3]) + 1911}-{text[3:5]}-{text[5:]}"
    return None


def _norm_key(value: str) -> str:
    return " ".join(str(value).split())


def parse_twse(payload: dict, trade_date: str) -> list[dict]:
    if payload.get("stat") != "OK":
        raise RuntimeError(f"TWSE T86 無資料或非交易日：{payload.get('stat')}")
    fields = [_norm_key(x) for x in payload.get("fields", [])]
    required = [_norm_key(x) for x in TWSE_FIELDS.values()]
    missing = [x for x in required if x not in fields]
    if missing:
        raise RuntimeError(f"TWSE T86 欄位變更，缺少：{missing}")
    indices = {name: fields.index(_norm_key(label)) for name, label in TWSE_FIELDS.items()}
    code_idx = fields.index("證券代號")
    output = []
    for row in payload.get("data", []):
        code = str(row[code_idx]).strip()
        if code not in STOCKS["twse"]:
            continue
        values = {name: to_int(row[idx]) for name, idx in indices.items()}
        if any(values[k] is None for k in ("foreign_net", "trust_net", "dealer_net", "total_net")):
            raise RuntimeError(f"TWSE {code} 買賣超欄位無法解析")
        self_buy, hedge_buy = values.pop("dealer_self_buy"), values.pop("dealer_hedge_buy")
        self_sell, hedge_sell = values.pop("dealer_self_sell"), values.pop("dealer_hedge_sell")
        values["dealer_buy"] = self_buy + hedge_buy if self_buy is not None and hedge_buy is not None else None
        values["dealer_sell"] = self_sell + hedge_sell if self_sell is not None and hedge_sell is not None else None
        output.append({"market": "twse", "stock_id": code, "trade_date": trade_date, **values})
    return output


def parse_tpex(rows: list, trade_date: str) -> list[dict]:
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("TPEx 三大法人 API 回傳空資料")
    dated = {ad_date(row.get("Date")) for row in rows if isinstance(row, dict)}
    dated.discard(None)
    if dated != {trade_date}:
        raise RuntimeError(f"TPEx API 僅提供最新快照，回傳日期 {sorted(dated)}，與指定日期 {trade_date} 不符；拒絕錯誤日期寫入")
    output = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("SecuritiesCompanyCode", "")).strip()
        if code not in STOCKS["tpex"]:
            continue
        # TPEx field labels are inconsistent: some use "Total Buy", others
        # "TotalBuy", and a few begin with whitespace. Compact whitespace
        # before matching so these official variants map to the same field.
        compact = {"".join(str(k).split()): v for k, v in row.items()}
        def val(base: str, suffix: str) -> int | None:
            key = "".join(f"{base}-{suffix}".split())
            return to_int(compact.get(key))
        foreign_buy, foreign_sell, foreign_net = (val(TPEX_BASES["foreign"], x) for x in ("TotalBuy", "TotalSell", "Difference"))
        trust_buy, trust_sell, trust_net = (val(TPEX_BASES["trust"], x) for x in ("TotalBuy", "TotalSell", "Difference"))
        dealer_buy, dealer_sell, dealer_net = (val(TPEX_BASES["dealer"], x) for x in ("TotalBuy", "TotalSell", "Difference"))
        total_net = to_int(row.get("TotalDifference"))
        if any(v is None for v in (
            foreign_buy, foreign_sell, foreign_net,
            trust_buy, trust_sell, trust_net,
            dealer_buy, dealer_sell, dealer_net, total_net,
        )):
            raise RuntimeError(f"TPEx {code} 三大法人買進、賣出或買賣超欄位缺漏／格式變更")
        if foreign_net + trust_net + dealer_net != total_net:
            raise RuntimeError(f"TPEx {code} 三大法人分項加總與官方合計不一致")
        output.append({
            "market": "tpex", "stock_id": code, "trade_date": trade_date,
            "foreign_buy": foreign_buy, "foreign_sell": foreign_sell, "foreign_net": foreign_net,
            "trust_buy": trust_buy, "trust_sell": trust_sell, "trust_net": trust_net,
            "dealer_buy": dealer_buy, "dealer_sell": dealer_sell, "dealer_net": dealer_net,
            "total_net": total_net,
        })
    return output


def fetch_records(trade_date: str) -> list[dict]:
    session = _session()
    twse = session.get(
        TWSE_URL,
        params={"date": trade_date.replace("-", ""), "selectType": "ALL", "response": "json"},
        headers=HEADERS, timeout=(15, 60),
    )
    twse.raise_for_status()
    twse_rows = parse_twse(twse.json(), trade_date)

    # This TPEx endpoint is a latest-day snapshot, not a historical date API.
    tpex = session.get(TPEX_URL, headers=HEADERS, timeout=(15, 60))
    tpex.raise_for_status()
    tpex_rows = parse_tpex(tpex.json(), trade_date)

    for market, expected in STOCKS.items():
        got = {r["stock_id"] for r in (twse_rows if market == "twse" else tpex_rows)}
        if got != expected:
            raise RuntimeError(f"{market} 目標股票資料不完整；預期 {sorted(expected)}，實際 {sorted(got)}")
    return twse_rows + tpex_rows


def save_records(records: list[dict]) -> int:
    sql = """
        INSERT INTO institutional_flows (
            market, stock_id, trade_date, foreign_buy, foreign_sell, foreign_net,
            trust_buy, trust_sell, trust_net, dealer_buy, dealer_sell, dealer_net,
            total_net, source, retrieved_at
        ) VALUES (
            %(market)s, %(stock_id)s, %(trade_date)s, %(foreign_buy)s, %(foreign_sell)s,
            %(foreign_net)s, %(trust_buy)s, %(trust_sell)s, %(trust_net)s,
            %(dealer_buy)s, %(dealer_sell)s, %(dealer_net)s, %(total_net)s,
            %(source)s, now()
        )
        ON CONFLICT (market, stock_id, trade_date) DO UPDATE SET
            foreign_buy=EXCLUDED.foreign_buy, foreign_sell=EXCLUDED.foreign_sell,
            foreign_net=EXCLUDED.foreign_net, trust_buy=EXCLUDED.trust_buy,
            trust_sell=EXCLUDED.trust_sell, trust_net=EXCLUDED.trust_net,
            dealer_buy=EXCLUDED.dealer_buy, dealer_sell=EXCLUDED.dealer_sell,
            dealer_net=EXCLUDED.dealer_net, total_net=EXCLUDED.total_net,
            source=EXCLUDED.source, retrieved_at=now()
    """
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            for record in records:
                record["source"] = "TWSE_T86" if record["market"] == "twse" else "TPEX_OPENAPI_tpex_3insti_daily_trading"
                cur.execute(sql, record)
    return len(records)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="交易日期 YYYY-MM-DD")
    args = parser.parse_args()
    parsed = date.fromisoformat(args.date)
    trade_date = parsed.isoformat()
    records = fetch_records(trade_date)
    count = save_records(records)
    print(f"成功寫入 {count} 筆三大法人資料，交易日 {trade_date}")
    for row in records:
        print(row["market"], row["stock_id"], "外資", row["foreign_net"], "投信", row["trust_net"], "自營商", row["dealer_net"], "合計", row["total_net"])


if __name__ == "__main__":
    main()
