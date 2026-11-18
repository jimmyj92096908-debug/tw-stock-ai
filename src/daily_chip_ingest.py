"""Daily idempotent ingestion of latest official institutional and margin snapshots."""
from __future__ import annotations

import os
import sys
from datetime import date

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

sys.path.insert(0, os.path.dirname(__file__))
from institutional_data import TPEX_URL as INSTITUTIONAL_TPEX_URL, ad_date as institutional_date
from institutional_data import fetch_records as fetch_institutional, save_records as save_institutional
from margin_data import fetch_records as fetch_margin, save_records as save_margin


def retry_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=4, connect=4, read=4, backoff_factor=2,
                  status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=frozenset({"GET"}),
                  respect_retry_after_header=True)
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def latest_tpex_trade_date() -> str:
    response = retry_session().get(
        INSTITUTIONAL_TPEX_URL,
        headers={"User-Agent": "Mozilla/5.0 (compatible; TaiwanStockResearch/1.0)"},
        timeout=(15, 60),
    )
    response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("TPEx 最新法人快照為空，停止匯入")
    dates = {institutional_date(row.get("Date")) for row in rows if isinstance(row, dict)}
    dates.discard(None)
    if len(dates) != 1:
        raise RuntimeError(f"TPEx 最新交易日不唯一或無法解析：{sorted(dates)}")
    return next(iter(dates))


def main() -> None:
    if not os.environ.get("DATABASE_URL"):
        raise RuntimeError("缺少 DATABASE_URL")
    trade_date = latest_tpex_trade_date()
    date.fromisoformat(trade_date)
    print(f"以 TPEx 官方最新快照日期 {trade_date} 作為本次交易日")
    institutional = fetch_institutional(trade_date)
    if len(institutional) != 4:
        raise RuntimeError(f"法人資料應為四檔，實際 {len(institutional)} 筆")
    print(f"法人資料寫入 {save_institutional(institutional)} 筆")

    # Exchange credit data can be published later than institutional flows.
    # Keep the successful institutional snapshot even if margin data is not ready.
    try:
        margin = fetch_margin(trade_date)
        if len(margin) < 3:
            raise RuntimeError(f"融資融券資料筆數異常：{len(margin)}")
        print(f"融資融券資料寫入 {save_margin(margin)} 筆（不適用股票不補零）")
    except Exception as exc:
        print(f"警告：融資融券資料暫不可用，法人資料已保存；下次排程再補抓。原因：{exc}")


if __name__ == "__main__":
    main()
