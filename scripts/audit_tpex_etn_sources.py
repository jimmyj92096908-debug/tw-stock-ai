#!/usr/bin/env python3
"""Audit the official TPEx ESG ETN showcase page.

This is a partial current-product source only, not a complete current or
historical ETN master. It does not independently authorize exclusions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

URL = "https://www.tpex.org.tw/zh-tw/indices/stock-index/serial_etf_etn.html"


class EtnSectionParser(HTMLParser):
    """Extract codes from product-code nodes inside div.product.etn."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[tuple[str, bool, bool]] = []
        self.etn_depth = 0
        self.code_depth = 0
        self.code_parts: list[str] = []
        self.heading = ""
        self.in_heading = False
        self.heading_parts: list[str] = []
        self.section_etn = False
        self.section_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        classes = set(dict(attrs).get("class", "").split())
        is_etn = tag == "div" and {"product", "etn"}.issubset(classes)
        is_code = tag == "div" and "product-code" in classes
        self.stack.append((tag, is_etn, is_code))
        if is_etn:
            self.etn_depth += 1
        if is_code and self.etn_depth:
            self.code_depth += 1
        if tag in {"h1", "h2", "h3", "h4"}:
            self.in_heading = True
            self.heading_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"h1", "h2", "h3", "h4"} and self.in_heading:
            heading = " ".join("".join(self.heading_parts).split()).upper()
            self.section_etn = heading == "ETN"
            self.in_heading = False
        for index in range(len(self.stack) - 1, -1, -1):
            item = self.stack.pop()
            if item[0] == tag:
                _, was_etn, was_code = item
                if was_code and self.code_depth:
                    self.code_depth -= 1
                if was_etn and self.etn_depth:
                    self.etn_depth -= 1
                break

    def handle_data(self, data: str) -> None:
        if self.in_heading:
            self.heading_parts.append(data)
        if self.etn_depth and self.code_depth:
            self.code_parts.append(data)
        if self.section_etn:
            self.section_parts.append(data)


def extract_etn_codes(html: str) -> list[str]:
    parser = EtnSectionParser()
    parser.feed(html)
    # The current TPEx page uses div.product.etn > div.product-code.
    text = " ".join(parser.code_parts)
    codes = re.findall(r"(?:代號|證券代號)\s*[:：]\s*[“\"']?([0-9A-Z]{6})", text, flags=re.I)
    if not codes:
        # Keep support for simpler official page variants, but only in ETN section.
        section = " ".join(parser.section_parts)
        codes = re.findall(r"(?:代號|證券代號)\s*[:：]\s*[“\"']?([0-9A-Z]{6})", section, flags=re.I)
    return sorted(set(code.upper() for code in codes))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="audit-output/market-scope/tpex-etn")
    args = parser.parse_args()
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    import requests

    response = requests.get(URL, timeout=(10, 60), headers={
        "User-Agent": "tw-stock-ai-tpex-etn-audit/1.0",
        "Accept": "text/html,application/xhtml+xml",
    })
    response.raise_for_status()
    raw = response.content
    (out / "tpex-esg-etn-page-raw.html").write_bytes(raw)
    html = raw.decode(response.encoding or "utf-8", errors="replace")
    codes = extract_etn_codes(html)
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_url": URL,
        "http_status": response.status_code,
        "content_type": response.headers.get("Content-Type", ""),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "security_code_field": "代號",
        "security_code_count": len(codes),
        "security_codes": codes,
        "source_coverage": "partial_current_esg_etn_showcase_only",
        "historical_coverage_confirmed": False,
        "complete_current_etn_master_confirmed": False,
        "classification_confirmed": bool(codes),
        "automatic_exclusion_performed": False,
        "database_accessed": False,
        "database_modified": False,
        "five_year_quotes_downloaded": False,
        "quote_download_authorized": False,
    }
    (out / "tpex-etn-source-audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / "tpex-etn-codes-raw.json").write_text(
        json.dumps([{"security_code": code} for code in codes], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "http_status": response.status_code,
        "security_code_count": len(codes),
        "source_coverage": report["source_coverage"],
        "complete_current_etn_master_confirmed": False,
        "database_modified": False,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
