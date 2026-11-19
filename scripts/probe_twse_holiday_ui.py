#!/usr/bin/env python3
"""Read-only extraction of TWSE holiday report configuration and CSV request logic."""
from __future__ import annotations
import json, re, urllib.parse, urllib.request
from html.parser import HTMLParser

URL = "https://www.twse.com.tw/zh/trading/holiday.html"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TWStockCalendarResearch/1.0)",
           "Accept": "text/html,application/xhtml+xml,application/javascript,*/*"}

def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.geturl(), r.headers.get("Content-Type", ""), r.read(2_000_000)

def snippets(source, patterns, before=500, after=1200, limit=30):
    found = []
    for pattern in patterns:
        for m in re.finditer(pattern, source, re.I | re.S):
            value = re.sub(r"\s+", " ", source[max(0,m.start()-before):m.end()+after]).strip()
            if value not in found:
                found.append(value)
            if len(found) >= limit:
                return found
    return found

class Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts, self.forms, self.selects = [], [], []
        self.links, self.tags = [], []
        self.in_select = None
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and a.get("src"): self.scripts.append(a["src"])
        if tag == "form": self.forms.append({"action":a.get("action"),"method":a.get("method")})
        if tag == "select":
            self.in_select = {"name":a.get("name"),"id":a.get("id"),"options":[]}
            self.selects.append(self.in_select)
        if tag == "option" and self.in_select is not None:
            self.in_select["options"].append({"value":a.get("value"),"text":a.get("label")})
        if tag in ("div","table","button","a","input"):
            keep = {k:v for k,v in a.items() if k in ("id","class","name","data-api","data-argv","data-report","href","type","value")}
            if keep: self.tags.append({"tag":tag,**keep})
        if tag == "a" and a.get("href"): self.links.append(a["href"])
    def handle_endtag(self, tag):
        if tag == "select": self.in_select = None

def main():
    result = {"page":{}, "report_scripts":[], "errors":[]}
    final, ctype, body = fetch(URL)
    html = body.decode("utf-8","replace")
    p = Parser(); p.feed(html)
    result["page"] = {
        "url":final,"content_type":ctype,"bytes":len(body),
        "forms":p.forms,"selects":p.selects,"relevant_tags":p.tags,
        "holiday_html_snippets":snippets(html,[r"rwd-table",r"data-argv",r"data-api",r"web-report",r"開休市"],250,500,35)
    }
    for src in p.scripts:
        asset = urllib.parse.urljoin(final,src)
        if "web-report.js" not in asset: continue
        try:
            js_url, js_type, js_body = fetch(asset)
            js = js_body.decode("utf-8","replace")
            result["report_scripts"].append({
                "url":js_url,"content_type":js_type,"bytes":len(js_body),
                "query_logic":snippets(js,[r"Form API:",r"\$\.getJSON",r"data.{0,20}argv",r"\.csv",r"cfg\.rwd",r"r\.api"],700,1800,40)
            })
        except Exception as exc:
            result["errors"].append({"url":asset,"error":str(exc)[:300]})

    # Probe the exact form API using its actual "date" field, not queryYear.
    api = "https://www.twse.com.tw/holidaySchedule/holidaySchedule"
    result["api_probes"] = []
    for year in ("2021", "2022", "2023", "2024", "2025", "2026"):
        for response in ("json",):
            query = urllib.parse.urlencode({"response": response, "date": year})
            target = api + "?" + query
            try:
                final_url, content_type, payload = fetch(target)
                sample = payload[:1200].decode("utf-8-sig", "replace")
                item = {"year_value": year, "response": response, "url": final_url,
                        "content_type": content_type, "bytes": len(payload),
                        "sample": sample}
            except Exception as exc:
                item = {"year_value": year, "response": response, "url": target,
                        "error": str(exc)[:300]}
            result["api_probes"].append(item)

    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__ == "__main__":
    main()
