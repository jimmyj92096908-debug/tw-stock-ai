"""Classify TWSE positive-volume OHLC gaps using official individual-month evidence.

This is a read-only evidence classifier. It never fills prices or accesses Neon.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

OHLC_FIELDS = ("open", "high", "low", "close")


def valid_ohlc(item: dict[str, Any]) -> bool:
    values = [item.get(field) for field in OHLC_FIELDS]
    if any(value is None for value in values):
        return False
    try:
        opened, high, low, close = (float(value) for value in values)
    except (TypeError, ValueError):
        return False
    return all(value > 0 for value in (opened, high, low, close)) and high >= max(opened, close, low) and low <= min(opened, close, high)


def classify_record(bulk: dict[str, Any], individual: dict[str, Any] | None) -> dict[str, Any]:
    """Return a conservative classification; never infer a missing price."""
    result = {
        "trade_date": bulk.get("trade_date"),
        "stock_id": bulk.get("stock_id"),
        "bulk_volume": bulk.get("volume"),
        "bulk_turnover": bulk.get("turnover"),
        "classification": None,
        "review_required": True,
        "price_imputation_allowed": False,
    }
    if individual is None or individual.get("individual_source_status") != "matched":
        result["classification"] = "INDIVIDUAL_SOURCE_NO_MATCH"
        result["reason"] = "No matching official individual-month row; retain OHLC as NULL."
        return result

    result["individual_volume"] = individual.get("volume")
    result["individual_turnover"] = individual.get("turnover")
    result["individual_ohlc"] = {field: individual.get(field) for field in OHLC_FIELDS}

    values_present = [individual.get(field) is not None for field in OHLC_FIELDS]
    if all(values_present) and valid_ohlc(individual):
        if (
            bulk.get("volume") == individual.get("volume")
            and bulk.get("turnover") == individual.get("turnover")
        ):
            result["classification"] = "INDIVIDUAL_OHLC_AVAILABLE_BULK_GAP"
            result["reason"] = (
                "Official individual source has valid OHLC and volume/turnover match. "
                "This is a confirmed source discrepancy, but not authorization for automatic backfill."
            )
        else:
            result["classification"] = "INDIVIDUAL_OHLC_AVAILABLE_VALUES_MISMATCH"
            result["reason"] = (
                "Official individual source has valid OHLC, but volume or turnover differs; "
                "manual source reconciliation is required."
            )
        return result

    if any(values_present):
        result["classification"] = "INDIVIDUAL_OHLC_PARTIAL_OR_INVALID"
        result["reason"] = "Official individual source has partial or invalid OHLC; retain missing values as NULL."
    else:
        result["classification"] = "OFFICIAL_INDIVIDUAL_OHLC_MISSING"
        result["reason"] = (
            "The official individual-month source also reports no OHLC. "
            "The underlying trading mechanism is not established; retain OHLC as NULL."
        )
    return result


def build_report(bulk_report: dict[str, Any], individual_report: dict[str, Any]) -> dict[str, Any]:
    lookup = {
        (row.get("trade_date"), row.get("stock_id")): row
        for row in individual_report.get("comparisons", [])
    }
    classified = [
        classify_record(
            row,
            lookup.get((row.get("trade_date"), row.get("stock_id"))),
        )
        for row in bulk_report.get("records", [])
    ]
    counts: dict[str, int] = {}
    for row in classified:
        key = row["classification"]
        counts[key] = counts.get(key, 0) + 1
    return {
        "report_type": "twse_ohlc_gap_classification",
        "read_only": True,
        "database_accessed": False,
        "database_modified": False,
        "price_imputation_performed": False,
        "automatic_backfill_allowed": False,
        "record_count": len(classified),
        "classification_counts": dict(sorted(counts.items())),
        "records": classified,
        "interpretation": (
            "Classification describes observed source evidence only. It does not identify "
            "the underlying trading mechanism and never authorizes automatic price imputation."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bulk", default="audit-output/twse-positive-volume-missing-ohlc.json")
    parser.add_argument("--individual", default="audit-output/twse-individual-stock-reconciliation.json")
    parser.add_argument("--output", default="audit-output/twse-ohlc-gap-classification.json")
    args = parser.parse_args()
    bulk = json.loads(Path(args.bulk).read_text(encoding="utf-8"))
    individual = json.loads(Path(args.individual).read_text(encoding="utf-8"))
    report = build_report(bulk, individual)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "record_count": report["record_count"],
        "classification_counts": report["classification_counts"],
        "database_accessed": False,
        "price_imputation_performed": False,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
