"""Read-only canary for dated TPEx whole-market daily quotes.

No DATABASE_URL, no SQL, and no writing. This probe is intentionally NOT
connected to production ingest until the endpoint's date / volume semantics
are compared with known official records. At most 2 dated GETs per run.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import requests

ENDPOINT = "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc"
MIN_STOCKS = 500
MAX_DAYS = 2
REQUIRED_FIELDS = (
    "代號", "收盤", "開盤", "最高", "最低", "成交股數", "成交金額(元)", "成交筆數"
)


def clean_field(value: str) -> str:
    """Field labels may contain HTML and whitespace."""
    return re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", str(value))).strip()


def decimal_value(value):
    raw = str(value).strip().replace(",", "")
    if raw in ("", "-", "--", "—", "X", "None"):
        return None
    try:
        result = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("Invalid numeric official field") from exc
    if not result.is_finite():
        raise ValueError("Non-finite official field")
    return result


def parse_day(payload: dict, requested: date) -> dict:
    """Parse names, not positions; reject incomplete or anomalous snapshots."""
    if not isinstance(payload, dict) or payload.get("stat", "").lower() != "ok":
        raise ValueError("No valid TPEx session status")
    tables = payload.get("tables")
    if not isinstance(tables, list) or not tables:
        raise ValueError("Missing TPEx data tables")
    selected = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        fields = [clean_field(x) for x in table.get("fields", [])]
        if not all(name in fields for name in REQUIRED_FIELDS):
            continue
        if len(fields) != len(set(fields)):
            raise ValueError("Duplicate official field labels")
        rows = table.get("data")
        if not isinstance(rows, list):
            raise ValueError("Malformed TPEx session rows")
        idx = {field: fields.index(field) for field in REQUIRED_FIELDS}
        seen = set()
        for row in rows:
            if not isinstance(row, list) or len(row) != len(fields):
                raise ValueError("Unexpected TPEx row width")
            stock_id = str(row[idx["代號"]]).strip()
            if not re.fullmatch(r"\d{4}", stock_id):
                continue
            if stock_id in seen:
                raise ValueError("Duplicate four-digit stock code in session")
            seen.add(stock_id)
            try:
                values = {key: decimal_value(row[index]) for key, index in idx.items()
                          if key != "代號"}
            except ValueError:
                raise ValueError("Invalid numeric value in official stock row")
            lo, hi, close, op = (values[k] for k in ("最低", "最高", "收盤", "開盤"))
            if close is None or close <= 0:
                continue
            if lo is None or hi is None or op is None:
                continue
            if not (Decimal("0") < lo <= op <= hi and lo <= close <= hi):
                raise ValueError("Invalid official OHLC bounds")
            if any(values[k] is None or values[k] < 0
                   for k in ("成交股數", "成交金額(元)", "成交筆數")):
                raise ValueError("Invalid official trading totals")
            if values["成交股數"] != values["成交股數"].to_integral_value():
                raise ValueError("Non-integral official share count")
            selected.append((stock_id, close, int(values["成交股數"])))
        break
    if len(selected) < MIN_STOCKS:
        raise ValueError("Too few valid four-digit securities")
    # This official page is requested by date and may lack per-row dates.
    # It is therefore deliberately NEVER an approved source for INSERT until
    # an independent date-anchored sample proves it returns the requested date.
    return {
        "requested_date": requested.isoformat(),
        "valid_four_digit_codes": len(selected),
        "close_checksum": str(sum(v for _, v, _ in selected)),
        "total_round_lot_shares": sum(v for _, _, v in selected),
        "samples": {code: str(close) for code, close, _ in selected
                    if code in ("3105", "6488", "8069")},
        "date_independently_verified": False,
        "write_approved": False,
    }


def probe(days: list[date], session=None) -> list[dict]:
    if not 1 <= len(days) <= MAX_DAYS or len(set(days)) != len(days):
        raise ValueError("Canary requires one or two distinct dates")
    if any(day >= date.today() or day.weekday() >= 5 for day in days):
        raise ValueError("Only historical weekdays are allowed")
    http = session or requests
    results = []
    for day in days:
        response = http.get(
            ENDPOINT,
            params={"date": day.strftime("%Y/%m/%d"), "type": "EW",
                    "response": "json"},
            headers={"Accept": "application/json",
                     "User-Agent": "Mozilla/5.0 (compatible; tw-stock-ai/1.0)"},
            timeout=30,
        )
        response.raise_for_status()
        results.append(parse_day(response.json(), day))
    if len(results) == 2 and results[0]["close_checksum"] == results[1]["close_checksum"]:
        raise ValueError("Date-separated quotes have an identical price checksum")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only TPEx dated bulk canary")
    parser.add_argument("--date", action="append", required=True,
                        help="YYYY-MM-DD; one or two historical weekdays")
    args = parser.parse_args()
    days = [date.fromisoformat(raw) for raw in args.date]
    print(json.dumps({"mode": "read-only", "results": probe(days)},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
