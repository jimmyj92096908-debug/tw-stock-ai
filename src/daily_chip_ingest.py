"""Daily official chip ingestion for the full TWSE/TPEx stock-master universe.

The TPEx institutional snapshot supplies the source trade date. Institutional
and margin feeds are independently validated before upsert. Missing margin
snapshots are reported as warnings and are never fabricated as zero.
"""
from __future__ import annotations

import os
import sys
from datetime import date

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

sys.path.insert(0, os.path.dirname(__file__))

from institutional_data import TPEX_URL as INSTITUTIONAL_TPEX_URL, ad_date
from institutional_flows import fetch_for_date, sync_rows
from margin_data import fetch_records as fetch_margin
from margin_data import load_stock_universe, save_records as save_margin

def retry_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=4, connect=4, read=4, backoff_factor=2,
                  status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=frozenset({"GET"}),
                  respect_retry_after_header=True)
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def latest_tpex_trade_date() -> date:
    response = retry_session().get(
        INSTITUTIONAL_TPEX_URL,
        headers={"User-Agent": "Mozilla/5.0 (compatible; TaiwanStockResearch/1.0)"},
        timeout=(15, 60),
    )
    response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("TPEx 最新法人快照為空，停止匯入")
    dates = {ad_date(row.get("Date")) for row in rows if isinstance(row, dict)}
    dates.discard(None)
    if len(dates) != 1:
        raise RuntimeError(f"TPEx 最新交易日不唯一或無法解析：{sorted(dates)}")
    return date.fromisoformat(next(iter(dates)))


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("缺少 DATABASE_URL")

    trade_date = latest_tpex_trade_date()
    print(f"官方 TPEx 最新交易日：{trade_date}")

    # Institutional importer parses full-market TWSE and TPEx data and
    # writes only symbols that exist in stock_master.
    institutional = fetch_for_date(trade_date)
    if not institutional:
        raise RuntimeError("上市／上櫃三大法人資料均為空，停止本次資料管線")
    written = sync_rows(institutional, database_url)
    print(f"三大法人資料：取得 {len(institutional)} 筆，Neon 寫入 {written} 筆")

    # Credit trading is a separate feed and can publish later than T86.
    # Keep the verified institutional data if credit data has not published yet.
    try:
        universe = load_stock_universe()
        margin = fetch_margin(trade_date.isoformat(), universe)
        if not margin:
            raise RuntimeError("融資融券資料為空")
        margin_written = save_margin(margin)
        by_market = {
            market: sum(row["market"] == market for row in margin)
            for market in ("twse", "tpex")
        }
        print(
            f"融資融券資料：取得 {len(margin)} 筆，寫入 {margin_written} 筆；"
            f"TWSE {by_market['twse']} 檔、TPEx {by_market['tpex']} 檔"
        )
    except Exception as exc:
        print(f"WARNING: 融資融券資料暫不可用，法人資料已保存；下次排程補抓。原因：{exc}")


if __name__ == "__main__":
    main()
