"""下載 TWSE 上市與 TPEx 上櫃公司基本資料，建立初步股票清單。

資料來源：
- TWSE OpenAPI：上市公司基本資料
- TPEx OpenAPI：上櫃股票基本資料

注意：這是第一版股票池。後續仍需依交易所證券分類資料，
進一步核對普通股、特別股、TDR 與其他商品的納入規則。
"""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Any

import requests

TWSE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "stock_list.csv"
TIMEOUT_SECONDS = 30

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def fetch_json(url: str) -> list[dict[str, Any]]:
    """從官方 OpenAPI 取得 JSON 清單。"""
    response = requests.get(
        url,
        headers={"User-Agent": "tw-stock-ai/0.1"},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()

    if not isinstance(payload, list):
        raise ValueError(f"預期 API 回傳 JSON 陣列，實際為：{type(payload).__name__}")

    return [row for row in payload if isinstance(row, dict)]


def first_value(row: dict[str, Any], candidates: tuple[str, ...]) -> str:
    """依候選欄位名稱取得第一個非空值。"""
    for key in candidates:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def normalize_rows(
    rows: list[dict[str, Any]],
    market: str,
) -> list[dict[str, str]]:
    """統一上市與上櫃資料欄位，僅保留四位數代碼。"""
    normalized: list[dict[str, str]] = []

    for row in rows:
        code = first_value(row, ("公司代號", "證券代號", "股票代號", "代號", "SecuritiesCompanyCode"))
        # TPEx 上櫃基本資料使用英文欄名，TWSE 則使用中文欄名。
        name = first_value(
            row,
            ("公司簡稱", "證券名稱", "股票名稱", "名稱", "CompanyAbbreviation",
             "公司名稱", "CompanyName"),
        )
        industry = first_value(row, ("產業別", "產業類別", "SecuritiesIndustryCode"))

        # 公司基本資料中的股票代碼通常為四位數；先排除非此格式項目。
        if not re.fullmatch(r"\d{4}", code):
            continue
        if not name:
            continue

        normalized.append(
            {
                "stock_id": code,
                "stock_name": name,
                "market": market,
                "industry": industry,
            }
        )

    return normalized


def build_stock_list() -> list[dict[str, str]]:
    """下載並合併上市、上櫃資料，依股票代碼去重。"""
    logger.info("下載 TWSE 上市公司基本資料")
    listed = normalize_rows(fetch_json(TWSE_URL), "上市")

    logger.info("下載 TPEx 上櫃公司基本資料")
    otc = normalize_rows(fetch_json(TPEX_URL), "上櫃")

    merged: dict[str, dict[str, str]] = {}
    for item in listed + otc:
        merged[(item["market"], item["stock_id"])] = item

    result = sorted(merged.values(), key=lambda item: item["stock_id"])
    if not result:
        raise RuntimeError("合併後股票清單為空，請檢查官方 API 欄位或連線狀態。")

    return result


def save_stock_list(rows: list[dict[str, str]]) -> None:
    """將股票清單存成 UTF-8 CSV。"""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["stock_id", "stock_name", "market", "industry"]
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    logger.info("已儲存 %s 筆資料至 %s", len(rows), OUTPUT_PATH)


def main() -> None:
    rows = build_stock_list()
    save_stock_list(rows)
    logger.info("股票清單建立完成：共 %s 檔", len(rows))


if __name__ == "__main__":
    main()
