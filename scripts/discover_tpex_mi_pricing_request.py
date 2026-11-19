"""Read-only discovery of the public TPEx daily close quotes page request."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests

PAGE = "https://www.tpex.org.tw/zh-tw/mainboard/trading/info/mi-pricing.html"


def main() -> None:
    out = Path("artifacts/tpex-mi-pricing-discovery")
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    result = {"read_only": True, "database_accessed": False, "database_modified": False, "page": PAGE}
    response = session.get(PAGE, timeout=45)
    result.update({"http_status": response.status_code, "final_url": response.url, "content_type": response.headers.get("Content-Type"), "html_bytes": len(response.content)})
    response.raise_for_status()
    html = response.text
    (out / "page.html").write_text(html, encoding="utf-8")
    script_urls = list(dict.fromkeys(urljoin(response.url, x) for x in re.findall(r'<script[^>]+src=["\']([^"\']+)', html, flags=re.I)))
    result["script_count"] = len(script_urls)
    findings = []
    for index, url in enumerate(script_urls):
        try:
            js_response = session.get(url, timeout=30)
            js_response.raise_for_status()
            js = js_response.text
            if any(term in js.lower() for term in ("mi-pricing", "aftertrading", "tradingstock")):
                path = out / f"script-{index}.js"
                path.write_text(js, encoding="utf-8")
                terms = []
                for term in ("mi-pricing", "afterTrading", "tradingStock"):
                    for match in list(re.finditer(re.escape(term), js, flags=re.I))[:8]:
                        terms.append(js[max(0, match.start()-350):min(len(js), match.end()+550)])
                findings.append({"url": url, "http_status": js_response.status_code, "saved_as": path.name, "matches": terms[:20]})
        except requests.RequestException as exc:
            findings.append({"url": url, "error": str(exc)})
    result["script_findings"] = findings
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
