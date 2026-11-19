"""Conservative reconciliation for TPEx official endpoint evidence.

This module never imputes OHLC or interprets missing rows as zero trading.
"""
from __future__ import annotations

from datetime import date
import math
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
    return result if math.isfinite(result) else None


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


def _find_table_row_by_code(payload: dict | None, stock_id: str) -> dict | None:
    """Find a stock row using response-declared field names; never rely on column positions."""
    if not isinstance(payload, dict):
        return None
    tables = payload.get("tables") or []
    if not tables and payload.get("fields") and payload.get("data") is not None:
        tables = [payload]
    for table in tables:
        fields = [str(x).strip() for x in (table.get("fields") or [])]
        if not fields:
            continue
        code_index = next((i for i, name in enumerate(fields) if name in {"證券代號", "代號", "股票代號"}), None)
        if code_index is None:
            continue
        for row in table.get("data") or []:
            if len(row) <= code_index or str(row[code_index]).strip() != stock_id:
                continue
            if len(row) < len(fields):
                return {"row_found": True, "row_length": len(row), "fields_length": len(fields)}
            return {"row_found": True, **dict(zip(fields, row))}
    return None


def _valid_ohlc(values: dict) -> bool:
    prices = [values.get(k) for k in ("open", "high", "low", "close")]
    if any(v is None or v <= 0 for v in prices):
        return False
    open_, high, low, close = prices
    return low <= min(open_, close) and max(open_, close) <= high


def reconcile_twse_payloads(
    monthly_payload: dict | None,
    daily_payload: dict | None,
    stock_id: str,
    trade_date: str,
) -> dict:
    """Cross-check TWSE monthly individual and daily all-market records."""
    monthly_row = None
    if isinstance(monthly_payload, dict):
        for row in monthly_payload.get("data") or []:
            if row and _roc_date(row[0]) == trade_date:
                monthly_row = row
                break
    monthly_fields = [
        "日期", "成交股數", "成交金額", "開盤價", "最高價",
        "最低價", "收盤價", "漲跌價差", "成交筆數",
    ]
    monthly = None
    if monthly_row is not None and len(monthly_row) >= len(monthly_fields):
        monthly = dict(zip(monthly_fields, monthly_row))
    daily = _find_table_row_by_code(daily_payload, stock_id)

    if monthly is None or not daily or not daily.get("row_found"):
        return {
            "classification": "pending_review",
            "reason": "one_or_both_twse_source_rows_missing_or_malformed",
            "monthly_row_found": monthly_row is not None,
            "daily_row_found": bool(daily and daily.get("row_found")),
            "ohlc_imputed": False,
        }

    monthly_ohlc = {
        key: _number(monthly.get(label))
        for key, label in (("open", "開盤價"), ("high", "最高價"), ("low", "最低價"), ("close", "收盤價"))
    }
    daily_ohlc = {
        key: _number(daily.get(label))
        for key, label in (("open", "開盤價"), ("high", "最高價"), ("low", "最低價"), ("close", "收盤價"))
    }
    monthly_volume = _number(monthly.get("成交股數"))
    daily_volume = _number(daily.get("成交股數"))
    monthly_trades = _number(monthly.get("成交筆數"))
    daily_trades = _number(daily.get("成交筆數"))

    if not _valid_ohlc(monthly_ohlc) or not _valid_ohlc(daily_ohlc):
        return {
            "classification": "pending_review",
            "reason": "ohlc_missing_or_invalid_in_at_least_one_source",
            "monthly_ohlc": monthly_ohlc,
            "daily_ohlc": daily_ohlc,
            "monthly_volume_shares": monthly_volume,
            "daily_volume_shares": daily_volume,
            "ohlc_imputed": False,
        }

    fields_match = monthly_ohlc == daily_ohlc
    volume_match = monthly_volume is not None and daily_volume is not None and monthly_volume == daily_volume
    trades_match = monthly_trades is not None and daily_trades is not None and monthly_trades == daily_trades
    if fields_match and volume_match and trades_match:
        classification, reason = "corroborated", "all_available_ohlc_volume_and_trade_count_fields_match"
    else:
        classification, reason = "source_conflict", "twse_monthly_and_daily_market_fields_disagree"
    return {
        "classification": classification,
        "reason": reason,
        "monthly_ohlc": monthly_ohlc,
        "daily_ohlc": daily_ohlc,
        "monthly_volume_shares": monthly_volume,
        "daily_volume_shares": daily_volume,
        "monthly_trade_count": monthly_trades,
        "daily_trade_count": daily_trades,
        "ohlc_match": fields_match,
        "volume_match": volume_match,
        "trade_count_match": trades_match,
        "ohlc_imputed": False,
    }
