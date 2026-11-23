"""Owner-local OFFLINE five-year TWSE AES + Neon report source-day overlay.

Consumes TWO existing separate owner-verified reports:
  * 2022 official TWSE AES 162 days + Neon 84 days, full date-source
    reconciliation for only frozen20 stocks (no historical PIT proof).
  * 2021..2026 official current-listed Neon-only 5-year market/year summary.

Never reads real AES/plain prices, calls Neon, fetches official data, writes
company actions or modifies model. Reconciles only aggregate distinct 2022
source-calendar days, NOT authenticated full-market per-stock coverage, nor
an assertion that 84 TWSE days with >=500 bars are identical date sets
to 84 source-calendar days from the frozen panel.
"""
from __future__ import annotations

import argparse
from datetime import date
import json

from scripts.twse_2021_22_traded_240_warmup_readonly import _private_file
from scripts.twse_tpex_five_year_neon_only_cohort_readonly import SCOPE as NEON_SCOPE

SCOPE = "OWNER_TWSE_2022_OFFLINE_VERIFIED_AES_NEON_SOURCE_CALENDAR_OVERLAY"
SOURCE_SCOPE = "TWSE_2022_LOCAL_AES_EXISTING_NEON_READONLY_FROZEN20_FACTOR_RESEARCH"
DATE_START = date(2022, 1, 1)
DATE_END = date(2022, 12, 31)
MAX_REPORT_BYTES = 24000


