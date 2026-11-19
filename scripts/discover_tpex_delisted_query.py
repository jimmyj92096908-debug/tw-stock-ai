#!/usr/bin/env python3
"""Read-only discovery of TPEx delisted-query page forms and linked frontend API hints."""
from __future__ import annotations
import argparse, json, re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

PAGE = "https://www.tpex.org.tw/zh-tw/mainboard/listed/delisted.html"
MAX_ASSETS = 20
MAX_BYTES = 1_000_000
TIMEOUT = (10, 25)

class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms, self.scripts, self.links = [], [], []
        self.current_form = None
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.current_form = {"action": attrs.get("action", ""), "method": attrs.get("method", "get"), "attrs": attrs}
            self.forms.append(self.current_form)
        elif tag == "input" and self.current_form is not None:
            self.current_form.setdefault("inputs", []).append({k: attrs.get(k) for k in ("name", "type", "value", "id")})
        elif tag == "select" and self.current_form is not None:
            self.current_form.setdefault("selects", []).append({k: attrs.get(k) for k in ("name", "id")})
        elif tag == "script" and attrs.get("src"):
            self.scripts.append(attrs["src"])
        elif tag == "link" and attrs.get("href") and "javascript" not in attrs.get("href", ""):
            self.links.append(attrs["href"])
    def handle_endtag(self, tag):
        if tag == "form":
            self.current_form = None

def bounded_get(session, url):
    r = session.get(url, timeout=TIMEOUT, headers={"User-Agent":"Mozilla/5.0 (compatible; market-data-audit/1.0)"})
    r.raise_for_status()
    data = r.content[:MAX_BYTES]
    return r, data

def inspect_asset(text, url):
    patterns = (r"(?:ajax|fetch|axios|\$\.(?:get|post)|\.(?:get|post))\s*\([^)]{0,500}", r"https?://[^\s\"'<>]+", r"/[^\s\"'<>]{1,200}(?:api|query|search|delist)[^\s\"'<>]*")
    hits = []
    for pattern in patterns:
        hits.extend(re.findall(pattern, text, flags=re.I))
    return list(dict.fromkeys(hits))[:100]

def run(output: Path):
    import requests
    output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    report = {"source_url": PAGE, "access_status": None, "page_title_hint": None, "forms": [], "script_assets": [], "endpoint_hints": [], "limitations": [], "automated_data_endpoint_confirmed": False}
    try:
        response, raw = bounded_get(session, PAGE)
        report["access_status"] = response.status_code
        (output / "delisted_page.html").write_bytes(raw)
        parser = PageParser()
        parser.feed(raw.decode(response.encoding or "utf-8", errors="replace"))
        report["forms"] = parser.forms
        report["script_assets"] = [urljoin(PAGE, src) for src in parser.scripts[:MAX_ASSETS]]
        for asset_index, asset in enumerate(report["script_assets"], start=1):
            try:
                _, js = bounded_get(session, asset)
                text = js.decode("utf-8", errors="replace")
                hints = inspect_asset(text, asset)
                if hints:
                    report["endpoint_hints"].append({"asset": asset, "hints": hints})
                (output / ("asset_" + str(asset_index) + ".js")).write_bytes(js)
            except Exception as e:
                report["limitations"].append(f"asset_fetch_failed: {asset}: {type(e).__name__}")
    except Exception as e:
        report["access_status"] = "error"
        report["limitations"].append(f"page_fetch_failed: {type(e).__name__}: {e}")
    report["limitations"].append("This diagnostic only discovers HTML form and frontend hints; hints are not proven APIs until request/response schema and coverage are validated.")
    report["automated_data_endpoint_confirmed"] = False
    (output / "diagnostic_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["access_status"], "form_count": len(report["forms"]), "script_count": len(report["script_assets"]), "hint_asset_count": len(report["endpoint_hints"]), "endpoint_confirmed": False}, ensure_ascii=False))
    return report

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default="audit-output/tpex-delisted-discovery")
    args = ap.parse_args()
    run(Path(args.output_dir))
