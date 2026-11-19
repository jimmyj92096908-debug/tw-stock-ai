"""Preflight a five-year TWSE/TPEx bulk-history range without downloading prices.

Fetches official TWSE holiday calendars, builds expected trading sessions,
and audits an existing local manifest if present. It never connects to Neon,
downloads daily quote payloads, or fills missing OHLC.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import requests

CALENDAR_URL = "https://www.twse.com.tw/holidaySchedule/holidaySchedule"
CLOSED_WORDS = ("放假", "補假", "市場無交易", "休市")
MARKETS = ("twse", "tpex")


def closed_dates_from_payload(payload: dict[str, Any], year: int) -> set[date]:
    if payload.get("stat") != "ok":
        raise ValueError(f"TWSE calendar status is not ok for {year}")
    # queryYear may be ignored by the public endpoint. Validate the year
    # actually represented by the response, not the requested query parameter.
    actual_years: set[int] = set()
    title = str(payload.get("title", ""))
    title_match = re.search(r"(?<!\d)(\d{2,4})\s*年", title)
    if title_match:
        value = int(title_match.group(1))
        actual_years.add(value + 1911 if value < 1911 else value)
    response_date = str(payload.get("date", "")).strip()
    if re.fullmatch(r"\d{8}", response_date):
        actual_years.add(int(response_date[:4]))
    if actual_years != {year}:
        raise ValueError(
            f"TWSE returned calendar year(s) {sorted(actual_years)} "
            f"instead of requested {year}"
        )
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise ValueError(f"TWSE calendar data is missing for {year}")
    closed: set[date] = set()
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        day_text, name, description = row[0], str(row[1]), str(row[2])
        if any(word in name or word in description for word in CLOSED_WORDS):
            text = str(day_text).strip().replace("/", "-")
            parts = text.split("-")
            if len(parts) == 3 and len(parts[0]) <= 3:
                text = f"{int(parts[0]) + 1911:04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
            closed.add(date.fromisoformat(text))
    return closed


class _CalendarHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self.current_row: list[str] | None = None
        self.current_cell: list[str] | None = None
        self.page_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.current_row = []
        elif tag in {"td", "th"} and self.current_row is not None:
            self.current_cell = []
        elif tag == "br" and self.current_cell is not None:
            self.current_cell.append(" ")

    def handle_data(self, data: str) -> None:
        self.page_text.append(data)
        if self.current_cell is not None:
            self.current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self.current_cell is not None and self.current_row is not None:
            self.current_row.append(" ".join("".join(self.current_cell).split()))
            self.current_cell = None
        elif tag == "tr" and self.current_row is not None:
            if self.current_row:
                self.rows.append(self.current_row)
            self.current_row = None


def closed_dates_from_html(html: str, year: int) -> set[date]:
    parser = _CalendarHTMLParser()
    parser.feed(html)
    page_text = " ".join(parser.page_text)
    year_matches = re.findall(r"(?<!\d)(\d{2,4})\s*年", page_text)
    actual_years = {
        int(value) + 1911 if int(value) < 1911 else int(value)
        for value in year_matches
    }
    if actual_years != {year}:
        raise ValueError(
            f"TWSE HTML returned calendar year(s) {sorted(actual_years)} "
            f"instead of requested {year}"
        )

    closed: set[date] = set()
    date_patterns = (
        re.compile(
            r"(?:(?P<prefix_year>\d{2,4})\s*年)?\s*"
            r"(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*日"
            r"(?:\s*[（(]\s*(?P<suffix_year>\d{2,4})\s*年\s*[）)])?"
        ),
        re.compile(r"(?P<iso_year>\d{4})[-/](?P<iso_month>\d{1,2})[-/](?P<iso_day>\d{1,2})"),
    )
    for row in parser.rows:
        if len(row) < 2:
            continue
        date_cell = next((cell for cell in row[:2] if any(p.search(cell) for p in date_patterns)), "")
        if not date_cell:
            continue
        label_text = " ".join(cell for cell in row if cell != date_cell)
        if not any(word in label_text for word in CLOSED_WORDS):
            continue
        for pattern in date_patterns:
            for match in pattern.finditer(date_cell):
                values = match.groupdict()
                if values.get("iso_year"):
                    item_year = int(values["iso_year"])
                    month = int(values["iso_month"])
                    day = int(values["iso_day"])
                else:
                    raw_year = values.get("suffix_year") or values.get("prefix_year")
                    item_year = int(raw_year) if raw_year else year
                    if item_year < 1911:
                        item_year += 1911
                    month = int(values["month"])
                    day = int(values["day"])
                if item_year == year:
                    closed.add(date(item_year, month, day))
    if not parser.rows:
        raise ValueError(f"TWSE historical calendar HTML has no table rows for {year}")
    return closed


def fetch_closed_dates(year: int, session: requests.Session) -> set[date]:
    roc_year = year - 1911
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; tw-stock-ai-history-preflight/1.0)",
        "Referer": "https://www.twse.com.tw/zh/trading/holiday.html",
    }
    landing = session.get(
        "https://www.twse.com.tw/zh/trading/holiday.html",
        timeout=(8, 20),
        headers=headers,
    )
    landing.raise_for_status()
    response = session.get(
        CALENDAR_URL,
        params={"queryYear": str(roc_year), "response": "html", "_": str(time.time_ns())},
        timeout=(8, 20),
        headers=headers,
    )
    response.raise_for_status()
    return closed_dates_from_html(response.text, year)


def expected_sessions(start: date, end: date, closed_by_year: dict[int, set[date]]) -> list[date]:
    if start > end:
        raise ValueError("start date must be on or before end date")
    days: list[date] = []
    current = start
    while current <= end:
        if current.weekday() < 5 and current not in closed_by_year.get(current.year, set()):
            days.append(current)
        current += timedelta(days=1)
    return days


def read_latest_manifest(manifest: Path) -> dict[tuple[str, str], dict[str, Any]]:
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    if not manifest.exists():
        return latest
    for line_number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        try:
            item = json.loads(line)
            market, day, status = item["market"], item["trade_date"], item["status"]
            date.fromisoformat(day)
            if market not in MARKETS or status not in {"success", "failed", "no_data_unverified"}:
                continue
            latest[(market, day)] = item
        except (ValueError, KeyError, TypeError):
            raise ValueError(f"Invalid manifest record at line {line_number}")
    return latest


def _safe_existing_file(root: Path, relative: str) -> bool:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return False
    return candidate.is_file() and candidate.stat().st_size > 0


def build_preflight(
    start: date,
    end: date,
    closed_by_year: dict[int, set[date]],
    output_dir: Path,
) -> dict[str, Any]:
    calendar_years = set(range(start.year, end.year + 1))
    missing_calendar_years = sorted(calendar_years - set(closed_by_year))
    calendar_complete = not missing_calendar_years
    sessions = expected_sessions(start, end, closed_by_year) if calendar_complete else []
    manifest_path = output_dir / "manifest.jsonl"
    latest = read_latest_manifest(manifest_path)
    expected_keys = {
        (market, day.isoformat())
        for day in sessions
        for market in MARKETS
    }
    in_range_latest = {
        key: item for key, item in latest.items()
        if start.isoformat() <= key[1] <= end.isoformat()
    }
    successful: list[tuple[str, str]] = []
    failed: list[tuple[str, str]] = []
    no_data_unverified: list[tuple[str, str]] = []
    incomplete_files: list[dict[str, str]] = []
    unexpected: list[tuple[str, str]] = []

    for key, item in in_range_latest.items():
        if calendar_complete and key not in expected_keys:
            unexpected.append(key)
            continue
        if item["status"] == "failed":
            failed.append(key)
            continue
        if item["status"] == "no_data_unverified":
            no_data_unverified.append(key)
            continue
        raw_ok = _safe_existing_file(output_dir, str(item.get("raw_path", "")))
        rows_ok = _safe_existing_file(output_dir, str(item.get("rows_path", "")))
        if raw_ok and rows_ok:
            successful.append(key)
        else:
            incomplete_files.append({
                "market": key[0],
                "trade_date": key[1],
                "raw_file_present": str(raw_ok).lower(),
                "rows_file_present": str(rows_ok).lower(),
            })

    pending = sorted(expected_keys - set(successful) - set(failed) - set(no_data_unverified) - {
        (item["market"], item["trade_date"]) for item in incomplete_files
    }) if calendar_complete else []
    market_counts = {
        market: {
            "expected_sessions": len(sessions) if calendar_complete else None,
            "completed": sum(1 for m, _ in successful if m == market),
            "failed": sum(1 for m, _ in failed if m == market),
            "no_data_unverified": sum(1 for m, _ in no_data_unverified if m == market),
            "pending": sum(1 for m, _ in pending if m == market) if calendar_complete else None,
        }
        for market in MARKETS
    }
    return {
        "report_type": "five_year_history_preflight",
        "range": {"start_date": start.isoformat(), "end_date": end.isoformat()},
        "calendar_source": "TWSE official holidaySchedule endpoint",
        "calendar_years": sorted(closed_by_year),
        "weekday_count": sum(
            1 for n in range((end - start).days + 1)
            if (start + timedelta(days=n)).weekday() < 5
        ),
        "calendar_status": "complete" if calendar_complete else "incomplete",
        "calendar_unavailable_years": missing_calendar_years,
        "official_trading_session_count": len(sessions) if calendar_complete else None,
        "expected_market_date_tasks": len(expected_keys) if calendar_complete else None,
        "market_counts": market_counts,
        "failed_market_dates": [{"market": m, "trade_date": d} for m, d in sorted(failed)],
        "no_data_unverified_market_dates": [
            {"market": m, "trade_date": d} for m, d in sorted(no_data_unverified)
        ],
        "incomplete_manifest_files": incomplete_files,
        "manifest_entries_outside_requested_range": [
            {"market": m, "trade_date": d} for m, d in sorted(unexpected)
        ],
        "pending_market_dates": [{"market": m, "trade_date": d} for m, d in pending],
        "pending_count_is_authoritative": calendar_complete,
        "stock_universe_validation": {
            "status": "not_run",
            "reason": (
                "The current four-digit company stock list is not a complete instrument "
                "universe for all-market quotes (which may include ETFs, ETNs and other securities). "
                "A separately scoped official instrument master is required."
            ),
        },
        "read_only": True,
        "daily_quote_downloaded": False,
        "database_accessed": False,
        "database_modified": False,
        "price_imputation_performed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default="2021-11-19")
    parser.add_argument("--end-date", default="2026-11-19")
    parser.add_argument("--output-dir", default="artifacts/five-year-market-history")
    parser.add_argument("--report", default="audit-output/five-year-history-preflight.json")
    args = parser.parse_args()
    start, end = date.fromisoformat(args.start_date), date.fromisoformat(args.end_date)
    if start > end:
        parser.error("start date must be on or before end date")
    session = requests.Session()
    closed_by_year: dict[int, set[date]] = {}
    calendar_errors: dict[str, str] = {}
    for year in range(start.year, end.year + 1):
        try:
            closed_by_year[year] = fetch_closed_dates(year, session)
        except Exception as exc:
            calendar_errors[str(year)] = f"{type(exc).__name__}: {str(exc)[:300]}"
    report = build_preflight(start, end, closed_by_year, Path(args.output_dir))
    report["calendar_errors"] = calendar_errors
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")
    print(json.dumps({
        "report": str(report_path),
        "range": report["range"],
        "calendar_status": report["calendar_status"],
        "calendar_unavailable_years": report["calendar_unavailable_years"],
        "calendar_errors": calendar_errors,
        "official_trading_session_count": report["official_trading_session_count"],
        "expected_market_date_tasks": report["expected_market_date_tasks"],
        "market_counts": report["market_counts"],
        "stock_universe_validation": report["stock_universe_validation"]["status"],
        "daily_quote_downloaded": False,
        "database_modified": False,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
