#!/usr/bin/env python3
"""Read-only discovery of official TPEx ETN listing and lifecycle page query hints."""
from __future__ import annotations

import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

PAGES = {
    "current_listing": "https://www.tpex.org.tw/zh-tw/product/etn/product/list.html",
    "maturity_termination": "https://www.tpex.org.tw/zh-tw/product/etn/product/delisted.html",
}
MAX_ASSETS = 20
MAX_BYTES = 1_000_000
TIMEOUT = (10, 25)


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = []
        self.scripts = []
        self.inline_scripts = []
        self.current_form = None
        self.in_script = False
        self.script_parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.current_form = {
                "action": attrs.get("action", ""),
                "method": attrs.get("method", "get").lower(),
                "attrs": {k: v for k, v in attrs.items() if k in {"id", "name", "class"}},
                "inputs": [],
                "selects": [],
            }
            self.forms.append(self.current_form)
        elif tag == "input" and self.current_form is not None:
            self.current_form["inputs"].append(
                {k: attrs.get(k) for k in ("name", "type", "value", "id")}
            )
        elif tag == "select" and self.current_form is not None:
            self.current_form["selects"].append(
                {k: attrs.get(k) for k in ("name", "id")}
            )
        elif tag == "script":
            self.in_script = True
            self.script_parts = []
            if attrs.get("src"):
                self.scripts.append(attrs["src"])

    def handle_data(self, data):
        if self.in_script:
            self.script_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.in_script:
            inline = "".join(self.script_parts).strip()
            if inline:
                self.inline_scripts.append(inline)
            self.in_script = False
            self.script_parts = []
        elif tag == "form":
            self.current_form = None


def inspect_asset(text):
    patterns = (
        r"(?:ajax|fetch|axios|\$\.(?:get|post)|\.get|\.post)\s*\([^)]{0,700}",
        r"""(?:action|url|endpoint|api)\s*[:=]\s*["']([^"']{1,300})""",
        r"""/[^"'\s<>]{1,240}(?:api|query|search|list|delist)[^"'\s<>]*""",
        r"tables\.init\s*\([^)]{0,700}",
    )
    hits = []
    for pattern in patterns:
        hits.extend(re.findall(pattern, text, flags=re.I))
    return list(dict.fromkeys(str(hit) for hit in hits))[:100]


def run(output: Path):
    import requests

    output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    report = {
        "sources": {},
        "automated_data_endpoint_confirmed": False,
        "exact_security_code_field_confirmed": False,
        "request_schema_confirmed": False,
        "response_schema_confirmed": False,
        "limitations": [
            "Discovery performs bounded HTTP GET requests only; it never submits search forms or calls candidate data endpoints.",
            "Frontend strings are hints only. Endpoint and schema require a separately observed successful request/response.",
        ],
    }
    for source_id, page_url in PAGES.items():
        item = {
            "source_url": page_url,
            "access_status": None,
            "forms": [],
            "script_assets": [],
            "inline_script_hints": [],
            "asset_hints": [],
            "limitations": [],
        }
        report["sources"][source_id] = item
        try:
            response = session.get(
                page_url,
                timeout=TIMEOUT,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; tw-stock-ai-readonly-audit/1.0)",
                    "Accept": "text/html,application/xhtml+xml",
                },
            )
            response.raise_for_status()
            raw = response.content[:MAX_BYTES]
            (output / f"{source_id}.html").write_bytes(raw)
            parser = PageParser()
            parser.feed(raw.decode(response.encoding or "utf-8", errors="replace"))
            item["access_status"] = response.status_code
            item["forms"] = parser.forms
            item["script_assets"] = [
                urljoin(page_url, src) for src in parser.scripts[:MAX_ASSETS]
            ]
            for index, inline in enumerate(parser.inline_scripts, start=1):
                hints = inspect_asset(inline)
                if hints:
                    item["inline_script_hints"].append(
                        {"inline_script_index": index, "hints": hints}
                    )
            for index, asset_url in enumerate(item["script_assets"], start=1):
                try:
                    asset_response = session.get(
                        asset_url,
                        timeout=TIMEOUT,
                        headers={"User-Agent": "Mozilla/5.0 (compatible; tw-stock-ai-readonly-audit/1.0)"},
                    )
                    asset_response.raise_for_status()
                    asset_raw = asset_response.content[:MAX_BYTES]
                    (output / f"{source_id}_asset_{index}.js").write_bytes(asset_raw)
                    hints = inspect_asset(asset_raw.decode("utf-8", errors="replace"))
                    if hints:
                        item["asset_hints"].append({"asset_url": asset_url, "hints": hints})
                except Exception as exc:
                    item["limitations"].append(
                        f"asset_fetch_failed:{type(exc).__name__}"
                    )
        except Exception as exc:
            item["access_status"] = "error"
            item["limitations"].append(
                f"page_fetch_failed:{type(exc).__name__}:{str(exc)[:300]}"
            )
    (output / "diagnostic_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        key: {
            "access_status": value["access_status"],
            "form_count": len(value["forms"]),
            "script_count": len(value["script_assets"]),
            "inline_hint_count": len(value["inline_script_hints"]),
            "asset_hint_count": len(value["asset_hints"]),
        }
        for key, value in report["sources"].items()
    }, ensure_ascii=False, sort_keys=True))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="audit-output/market-scope/tpex-etn-query-discovery")
    args = parser.parse_args()
    run(Path(args.output_dir))
