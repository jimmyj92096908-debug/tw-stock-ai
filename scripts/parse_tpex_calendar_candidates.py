#!/usr/bin/env python3
"""Extract conservative, review-only date candidates from archived official TPEx calendars.

This is not a trading-calendar generator. It preserves source context and never
labels a date as an accepted closure/session. Human market-scope review remains
mandatory, especially for bond-system and settlement-only references.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

CHINESE_DATE = re.compile(r"(?<!\d)(1[0-2]|0?[1-9])\s*月\s*(3[01]|[12]\d|0?[1-9])\s*日")
ENGLISH_DATE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(3[01]|[12]\d|0?[1-9])\b",
    re.IGNORECASE,
)
ENGLISH_MONTH = {name.lower(): i for i, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"), 1
)}
EQUITY_TERMS = ("股票交易系統", "Listed Stock", "Emerging Stock")
BOND_TERMS = ("國際債券", "債券等殖", "債券處所", "Bond EBTS", "International Bond")
SETTLEMENT_TERMS = ("給付結算", "清算", "交割", "Clearing & Settlement")


def classify_context(context: str) -> str:
    if any(term.lower() in context.lower() for term in BOND_TERMS):
        return "bond_or_non_equity_scope_review"
    if any(term.lower() in context.lower() for term in EQUITY_TERMS):
        return "explicit_equity_scope_candidate"
    if any(term in context for term in SETTLEMENT_TERMS):
        return "settlement_only_or_mixed_scope_review"
    return "general_or_unclear_market_scope_review"


def extract_candidates(text: str, roc_year: int, source_sha256: str) -> list[dict[str, Any]]:
    """Extract date tokens with nearby context; never infer closure from a token."""
    gregorian_year = roc_year + 1911
    lines = text.replace("\\r", "\r").replace("\\n", "\n").replace("\r", "\n").splitlines()
    found: dict[tuple[int, int], dict[str, Any]] = {}
    for index, line in enumerate(lines):
        matches: list[tuple[int, int]] = []
        for match in CHINESE_DATE.finditer(line):
            matches.append((int(match.group(1)), int(match.group(2))))
        for match in ENGLISH_DATE.finditer(line):
            matches.append((ENGLISH_MONTH[match.group(1).lower()], int(match.group(2))))
        # PDF text extraction may split month and day into separate lines;
        # scan a short joined window, but retain the occurrence's local context.
        window = " ".join(lines[index:index + 3])
        for match in ENGLISH_DATE.finditer(window):
            pair = (ENGLISH_MONTH[match.group(1).lower()], int(match.group(2)))
            if pair not in matches:
                matches.append(pair)
        for month, day in matches:
            if day > 31:
                continue
            context = " | ".join(part.strip() for part in lines[max(0, index - 1):min(len(lines), index + 3)] if part.strip())
            key = (month, day)
            item = found.setdefault(key, {
                "date": f"{gregorian_year:04d}-{month:02d}-{day:02d}",
                "roc_year": roc_year,
                "source_sha256": source_sha256,
                "occurrences": [],
            })
            item["occurrences"].append({
                "line_number": index + 1,
                "context": context[:1200],
                "scope_classification": classify_context(context),
                "calendar_status": "candidate_only_not_accepted",
            })
    return sorted(found.values(), key=lambda item: item["date"])


def parse_directory(input_dir: Path) -> dict[str, Any]:
    records = []
    errors = []
    for path in sorted(input_dir.glob("*.txt")):
        match = re.fullmatch(r"(\d{3})\.txt", path.name)
        if not match:
            continue
        roc_year = int(match.group(1))
        raw = path.read_bytes()
        text = raw.decode("utf-8", "replace")
        records.extend(extract_candidates(text, roc_year, hashlib.sha256(raw).hexdigest()))
    if not records:
        errors.append("No ROC-year .txt files found; expected names such as 112.txt.")
    return {
        "schema_version": 1,
        "source_scope": "Archived official TPEx annual calendar text; extraction candidates only",
        "records": records,
        "record_count": len(records),
        "calendar_days_accepted": False,
        "trading_sessions_generated": False,
        "automatic_closure_inference": False,
        "errors": errors,
        "review_policy": [
            "A date token is not proof of a market closure.",
            "Bond-system, settlement-only, and make-up-workday references must not be treated as equity trading sessions.",
            "Every candidate requires source-document and market-specific manual validation.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", default="audit-output/market-scope/tpex-calendar")
    parser.add_argument("--output", default="audit-output/market-scope/tpex-calendar-candidates.json")
    args = parser.parse_args()
    result = parse_directory(Path(args.input_dir))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    scope_counts: dict[str, int] = {}
    for record in result["records"]:
        for occurrence in record["occurrences"]:
            label = occurrence["scope_classification"]
            scope_counts[label] = scope_counts.get(label, 0) + 1
    print(json.dumps({
        "record_count": result["record_count"],
        "occurrence_count": sum(len(x["occurrences"]) for x in result["records"]),
        "scope_classification_counts": dict(sorted(scope_counts.items())),
        "calendar_days_accepted": False,
        "trading_sessions_generated": False,
        "output": str(output),
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
