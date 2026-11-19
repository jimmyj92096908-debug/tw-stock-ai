#!/usr/bin/env python3
"""Archive TPEx OpenAPI catalog and identify documented ETN/bond listing routes.

Discovery only: no inferred code lists, database access, or quote downloads.
"""
from __future__ import annotations
import argparse, hashlib, json, time
from datetime import datetime, timezone
from pathlib import Path

URL = "https://www.tpex.org.tw/openapi/swagger.json"

def inspect_catalog(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("paths"), dict):
        raise ValueError("OpenAPI catalog has no paths object")
    hits = []
    for path, methods in payload["paths"].items():
        if not isinstance(methods, dict):
            continue
        for method, spec in methods.items():
            if method.lower() not in {"get", "post"} or not isinstance(spec, dict):
                continue
            text = " ".join([
                str(path), str(spec.get("summary", "")),
                str(spec.get("description", "")),
                " ".join(map(str, spec.get("tags", []))),
            ]).lower()
            if any(k in text for k in ("etn", "債券", "bond", "指數投資證券", "證券基本資料")):
                hits.append({
                    "method": method.upper(), "path": path,
                    "summary": spec.get("summary", ""),
                    "description": spec.get("description", ""),
                    "tags": spec.get("tags", []),
                })
    return {"openapi_version": payload.get("openapi"), "title": payload.get("info", {}).get("title"),
            "path_count": len(payload["paths"]), "matching_routes": hits}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="audit-output/market-scope/tpex-openapi")
    args = parser.parse_args()
    out = Path(args.output_dir); out.mkdir(parents=True, exist_ok=True)
    import requests
    response = None
    for attempt in range(1, 4):
        try:
            response = requests.get(URL, timeout=(10, 60),
                headers={"User-Agent": "tw-stock-ai-openapi-catalog-audit/1.0", "Accept": "application/json"})
            response.raise_for_status()
            break
        except requests.RequestException:
            if attempt == 3: raise
            time.sleep(attempt * 2)
    raw = response.content
    (out / "tpex-openapi-swagger-raw.json").write_bytes(raw)
    payload = json.loads(raw.decode("utf-8-sig"))
    inspected = inspect_catalog(payload)
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_url": URL, "http_status": response.status_code,
        "content_type": response.headers.get("Content-Type", ""),
        "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
        **inspected, "security_codes_extracted": False,
        "classification_confirmed": False, "database_accessed": False,
        "database_modified": False, "five_year_quotes_downloaded": False,
        "quote_download_authorized": False,
    }
    (out / "tpex-openapi-catalog-audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"http_status": response.status_code, "path_count": report["path_count"],
        "matching_routes": report["matching_routes"], "database_modified": False,
        "five_year_quotes_downloaded": False}, ensure_ascii=False, sort_keys=True))

if __name__ == "__main__":
    main()
