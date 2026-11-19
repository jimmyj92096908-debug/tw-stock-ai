"""Read-only reconciliation of daily OHLC data against official source observations.

This module classifies evidence only. It never repairs, imputes, or writes market data.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence


FIELDS = ("open", "high", "low", "close", "volume", "transactions")


@dataclass(frozen=True)
class SourceAudit:
    status: str
    reason: str
    eligible_for_indicators: bool
    conflicting_fields: tuple[str, ...] = ()


def _number(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        result = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None


def _has_complete_ohlc(row: Mapping[str, Any]) -> bool:
    values = [_number(row.get(key)) for key in ("open", "high", "low", "close")]
    if any(value is None or value <= 0 for value in values):
        return False
    opening, high, low, close = values
    return high >= max(opening, low, close) and low <= min(opening, high, close)


def classify_source_evidence(
    database_row: Mapping[str, Any],
    source_observations: Sequence[Mapping[str, Any]] = (),
) -> SourceAudit:
    """Classify database values and optional independent official observations.

    Each observation may contain a source label and any of open/high/low/close,
    volume, transactions. Missing fields are not treated as zero. Two or more
    different non-null values for the same field constitute a source conflict.
    """
    conflicts: list[str] = []
    for field in FIELDS:
        observed = {
            value
            for item in source_observations
            if (value := _number(item.get(field))) is not None
        }
        if len(observed) > 1:
            conflicts.append(field)

    if conflicts:
        return SourceAudit(
            "source_conflict",
            "official_sources_disagree:" + ",".join(conflicts),
            False,
            tuple(conflicts),
        )

    volume = _number(database_row.get("volume"))
    ohlc_values = [_number(database_row.get(key)) for key in ("open", "high", "low", "close")]
    all_ohlc_missing = all(value is None for value in ohlc_values)

    if _has_complete_ohlc(database_row):
        return SourceAudit("valid", "complete_consistent_ohlc", True)

    if volume is not None and volume > 0 and all_ohlc_missing:
        if source_observations:
            source_has_ohlc = any(_has_complete_ohlc(item) for item in source_observations)
            if not source_has_ohlc:
                return SourceAudit(
                    "official_sources_missing_ohlc_with_volume",
                    "positive_volume_but_all_checked_official_sources_lack_complete_ohlc",
                    False,
                )
        return SourceAudit(
            "positive_volume_no_ohlc",
            "positive_volume_with_all_database_ohlc_null",
            False,
        )

    if volume == 0 and all_ohlc_missing:
        return SourceAudit(
            "zero_volume_no_ohlc_unconfirmed",
            "zero_volume_and_all_ohlc_null_do_not_prove_no_trade_without_source_semantics",
            False,
        )

    if volume is None:
        return SourceAudit("pending_review", "volume_missing_or_non_numeric", False)

    if any(value is None for value in ohlc_values):
        return SourceAudit("pending_review", "partial_or_non_numeric_ohlc", False)

    return SourceAudit("invalid", "non_positive_or_inconsistent_ohlc", False)
