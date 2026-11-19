#!/usr/bin/env python3
"""Read-only audit of official TPEx calendar sources and TDCC securities master.

This archives evidence and produces review candidates. It deliberately does not
assert a market calendar or a complete historical instrument universe merely
because a source file is reachable.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

TDCC_MASTER_URL = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-1"
TIMEOUT = (8, 30)
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; tw-stock-ai-scope-audit/1.0)"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_csv(raw: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "big5", "cp950"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("TDCC CSV encoding is not UTF-8/Big5/CP950")


def inspect_tdcc_csv(raw: bytes) -> dict[str, Any]:
    text, encoding = decode_csv(raw)
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    if not rows:
        raise ValueError("TDCC securities master CSV is empty")
    header_index = next(
        (i for i, row in enumerate(rows[:10]) if any("證券代號" in cell for cell in row)),
        None,
    )
    if header_index is None:
        return {
            "encoding": encoding,
            "row_count_including_headers": len(rows),
            "header_detected": False,
            "sample_rows": rows[:5],
            "status": "manual_schema_review_required",
        }
    header = [cell.strip() for cell in rows[header_index]]
    body = [row for row in rows[header_index + 1:] if any(cell.strip() for cell in row)]
    width = len(header)
    normalized = [row[:width] + [""] * max(0, width - len(row)) for row in body]
    market_columns = [i for i, name in enumerate(header) if "市場別" in name or "市場" == name]
    type_columns = [i for i, name in enumerate(header) if any(k in name for k in ("證券類別", "商品類別", "證券種類", "證券型態"))]
    code_columns = [i for i, name in enumerate(header) if "證券代號" in name or "代號" == name]
    name_columns = [i for i, name in enumerate(header) if "證券名稱" in name or "名稱" == name]
    counts = {}
    for label, indexes in (("market", market_columns), ("instrument_type", type_columns)):
        counts[label] = {
            header[i]: dict(Counter(row[i].strip() for row in normalized if row[i].strip()))
            for i in indexes
        }
    return {
        "encoding": encoding,
        "header_detected": True,
        "headers": header,
        "row_count": len(normalized),
        "market_or_type_value_counts": counts,
        "code_columns": [header[i] for i in code_columns],
        "name_columns": [header[i] for i in name_columns],
        "sample_rows": [dict(zip(header, row)) for row in normalized[:8]],
        "status": "source_parsed_schema_review_required",
        "scope_limitations": [
            "TDCC securities master is a current depository reference, not by itself a five-year historical trading universe.",
            "Market/type field meanings and inclusion of all daily-quote instrument classes require validation.",
            "Historical delisted, expired, suspended and newly listed instruments require date-effective source coverage.",
        ],
    }


def archive_tpex_calendars(registry_path: Path, output: Path, session: requests.Session) -> dict[str, Any]:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    results = []
    for roc_year, item in sorted(registry["markets"]["tpex"].items()):
        url = item["url"]
        record: dict[str, Any] = {
            "roc_year": int(roc_year),
            "gregorian_year": int(roc_year) + 1911,
            "url": url,
            "registry_status": item["status"],
            "registry_description": item["description"],
            "status": "pending",
        }
        try:
            response = session.get(url, timeout=TIMEOUT, headers=HEADERS)
            response.raise_for_status()
            raw = response.content
            suffix = ".pdf" if ("pdf" in response.headers.get("Content-Type", "").lower() or url.lower().endswith(".pdf")) else ".html"
            path = output / "tpex-calendar" / f"{roc_year}{suffix}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            record.update({
                "status": "archived_pending_calendar_validation",
                "http_status": response.status_code,
                "final_url": response.url,
                "content_type": response.headers.get("Content-Type", ""),
                "bytes": len(raw),
                "sha256": sha256(raw),
                "raw_path": str(path),
            })
            if suffix == ".html":
                from html.parser import HTMLParser
                class Text(HTMLParser):
                    def __init__(self):
                        super().__init__()
                        self.parts = []
                    def handle_data(self, data):
                        if data.strip():
                            self.parts.append(" ".join(data.split()))
                parser = Text()
                parser.feed(raw.decode("utf-8", "replace"))
                extracted = "\\n".join(parser.parts)
                text_path = path.with_suffix(".txt")
                text_path.write_text(extracted + "\\n", encoding="utf-8")
                record["text_path"] = str(text_path)
                record["text_preview"] = extracted[:1200]
            else:
                try:
                    from pypdf import PdfReader
                    reader = PdfReader(io.BytesIO(raw))
                    extracted = "\\n".join(page.extract_text() or "" for page in reader.pages)
                    text_path = path.with_suffix(".txt")
                    text_path.write_text(extracted + "\\n", encoding="utf-8")
                    record["pdf_pages"] = len(reader.pages)
                    record["text_path"] = str(text_path)
                    record["text_preview"] = extracted[:1600]
                    record["status"] = "archived_text_extracted_pending_structured_calendar_validation"
                except Exception as exc:
                    record["text_extraction_error"] = f"{type(exc).__name__}: {str(exc)[:250]}"
                    record["status"] = "archived_text_extraction_failed_manual_review_required"
        except Exception as exc:
            record["status"] = "source_fetch_failed"
            record["error"] = f"{type(exc).__name__}: {str(exc)[:400]}"
        results.append(record)
    return {
        "source": "TPEx official annual market calendar URLs from checked-in source registry",
        "years": results,
        "calendar_days_accepted": False,
        "reason": "Source archival and text extraction do not independently establish a parsed trading-session calendar; market-specific table rows require validation.",
    }


def audit_tdcc(output: Path, session: requests.Session) -> dict[str, Any]:
    response = session.get(TDCC_MASTER_URL, timeout=TIMEOUT, headers=HEADERS)
    response.raise_for_status()
    raw = response.content
    path = output / "tdcc-securities-master.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    inspected = inspect_tdcc_csv(raw)
    inspected.update({
        "source": "TDCC official open data securities master",
        "url": response.url,
        "http_status": response.status_code,
        "content_type": response.headers.get("Content-Type", ""),
        "bytes": len(raw),
        "sha256": sha256(raw),
        "raw_path": str(path),
    })
    return inspected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", default="data/calendars/source_registry.json")
    parser.add_argument("--output-dir", default="audit-output/market-scope")
    parser.add_argument("--report", default="audit-output/market-scope/market-scope-audit.json")
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    tpex = archive_tpex_calendars(Path(args.registry), output, session)
    tdcc = audit_tdcc(output, session)
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "database_accessed": False,
        "database_modified": False,
        "five_year_quotes_downloaded": False,
        "tpex_calendar_audit": tpex,
        "tdcc_instrument_master_audit": tdcc,
        "overall_status": "evidence_archived_review_required",
    }
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
    print(json.dumps({
        "report": str(path),
        "tpex_calendar_years": len(tpex["years"]),
        "tpex_calendar_archived": sum(1 for x in tpex["years"] if x["status"] != "source_fetch_failed"),
        "tdcc_master_rows": tdcc.get("row_count"),
        "tdcc_schema_status": tdcc["status"],
        "overall_status": report["overall_status"],
        "database_modified": False,
        "five_year_quotes_downloaded": False,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
