"""Fail-closed trading-day gate using the official TWSE holiday schedule."""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

CALENDAR_URL = "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule"
CLOSED_WORDS = ("放假", "補假", "市場無交易", "休市")


def closed_dates_from_payload(payload: dict) -> set[date]:
    if payload.get("stat") != "ok":
        raise ValueError("TWSE calendar status is not ok")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise ValueError("TWSE calendar data is missing")
    closed: set[date] = set()
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        day_text, name, description = row[0], str(row[1]), str(row[2])
        if any(word in name or word in description for word in CLOSED_WORDS):
            closed.add(date.fromisoformat(day_text))
    return closed


def fetch_closed_dates(year: int, get=requests.get) -> set[date]:
    response = get(
        CALENDAR_URL,
        params={"queryYear": str(year), "response": "json"},
        timeout=20,
        headers={"User-Agent": "tw-stock-ai/1.0"},
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("queryYear") not in (None, year):
        raise ValueError("TWSE returned a different calendar year")
    return closed_dates_from_payload(payload)


def is_trading_day(day: date, closed_dates: set[date]) -> bool:
    return day.weekday() < 5 and day not in closed_dates


def main() -> int:
    today = date.today() if os.getenv("CALENDAR_DATE") else date.today()
    if os.getenv("CALENDAR_DATE"):
        today = date.fromisoformat(os.environ["CALENDAR_DATE"])
    else:
        from datetime import datetime
        today = datetime.now(ZoneInfo("Asia/Taipei")).date()

    output_path = os.getenv("GITHUB_OUTPUT")
    try:
        closed = fetch_closed_dates(today.year)
        should_run = is_trading_day(today, closed)
        reason = "trading_day" if should_run else "market_closed"
        print(f"TWSE 官方行事曆：{today.isoformat()} -> {reason}")
        source = "twse_official"
    except Exception as exc:
        # Do not send a scheduled report when the official calendar cannot be verified.
        should_run, reason, source = False, "calendar_unavailable", "unavailable"
        print(f"::warning::無法確認 TWSE 官方交易日曆，為避免假日誤推播而略過：{type(exc).__name__}")

    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as handle:
            handle.write(f"should_run={'true' if should_run else 'false'}\n")
            handle.write(f"reason={reason}\n")
            handle.write(f"calendar_source={source}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
