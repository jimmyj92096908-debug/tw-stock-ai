"""Integrated, fail-closed Taiwan equity research model acceptance.

This module validates *committed* fitted-model evidence and assembles an
as-of-safe ranking and chip/composite freshness report. It never approves an
order, pushes a LINE message, trains on holdout labels, or updates a database.
"""
from __future__ import annotations

from datetime import date, datetime
import math

from trained_factor_model import (
    FEATURE_NAMES, VERSION, research_rank,
)

STOCK_STATUS_SQL = """
SELECT
 (SELECT MAX(trade_date) FROM public.daily_prices
   WHERE market=%s AND stock_id=%s AND close IS NOT NULL) AS latest_price_date,
 (SELECT MAX(trade_date) FROM public.daily_technicals
   WHERE market=%s AND stock_id=%s) AS latest_technical_date,
 (SELECT MAX(as_of_date) FROM public.daily_composite_scores
   WHERE market=%s AND stock_id=%s AND total_score IS NOT NULL) AS latest_composite_date,
 (SELECT total_score FROM public.daily_composite_scores
   WHERE market=%s AND stock_id=%s AND total_score IS NOT NULL
   ORDER BY as_of_date DESC LIMIT 1) AS latest_composite_score,
 (SELECT chip_score FROM public.daily_composite_scores
   WHERE market=%s AND stock_id=%s AND total_score IS NOT NULL
   ORDER BY as_of_date DESC LIMIT 1) AS composite_chip_component,
 (SELECT MAX(as_of_date) FROM public.daily_chip_scores
   WHERE market=%s AND stock_id=%s AND total_score IS NOT NULL
   AND coverage_weight >= 0.50) AS latest_publishable_chip_date,
 (SELECT total_score FROM public.daily_chip_scores
   WHERE market=%s AND stock_id=%s AND total_score IS NOT NULL
   AND coverage_weight >= 0.50 ORDER BY as_of_date DESC LIMIT 1)
   AS latest_publishable_chip_score,
 (SELECT coverage_weight FROM public.daily_chip_scores
   WHERE market=%s AND stock_id=%s AND total_score IS NOT NULL
   AND coverage_weight >= 0.50 ORDER BY as_of_date DESC LIMIT 1)
   AS latest_publishable_chip_coverage
"""