def reconcile_offline(source, neon):
    """Pure, conservative, fail-closed exact prior receipts reconciliation."""
    if (not isinstance(source, dict) or source.get("schema_version") != 1
            or source.get("scope") != SOURCE_SCOPE
            or source.get("neon_transaction_mode") != "READ_ONLY"
            or source.get("neon_write_operations") != 0
            or source.get("line_messages_sent") != 0
            or source.get("live_model_release_decision") != "BLOCKED"
            or source.get("complete_five_year_history_verified") is not False
            or source.get("dividends_splits_or_total_return_adjusted") is not False
            or source.get("historical_delisted_survivorship_bias_removed") is not False
            or source.get("frozen_current_research_stock_count") != 20
            or source.get("frozen_stocks_with_complete_last_240_source_sessions") != 18
            or source.get("missing_sma240_stock_count") != 2
            or source.get("local_2022_source_sessions") != 162
            or source.get("neon_source_sessions") != 84
            or source.get("overlapping_source_sessions") != 0
            or source.get("unique_observed_2022_source_sessions") != 246
            or source.get("first_combined_session") != "2022-01-03"
            or source.get("last_combined_session") != "2022-12-30"):
        raise ValueError("Owner's 2022 162 AES + 84 source-date read-only receipt not accepted")
    # Prevent fabricated calendar coverage by algebraically reconciling
    # counts from previous verified owner sources.
    aes = source["local_2022_source_sessions"]
    stored = source["neon_source_sessions"]
    overlap = source["overlapping_source_sessions"]
    combined = source["unique_observed_2022_source_sessions"]
    if (aes + stored - overlap != combined
            or not 0 <= overlap <= min(aes, stored)):
        raise ValueError("Impossible AES + Neon original official date reconciliation")
    if (not isinstance(neon, dict) or neon.get("schema_version") != 1
            or neon.get("scope") != NEON_SCOPE
            or neon.get("model_release") != "BLOCKED"
            or neon.get("production_neon_writes") != 0
            or neon.get("line_messages_sent") != 0
            or neon.get("five_year_history_completed") is not False
            or neon.get("excludes_owner_private_aes_and_non_neon_source_history") is not True
            or neon.get("current_listed_issuers_only_not_historical_pit_membership") is not True
            or neon.get("owner_aes_2021_2022_source_not_included") is not True
            or not isinstance(neon.get("market"), dict)
            or set(neon["market"]) != {"twse", "tpex"}):
        raise ValueError("Owner's new Neon-only TWSE/TPEx five-year coverage proof invalid")
    try:
        begin = date.fromisoformat(neon["window_start_inclusive"])
        end = date.fromisoformat(neon["window_end_exclusive"])
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError("Invalid recorded five-year owner audit window") from exc
    if (not date(2021, 1, 1) <= begin < DATE_START
            or not DATE_END < end <= date(2027, 1, 1)):
        raise ValueError("Only actual 2022-inclusive owner five-year audit supported")

    market_results = {}
    totals_240 = totals_1000 = 0
    for market in ("twse", "tpex"):
        stat = neon["market"][market]
        if not isinstance(stat, dict):
            raise ValueError("Invalid market response payload")
        population = stat.get("official_current_listed_stocks_excluding_1589")
        ready240 = stat.get("with_at_least_240_valid_stored_days")
        ready1000 = stat.get("with_at_least_1000_valid_stored_days")
        if (type(population) is not int or population < 700
                or type(ready240) is not int or type(ready1000) is not int
                or not 0 <= ready1000 <= ready240 <= population):
            raise ValueError("Impossible official current listing, trading-day maturity totals")
        years = stat.get("yearly_neon_source_observations")
        if not isinstance(years, list) or len(years) != 6:
            raise ValueError("Six actual annual Neon coverage segments required")
        seq = {}
        for r in years:
            if not isinstance(r, dict) or type(r.get("year")) is not int:
                raise ValueError("Invalid yearly Neon source receipt")
            yr = r["year"]
            if (yr in seq or yr < 2021 or yr > 2026
                    or any(type(r.get(k)) is not int or r[k] < 0 for k in (
                        "days_with_any_neon_eligible_source_bars",
                        "days_with_at_least_500_eligible_source_bars",
                        "neon_stored_valid_source_stock_bars"))
                    or r["days_with_at_least_500_eligible_source_bars"] >
                       r["days_with_any_neon_eligible_source_bars"]
                    or r["days_with_any_neon_eligible_source_bars"] > 366
                    or r["neon_stored_valid_source_stock_bars"] >
                       population * r["days_with_any_neon_eligible_source_bars"]):
                raise ValueError("Invalid or inflated yearly Neon source coverage")
            seq[yr] = r
        if set(seq) != set(range(2021, 2027)):
            raise ValueError("Incomplete 2021..2026 official current-list market-year ledger")
        days_any = seq[2022]["days_with_any_neon_eligible_source_bars"]
        high = seq[2022]["days_with_at_least_500_eligible_source_bars"]
        if (market == "twse" and
                (seq[2021]["days_with_any_neon_eligible_source_bars"] != 28 or
                 seq[2021]["days_with_at_least_500_eligible_source_bars"] != 0)):
            raise ValueError("Old 2021 sparse Neon source snapshot has changed")
        if days_any != combined or (
                market == "twse" and high != stored) or (
                market == "tpex" and high != combined):
            raise ValueError("2022 Neon annual source counts inconsistent with old 2022 witness")
        totals_240 += ready240
        totals_1000 += ready1000
        market_results[market] = {
            "currently_listed_owner_eligible_stock_count": population,
            "at_least_240_neon_stored_valid_days": ready240,
            "at_least_1000_neon_stored_valid_days": ready1000,
            "neon_2022_days_with_any_eligible_source_stock": days_any,
            "neon_2022_days_with_at_least_500_current_stock_bars": high,
            "source_2022_year_research_gap": (
                "TWSE_162_LOCAL_AES_SOURCE_DAYS_WITHOUT_NEON_HIGH_DENSITY_BULK"
                if market == "twse" else
                "NO_2022_MISSING_DATES_OBSERVED_AT_500_STOCK_HEURISTIC"
            ),
        }
    return {
        "schema_version": 1,
        "scope": SCOPE,
        "study_year": 2022,
        "owner_prior_2022_source_report_scope": SOURCE_SCOPE,
        "owner_prior_5y_neon_report_scope": NEON_SCOPE,
        "neon_window_start_inclusive": begin.isoformat(),
        "neon_window_end_exclusive": end.isoformat(),
        "markets": market_results,
        "twse_2022_authenticated_local_aes_source_days": aes,
        "twse_2022_verified_neon_official_bulk_source_days": stored,
        "twse_2022_prior_source_calendar_date_overlap": overlap,
        "twse_2022_deduplicated_observed_source_calendar_dates": combined,
        "twse_2022_neon_current_stock_500_bar_dates": (
            market_results["twse"]["neon_2022_days_with_at_least_500_current_stock_bars"]),
        "2022_neon_500_bar_dates_and_source_bulk_84_day_sets_proven_identical": False,
        "2022_private_aes_has_at_least_500_today_listed_stocks_on_all_162_dates_proven": False,
        "virtual_2022_twse_source_calendar_date_count": combined,
        "virtual_2022_twse_full_market_per_stock_coverage_verified": False,
        "twse_current_frozen20_raw_sma240_by_market_day_complete": 18,
        "twse_current_frozen20_nontrade_halt_stock_days_known": 14,
        "current_listed_stocks_total": sum(
            v["currently_listed_owner_eligible_stock_count"]
            for v in market_results.values()),
        "neon_only_current_listed_240_day_ready_total": totals_240,
        "neon_only_current_listed_1000_day_ready_total": totals_1000,
        "owner_private_aes_not_counted_as_existing_neon_rows": True,
        "2021_twse_28_neon_observed_dates_not_independent_full_500_stock_days": True,
        "safe_priority_next": [
            "AUTHENTICATE_2022_AES_162_SOURCE_DATES_AND_PER_STOCK_ELIGIBLE_COVERAGE",
            "DATEWISE_VERIFY_NEON_OFFICIAL_BULK_84_VS_HIGH_DENSITY_84",
            "KEEP_PRIVATE_2021_AES_SEPARATE_AND_CHECK_REAL_TRADING_DATES",
            "VALIDATE_OTHER_CORPORATE_ACTIONS_BEFORE_ADJUSTED_TOTAL_RETURN",
            "DEVELOP_FIVE_YEAR_PIT_AND_WALK_FORWARD_ONLY_AFTER_DATA_EVIDENCE",
        ],
        "complete_five_year_price_bars_verified": False,
        "complete_adjusted_dividends_and_total_return_proven": False,
        "history_survivorship_unbiased": False,
        "model_release": "BLOCKED",
        "production_neon_writes": 0,
        "line_messages_sent": 0,
        "extra_paid_services": False,
    }


