#!/usr/bin/env python3
"""Read-only diagnostic for the official TWSE historical holiday UI.

Fetches the public page and linked first-party JavaScript assets. It does not
submit forms, download calendar records, or modify project/database state.
"""
from __future__ import annotations

import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser

PAGES = [
    "https://www.twse.com.tw/zh/trading/holiday.html",
    "https://accessibility.twse.com.tw/zh/trading/holiday.html",
]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TWStockCalendarResearch/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/javascript,*/*",
}


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = []
        self.selects = []
        self.scripts = []
        self.links = []
        self._form = None
        self._select = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self._form = {"action": a.get("action", ""), "method": a.get("method", "get")}
            self.forms.append(self._form)
        elif tag == "select":
            self._select = {"name": a.get("name", ""), "id": a.get("id", ""), "options": []}
            self.selects.append(self._select)
        elif tag == "option" and self._select is not None:
            self._select["options"].append({"value": a.get("value", "")})
        elif tag == "script" and a.get("src"):
            self.scripts.append(a["src"])
        elif tag == "a" and any(k in (a.get("href", "").lower()) for k in ("csv", "download", "holiday")):
            self.links.append(a.get("href", ""))

    def handle_endtag(self, tag):
        if tag == "form":
            self._form = None
        elif tag == "select":
            self._select = None


def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as response:
        body = response.read(2_000_000)
        return response.geturl(), response.headers.get("Content-Type", ""), body


def main():
    summary = {"pages": [], "assets": [], "errors": []}
    seen_assets = set()
    for page in PAGES:
        try:
            final_url, content_type, body = fetch(page)
            html = body.decode("utf-8", errors="replace")
            parser = PageParser()
            parser.feed(html)
            item = {
                "requested_url": page,
                "final_url": final_url,
                "content_type": content_type,
                "html_bytes": len(body),
                "forms": parser.forms,
                "selects": parser.selects,
                "download_links": parser.links,
                "script_count": len(parser.scripts),
            }
            summary["pages"].append(item)
            for src in parser.scripts:
                asset_url = urllib.parse.urljoin(final_url, src)
                if asset_url in seen_assets or urllib.parse.urlparse(asset_url).netloc not in {
                    "www.twse.com.tw", "accessibility.twse.com.tw"
                }:
                    continue
                seen_assets.add(asset_url)
                try:
                    _, ctype, js = fetch(asset_url)
                    text = js.decode("utf-8", errors="replace")
                    hits = []
                    for match in re.finditer(r"(?i).{0,100}(?:holiday|csv|download|queryYear|year|開休市).{0,160}", text):
                        snippet = re.sub(r"\\s+", " ", match.group(0)).strip()
                        if snippet and snippet not in hits:
                            hits.append(snippet)
                        if len(hits) >= 12:
                            break
                    summary["assets"].append({
                        "url": asset_url, "content_type": ctype,
                        "bytes": len(js), "relevant_snippets": hits,
                    })
                except Exception as exc:
                    summary["errors"].append({"url": asset_url, "error": str(exc)[:240]})
        except Exception as exc:
            summary["errors"].append({"url": page, "error": str(exc)[:240]})

    import json
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["pages"]:
        raise SystemExit("No official TWSE page could be fetched")


if __name__ == "__main__":
    main()
