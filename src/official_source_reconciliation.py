"""Conservative reconciliation for TPEx official endpoint evidence.

This module never imputes OHLC or interprets missing rows as zero trading.
"""
from __future__ import annotations

from datetime import date
from typing import Any


MISSING = {"", "--", "-", "—", "－", "N/A", "NA"}


def _roc_date(value: Any) -> str | None:
    text = str(value or "").strip().rstrip("*＊")
    parts = text.split("/")
    if len(parts) != 3:
        return None
    try:
        year, month, day = map(int, parts)
        return date(year + 1911, month, day).isoformat()
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if text in MISSING:
        return None
    try:
        result = float(text)
    except ValueError:
        return None
    return result


def _monthly_observation(payload: dict | None, trade_date: str) -> dict | None:
    if not isinstance(payload, dict):
        return None
    for table in payload.get("tables") or []:
        fields = table.get("fields") or []
        for row in table.get("data") or []:
            if not row or _roc_date(row[0]) != trade_date:
                continue
            if len(row) < len(fields):
                return {"row_found": True, "row_length": len(row), "fields_length": len(fields)}
            return {"row_found": True, **dict(zip(fields, row))}
    return None


def _bulk_observation(payload: dict | None, stock_id: str) -> dict | None:
    if not isinstance(payload, dict):
        return None
    for table in payload.get("tables") or []:
        fields = table.get("fields") or []
        rows = table.get("data") or []
        for row in rows:
            if row and str(row[0]).strip() == stock_id:
                if len(row) < len(fields):
                    return {"row_found": True, "row_length": len(row), "fields_length": len(fields)}
                return {
                    "row_found": True,
                    "total_count": table.get("totalCount"),
                    **dict(zip(fields, row)),
                }
        if not rows:
            return {
                "row_found": False,
                "total_count": table.get("totalCount"),
                "table_title": table.get("title"),
                "fields": fields,
            }
    return None


def reconcile_tpex_payloads(
    monthly_payload: dict | None,
    bulk_payload: dict | None,
    stock_id: str,
    trade_date: str,
) -> dict:
    monthly = _monthly_observation(monthly_payload, trade_date)
    bulk = _bulk_observation(bulk_payload, stock_id)

    if not monthly or not monthly.get("row_found"):
        return {
            "classification": "pending_review",
            "reason": "monthly_endpoint_target_row_not_found",
            "monthly_row_found": False,
            "bulk_row_found": bool(bulk and bulk.get("row_found")),
        }

    monthly_volume_lots = _number(monthly.get("成交張數"))
    monthly_ohlc = {
        key: _number(monthly.get(label))
        for key, label in (("open", "開盤"), ("high", "最高"), ("low", "最低"), ("close", "收盤"))
    }
    monthly_has_missing_ohlc = any(v is None for v in monthly_ohlc.values())
    monthly_positive_volume = monthly_volume_lots is not None and monthly_volume_lots > 0

    if not bulk or not bulk.get("row_found"):
        count = bulk.get("total_count") if bulk else None
        if monthly_positive_volume and count == 0:
            return {
                "classification": "source_conflict",
                "reason": "monthly_individual_positive_volume_but_bulk_table_total_count_zero",
                "monthly_row_found": True,
                "monthly_volume_lots": monthly_volume_lots,
                "monthly_ohlc": monthly_ohlc,
                "bulk_row_found": False,
                "bulk_total_count": count,
                "bulk_table_title": bulk.get("table_title") if bulk else None,
                "ohlc_imputed": False,
            }
        return {
            "classification": "pending_review",
            "reason": "bulk_target_row_absent_without_confirmed_zero_count",
            "monthly_row_found": True,
            "monthly_volume_lots": monthly_volume_lots,
            "monthly_ohlc": monthly_ohlc,
            "bulk_row_found": False,
            "bulk_total_count": count,
            "ohlc_imputed": False,
        }

    bulk_ohlc = {
        key: _number(bulk.get(label))
        for key, label in (("open", "開盤 "), ("high", "最高 "), ("low", "最低"), ("close", "收盤 "))
    }
    return {
        "classification": "pending_review",
        "reason": "bulk_row_found_field_level_unit_and_value_validation_required",
        "monthly_row_found": True,
        "monthly_volume_lots": monthly_volume_lots,
        "monthly_ohlc": monthly_ohlc,
        "monthly_ohlc_missing": monthly_has_missing_ohlc,
        "bulk_row_found": True,
        "bulk_ohlc": bulk_ohlc,
        "bulk_volume_shares": _number(bulk.get("成交股數  ")),
        "ohlc_imputed": False,
    }