def main():
    p = argparse.ArgumentParser(description="Offline owner-private 2022 AES/Neon vs five-year source date audit")
    p.add_argument("--prior-2022-panel", required=True)
    p.add_argument("--neon-five-year-report", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    try:
        a = _private_file(args.prior_2022_panel, should_exist=True)
        b = _private_file(args.neon_five_year_report, should_exist=True)
        target = _private_file(args.out, should_exist=False)
        if len({a, b, target}) != 3:
            raise ValueError("Old owner reports and new output must be distinct")
        report = reconcile_offline(
            json.loads(a.read_text(encoding="utf-8")),
            json.loads(b.read_text(encoding="utf-8")))
        content = json.dumps(
            report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if len(content.encode("utf-8")) > MAX_REPORT_BYTES:
            raise ValueError("Private overlay provenance report oversized")
        with target.open("x", encoding="utf-8") as fp:
            fp.write(content)
        print(json.dumps({
            "status": "TWSE_2022_AES_NEON_FIVE_YEAR_SOURCE_DAY_OVERLAY_OFFLINE_PASS",
            "local_aes_days": report["twse_2022_authenticated_local_aes_source_days"],
            "neon_official_bulk_days": report["twse_2022_verified_neon_official_bulk_source_days"],
            "deduplicated_known_source_days": report[
                "twse_2022_deduplicated_observed_source_calendar_dates"],
            "unverified_full_market_listing_or_actions": True,
            "neon_writes": 0,
            "line_messages_sent": 0,
            "model_release": "BLOCKED",
        }, ensure_ascii=False))
    except Exception:
        raise SystemExit(
            "2022 owner AES/Neon five-year source overlay evidence FAILED; "
            "never writes Neon, sends LINE, or prints credentials"
        ) from None


if __name__ == "__main__":
    main()
