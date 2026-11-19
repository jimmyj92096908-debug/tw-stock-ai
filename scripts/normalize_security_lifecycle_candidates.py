#!/usr/bin/env python3
"""Normalize official listing/delisting CSV snapshots into review-only lifecycle events."""
from __future__ import annotations
import argparse, csv, json
from pathlib import Path
from typing import Any

ALIASES = {
    "code": ("公司代號", "上市編號", "上櫃編號", "證券代號", "股票代號"),
    "name": ("公司名稱", "公司簡稱", "證券名稱", "股票名稱"),
    "listing_date": ("上市日期", "股票上市買賣日期", "上櫃日期", "掛牌日期"),
    "delisting_date": ("終止上市日期", "下市日期", "終止上櫃日期", "終止櫃買日期"),
}
DATE_KEYS = ("listing_date", "delisting_date")

def first_value(row: dict[str, str], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = (row.get(key) or "").strip()
        if value:
            return value
    return ""

def normalize_date(value: str) -> str | None:
    value = value.strip().replace("/", "-")
    if not value:
        return None
    parts = value.split("-")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        y, m, d = map(int, parts)
        if y < 1911:
            y += 1911
        try:
            from datetime import date
            return date(y, m, d).isoformat()
        except ValueError:
            return None
    return None

def normalize_rows(rows: list[dict[str, str]], market: str, source: str) -> dict[str, Any]:
    events = []
    rejected = []
    for idx, row in enumerate(rows, start=2):
        code = first_value(row, ALIASES["code"])
        name = first_value(row, ALIASES["name"])
        listing_raw = first_value(row, ALIASES["listing_date"])
        delisting_raw = first_value(row, ALIASES["delisting_date"])
        listing = normalize_date(listing_raw)
        delisting = normalize_date(delisting_raw)
        if not code:
            rejected.append({"row_number": idx, "reason": "missing_security_code"})
            continue
        if listing_raw and not listing:
            rejected.append({"row_number": idx, "stock_id": code, "reason": "invalid_listing_date", "raw_date": listing_raw})
        if delisting_raw and not delisting:
            rejected.append({"row_number": idx, "stock_id": code, "reason": "invalid_delisting_date", "raw_date": delisting_raw})
        if listing:
            events.append({"stock_id": code, "name": name, "market": market, "event_type": "listing_start_candidate", "event_date": listing, "source": source, "source_row": idx, "validation_status": "candidate_not_accepted"})
        if delisting:
            events.append({"stock_id": code, "name": name, "market": market, "event_type": "delisting_end_candidate", "event_date": delisting, "source": source, "source_row": idx, "validation_status": "candidate_not_accepted"})
    # Candidate intervals are constructed only when both dates exist and chronology is valid.
    intervals = []
    by_code: dict[str, dict[str, Any]] = {}
    for event in events:
        record = by_code.setdefault(event["stock_id"], {"stock_id": event["stock_id"], "name": event["name"], "market": market, "listing_date": None, "delisting_date": None, "source": source})
        if event["event_type"] == "listing_start_candidate":
            record["listing_date"] = event["event_date"]
        elif event["event_type"] == "delisting_end_candidate":
            record["delisting_date"] = event["event_date"]
    for record in by_code.values():
        start, end = record["listing_date"], record["delisting_date"]
        if start and end and end < start:
            rejected.append({"stock_id": record["stock_id"], "reason": "delisting_before_listing", "listing_date": start, "delisting_date": end})
            continue
        record.update({"effective_from_candidate": start, "effective_to_candidate": end, "interval_status": "candidate_review_required", "historical_universe_accepted": False})
        intervals.append(record)
    return {"schema_version": 1, "market": market, "source": source, "input_rows": len(rows), "event_count": len(events), "candidate_interval_count": len(intervals), "events": events, "candidate_intervals": intervals, "rejected_rows": rejected, "historical_universe_accepted": False, "download_authorized": False, "notes": ["CSV snapshots may omit historical delisted instruments or effective-date revisions.", "Date intervals are review candidates, not proof of trading sessions or daily quote availability."]}

def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV header missing")
        return list(reader)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True)
    p.add_argument("--market", required=True, choices=("TWSE", "TPEX"))
    p.add_argument("--source", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    result = normalize_rows(read_csv(Path(a.input)), a.market, a.source)
    out = Path(a.output); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"rows": result["input_rows"], "events": result["event_count"], "intervals": result["candidate_interval_count"], "accepted": False}, ensure_ascii=False))
if __name__ == "__main__":
    main()
