"""Conservative, non-probabilistic evidence completeness assessment.

The data_quality_index is NOT the chance of profitable trading. It measures
only verified factor availability, dates and history. Missing or stale critical
fields cannot get a usable numeric quality index.
"""
from __future__ import annotations

from datetime import date, datetime
import math


def _day(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def data_quality_assessment(stock: dict, raw: dict) -> dict:
    """Verify current priced/technical/SMC/composite dates before grading.

    Optional raw additions: valid_price_days, latest_composite_coverage,
    latest_smc_date. Absence is treated as missing evidence, not 100% quality.
    """
    price = _day(stock.get("price_date"))
    tech = _day(stock.get("technical_date"))
    score_day = _day(stock.get("composite_date"))
    smc = _day(raw.get("latest_smc_date"))
    coverage = _num(raw.get("latest_composite_coverage"))
    days_raw = raw.get("valid_price_days")
    days = days_raw if type(days_raw) is int and days_raw >= 0 else None
    reason = []
    if price is None:
        reason.append("NO_VALID_REFERENCE_PRICE_DATE")
    if price is None or tech != price:
        reason.append("TECHNICAL_NOT_ON_LATEST_PRICE_DATE")
    if price is None or smc != price:
        reason.append("SMC_NOT_ON_LATEST_PRICE_DATE")
    if price is None or score_day != price:
        reason.append("SCORE_NOT_ON_LATEST_PRICE_DATE")
    if coverage is None or not 0.5 <= coverage <= 1:
        reason.append("FACTOR_COVERAGE_UNVERIFIED")
    if days is None:
        reason.append("HISTORY_LENGTH_UNVERIFIED")
    elif days < 60:
        reason.append("UNDER_60_VALID_PRICE_SESSIONS")

    critical = ("NO_VALID_REFERENCE_PRICE_DATE",
                "TECHNICAL_NOT_ON_LATEST_PRICE_DATE",
                "SMC_NOT_ON_LATEST_PRICE_DATE",
                "SCORE_NOT_ON_LATEST_PRICE_DATE",
                "FACTOR_COVERAGE_UNVERIFIED",
                "HISTORY_LENGTH_UNVERIFIED",
                "UNDER_60_VALID_PRICE_SESSIONS")
    # Chip evidence is described separately; NEVER attach a newer independent
    # chip date to an older composite or silently assume it was incorporated.
    chip_included = stock.get("composite_chip_component") is not None
    chip_current = stock.get("independent_chip_is_current") is True
    if not chip_included:
        reason.append("CHIP_NOT_IN_CURRENT_COMPOSITE")
    chip_coverage = _num(stock.get("independent_chip_coverage"))
    if chip_included and not chip_current:
        reason.append("CHIP_SOURCE_DATE_OR_COVERAGE_UNVERIFIED")
    ready = not any(x in reason for x in critical)
    idx = None
    if ready:
        assert coverage is not None and days is not None
        history_fraction = min(days / 240, 1)
        chip_provenance = (
            min(chip_coverage, 1) if chip_current and chip_coverage is not None else 0.0
        )
        idx = round(100*(0.45*coverage + 0.30*history_fraction +
                         0.15*chip_provenance + 0.10), 1)
    return {
        "status": "CURRENT_EVIDENCE_PARTIAL" if ready else "INSUFFICIENT_CURRENT_EVIDENCE",
        "data_quality_index": idx,
        "is_probability_of_profit": False,
        "factors_recorded_coverage": coverage,
        "valid_price_sessions": days,
        "on_latest_valid_price_date": ready,
        "composite_contains_chip": chip_included,
        "independent_chip_source_current": chip_current,
        "reasons": reason,
        "trading_approved": False,
    }