def _day(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            return None
        return parsed.isoformat() if parsed.isoformat() == value else None
    return None


def _number(value):
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def verify_fitted_model(model, evaluation):
    """A provenance/gating audit, not a claim of positive alpha or new holdout."""
    problems = []
    if model.get("version") != VERSION or evaluation.get("model_version") != VERSION:
        problems.append("model_version_mismatch")
    if model.get("feature_names") != list(FEATURE_NAMES):
        problems.append("feature_schema_mismatch")
    weights = model.get("weights")
    if (not isinstance(weights, list) or len(weights) != len(FEATURE_NAMES)
            or any(_number(w) is None for w in weights)):
        problems.append("invalid_model_coefficients")
    trained_through = _day(model.get("trained_through"))
    holdout_from = _day(model.get("holdout_from"))
    if not trained_through or not holdout_from or trained_through >= holdout_from:
        problems.append("invalid_train_holdout_order")
    if not model.get("development_sha256"):
        problems.append("no_development_row_fingerprint")
    if evaluation.get("holdout_is_pristine_independent_validation") is not True:
        problems.append("holdout_not_pristine")
    if evaluation.get("holdout_previously_examined_during_model_design") is True:
        problems.append("holdout_previously_examined")
    if model.get("holdout_previously_examined_during_model_design") is True:
        problems.append("model_discloses_previously_examined_holdout")

    holdout = evaluation.get("holdout")
    net_excess = _number(holdout.get("model_mean_net_excess")) if isinstance(holdout, dict) else None
    holdout_days = holdout.get("dates") if isinstance(holdout, dict) else None
    if not isinstance(holdout_days, int) or isinstance(holdout_days, bool) or holdout_days < 10:
        problems.append("insufficient_holdout_days")
    if net_excess is None or net_excess <= 0:
        problems.append("non_positive_holdout_net_excess")
    if evaluation.get("holdout_research_gate_passed") is not True:
        problems.append("reported_research_gate_failed")
    if any(model.get(k) is not False for k in ("may_send_trade_signals", "production_release_approved")):
        problems.append("model_release_flags_invalid")
    if any(evaluation.get(k) is not False for k in ("live_trading_approved", "line_signal_delivery_approved")):
        problems.append("evaluation_release_flags_invalid")

    # The evidence gate is separate from trade eligibility: no mechanism in
    # this research code is authorized to enable automated trades or LINE tips.
    return {
        "model_version": VERSION,
        "research_evidence_status": "INCOMPLETE_OR_FAILED" if problems else "RESEARCH_SCREEN_PASSED_ONLY",
        "research_evidence_problems": list(dict.fromkeys(problems)),
        "training_date": trained_through,
        "holdout_start": holdout_from,
        "holdout_dates": holdout_days,
        "holdout_net_excess": net_excess,
        "holdout_previously_examined": (
            evaluation.get("holdout_previously_examined_during_model_design") is True
        ),
        "production_release_approved": False,
        "line_signal_delivery_approved": False,
        "live_trading_approved": False,
    }


def stock_date_assessment(raw, *, market="twse", stock_id="2330"):
    """Report factor dates without joining a future chip factor to an old score."""
    price = _day(raw.get("latest_price_date"))
    technical = _day(raw.get("latest_technical_date"))
    composite = _day(raw.get("latest_composite_date"))
    chip = _day(raw.get("latest_publishable_chip_date"))
    chip_score = _number(raw.get("latest_publishable_chip_score"))
    coverage = _number(raw.get("latest_publishable_chip_coverage"))
    composite_score = _number(raw.get("latest_composite_score"))
    composite_chip = _number(raw.get("composite_chip_component"))

    source_age = None
    if price and chip:
        source_age = (date.fromisoformat(price) - date.fromisoformat(chip)).days
    current_chip = (
        source_age is not None and 0 <= source_age <= 7 and
        chip_score is not None and 0 <= chip_score <= 100 and
        coverage is not None and .5 <= coverage <= 1
    )
    technical_fresh = price is not None and price == technical
    composite_fresh = price is not None and price == composite
    # A newer independent score NEVER changes the stored historical composite.
    chip_later_than_composite = chip is not None and composite is not None and chip > composite
    return {
        "market": market, "stock_id": stock_id,
        "price_date": price, "technical_date": technical,
        "composite_date": composite,
        "composite_score": composite_score,
        "composite_chip_component": composite_chip,
        "independent_chip_date": chip,
        "independent_chip_score": chip_score if current_chip else None,
        "independent_chip_coverage": coverage if current_chip else None,
        "chip_age_calendar_days": source_age,
        "independent_chip_is_current": current_chip,
        "technical_matches_latest_price": technical_fresh,
        "composite_matches_latest_price": composite_fresh,
        "new_chip_not_in_older_composite": chip_later_than_composite,
        "model_data_ready_for_current_ranking": (
            technical_fresh and composite_fresh
        ),
    }


def assemble_research_bundle(
    model, evaluation, ranking_rows, stock_raw, *, market="twse",
    stock_id="2330", limit=10,
):
    audit = verify_fitted_model(model, evaluation)
    stock = stock_date_assessment(stock_raw, market=market, stock_id=stock_id)
    safe_ranking = None
    # Only use matched score/price observations. The ranker itself enforces
    # same-day joins and refuses cross-date cohorts or invalid score coverage.
    if "invalid_model_coefficients" not in audit["research_evidence_problems"] and \
       "model_version_mismatch" not in audit["research_evidence_problems"] and \
       "feature_schema_mismatch" not in audit["research_evidence_problems"]:
        safe_ranking = research_rank(ranking_rows, model, limit=limit)
    if safe_ranking is None:
        safe_ranking = {
            "model_version": VERSION, "date": None, "stocks": [],
            "abstain": True, "reason": "invalid_fitted_model"
        }
    model_date = safe_ranking.get("date")
    latest_price = stock["price_date"]
    # Do not label an older ranking as a live/current market forecast.
    latest_ranking_is_price_current = (
        model_date is not None and latest_price is not None and
        model_date == latest_price
    )
    return {
        "report_type": "taiwan_stock_research_model_bundle_v1",
        "model": audit,
        "stock_data": stock,
        "ranking": safe_ranking,
        "ranking_matches_reference_price_date": latest_ranking_is_price_current,
        "overall_status": (
            "RESEARCH_ONLY_EVIDENCE_BLOCKED"
            if audit["research_evidence_problems"]
            else "RESEARCH_ONLY_REQUIRES_INDEPENDENT_RELEASE_REVIEW"
        ),
        "abstain_from_trading": True,
        "publish_line_trade_signal": False,
        "orders_enabled": False,
        "production_database_modified": False,
        "warning": (
            "研究結果不可視為即時預測、買賣建議或實際可執行報酬。"
            "不同資料日的籌碼與綜合評分不可逕行合併。"
        ),
    }
