"""Historical receipt arithmetic only; no Neon, decrypted prices, or network.

This reconciles the fixed 2026-11-23 historical owner receipts. Equal roster
counts are not evidence that roster identifiers or snapshot vintages match.
The output is a conditional aggregate, never an updated per-stock panel.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

N = 1092
YEARS = tuple(range(2021, 2027))
WINDOW = ("2021-11-23", "2026-11-23")
S21 = "OWNER_2021_TWSE_AES_NEON_CURRENT_LISTED_28DAY_STOCK_DATE_UNION_READONLY"
S21_ALTERNATE = "OWNER_TWSE_2021_28DAY_AES_NEON_CURRENT_COHORT_STOCK_DATE_UNION"
S22 = "OWNER_2022_TWSE_AES_NEON_CURRENT_OFFICIAL_STOCK_DATE_DENSITY_RESEARCH"
S5 = "OWNER_TWSE_TPEX_NEON_ONLY_5Y_OFFICIAL_CURRENT_LISTED_SOURCE_DEPTH"
LIMIT = 100_000
ABSENCE = ("before_first", "after_last", "inside_first_last", "no_2022_record")
GROUPS = ("all_observed_source_days", "no_observed_source_day",
          "absence_only_before_first_observed_day", "absence_only_after_last_observed_day",
          "absence_at_both_outer_boundaries_only", "internal_absent_days_only",
          "internal_and_outer_absent_days")


def require(ok):
    if not ok:
        raise ValueError("Inconsistent or unsupported historical source receipt")


def integer(value, lo=0, hi=10_000_000):
    require(type(value) is int and lo <= value <= hi)
    return value


def same_int(report, key, expected):
    require(integer(report.get(key)) == expected)


def receipt(r, scope):
    require(isinstance(r, dict) and r.get("scope") == scope)
    same_int(r, "schema_version", 1)
    same_int(r, "production_neon_writes", 0)
    same_int(r, "line_messages_sent", 0)
    require(r.get("model_release") == "BLOCKED")


def normalize_2021(report):
    """Accept either existing producer's exact schema, not mixed field aliases."""
    require(isinstance(report, dict))
    if report.get("scope") == S21:
        receipt(report, S21)
        return report
    receipt(report, S21_ALTERNATE)
    require(report.get("previous_pr241_receipt_fully_reauthenticated") is True)
    require(report.get("2021_current_cohort_aes_neon_deduplicated_stock_day_union_verified") is True)
    require(report.get("source_key_union_not_price_or_volume_economic_parity") is True)
    require(report.get("historic_asof_listed_universe_and_ipo_eligibility_not_proven") is True)
    require(report.get("full_five_year_and_corporate_action_total_return_not_verified") is True)
    require(report.get("historical_point_in_time_universe_verified", False) is False)
    same_int(report, "valid_neon_2021_source_days", 28)
    mapping = {
        "five_year_baseline_window_start": "study_rolling_five_year_start_inclusive",
        "five_year_baseline_window_end_exclusive": "study_rolling_five_year_end_exclusive",
        "official_current_survivor_tickers_excluding_1589": "official_current_twse_survivor_eligible_count",
        "authenticated_owner_2021_source_dates": "authenticated_2021_aes_source_days",
        "prior_2021_aes_source_stock_date_pairs": "aes_current_stock_source_date_pairs",
        "prior_2021_neon_source_stock_date_pairs": "neon_current_stock_source_date_pairs",
        "aes_neon_overlapping_source_stock_date_pairs": "duplicated_aes_neon_current_stock_date_pairs",
        "aes_exclusive_source_stock_date_pairs": None,
        "neon_exclusive_source_stock_date_pairs": "new_neon_current_stock_date_pairs_outside_aes",
        "actual_deduplicated_aes_neon_stock_date_pairs": "unique_aes_plus_neon_2021_stock_date_pairs",
        "current_stock_source_day_count_histogram": "owner_private_union_stock_2021_observed_source_day_histogram",
    }
    # Neither producer may be accepted by supplying a mixture of both schemas.
    require(not any(k in report for k in mapping))
    normalized = {k: report.get(v) for k,v in mapping.items() if v is not None}
    normalized["aes_exclusive_source_stock_date_pairs"] = (
        integer(normalized["prior_2021_aes_source_stock_date_pairs"])
        - integer(normalized["aes_neon_overlapping_source_stock_date_pairs"]))
    normalized["current_issuer_2026_roster_is_not_historical_2021_pit_roster"] = True
    return normalized


def reconcile(a, b, c):
    a = normalize_2021(a)
    receipt(b, S22)
    receipt(c, S5)
    require((a.get("five_year_baseline_window_start"),
             a.get("five_year_baseline_window_end_exclusive")) == WINDOW)
    require((c.get("window_start_inclusive"), c.get("window_end_exclusive")) == WINDOW)
    require(a.get("current_issuer_2026_roster_is_not_historical_2021_pit_roster") is True)
    require(c.get("current_listed_issuers_only_not_historical_pit_membership") is True)
    require(c.get("excludes_owner_private_aes_and_non_neon_source_history") is True)
    require(c.get("five_year_history_completed") is False)
    require(b.get("full_market_all_stock_daily_bar_completeness_certified") is False)
    require(b.get("source_day_presence_and_240_count_not_adjusted_total_return_or_historical_pit") is True)
    for key, value in {
        "official_current_survivor_tickers_excluding_1589": N,
        "authenticated_owner_2021_source_dates": 28,
        "prior_2021_aes_source_stock_date_pairs": 26120,
        "prior_2021_neon_source_stock_date_pairs": 552,
        "aes_neon_overlapping_source_stock_date_pairs": 552,
        "aes_exclusive_source_stock_date_pairs": 25568,
        "neon_exclusive_source_stock_date_pairs": 0,
        "actual_deduplicated_aes_neon_stock_date_pairs": 26120,
    }.items():
        same_int(a, key, value)
    hist = a["current_stock_source_day_count_histogram"]
    require(isinstance(hist, dict) and all(k in {str(i) for i in range(29)} for k in hist))
    require(sum(integer(v, hi=N) for v in hist.values()) == N)
    require(sum(int(k)*v for k,v in hist.items()) == 26120)
    for key, value in {
        "year": 2022,
        "official_current_listed_eligible_twse_issuers": N,
        "aes_prior_2022_source_calendar_dates": 162,
        "neon_original_bulk_source_calendar_dates": 84,
        "aes_source_days_overlap_neon_bulk_source_days": 0,
        "aes_plus_neon_unique_observed_source_dates": 246,
        "neon_rechecked_stock_date_source_rows": 83294,
        "aes_neon_current_listed_stocks_with_all_246_source_dates": 825,
        "aes_neon_current_listed_stocks_with_at_least_240_of_246_source_dates": 890,
    }.items():
        same_int(b, key, value)
    s = b["current_listed_source_date_observation_absence_signatures"]
    groups = s["observation_signature_stock_count"]
    require(set(groups) == set(GROUPS))
    require([integer(groups[k], hi=N) for k in GROUPS] ==
            [825, 129, 20, 2, 0, 104, 12])
    same_int(s, "eligible_stocks_not_observed_on_all_source_days", 267)
    same_int(s, "currently_eligible_stocks_observed_240_to_245_source_days", 65)
    same_int(s, "currently_eligible_stocks_observed_fewer_than_240_source_days", 202)
    missing = sum(integer(s["nominal_absent_stock_source_date_pairs_" + k],
                          hi=N*246) for k in ABSENCE)
    same_int(s, "nominal_absent_stock_source_date_pairs_total", missing)
    same_int(s, "nominal_absent_stock_source_date_pairs_no_2022_record", 129*246)
    merged22 = N*246 - missing
    # Independent bounds implied by per-stock depth groups; absence is not a
    # verified trading obligation. 129 entirely absent issuers contribute zero.
    lower = 825*246 + 65*240 + 73
    upper = 825*246 + 65*245 + 73*239
    require(lower <= merged22 <= upper)

    markets = c["market"]
    require(set(markets) == {"twse", "tpex"})
    annual = {}
    for market, pop in (("twse", N), ("tpex", 898)):
        m = markets[market]
        same_int(m, "official_current_listed_stocks_excluding_1589", pop)
        seq = m["yearly_neon_source_observations"]
        require(isinstance(seq, list) and len(seq) == 6)
        rows = {}
        for row in seq:
            year = integer(row["year"], 2021, 2026)
            require(year not in rows)
            days = integer(row["days_with_any_neon_eligible_source_bars"], hi=366)
            dense = integer(row["days_with_at_least_500_eligible_source_bars"], hi=days)
            pairs = integer(row["neon_stored_valid_source_stock_bars"],
                            lo=max(days, dense*500+days-dense), hi=days*pop)
            rows[year] = (days, dense, pairs)
        require(set(rows) == set(YEARS))
        annual[market] = rows
    tw = annual["twse"]
    require(tw[2021] == (28, 0, 552))
    require(tw[2022] == (246, 84, 83294))
    neon = sum(v[2] for v in tw.values())
    # Replacement, never sum the AES union on top of the same Neon year.
    hypothetical = neon - tw[2021][2] - tw[2022][2] + 26120 + merged22
    require(hypothetical >= neon)
    return {
        "schema_version": 1,
        "scope": "OWNER_FIXED_20261123_CONDITIONAL_CROSS_YEAR_RECEIPT_ARITHMETIC",
        "historical_window_start": WINDOW[0],
        "historical_window_end_exclusive": WINDOW[1],
        "twse_2021_union_observed_keys": 26120,
        "twse_2022_union_observed_keys_from_absence_conservation": merged22,
        "twse_2021_2022_observed_keys_sum": 26120 + merged22,
        "twse_neon_only_baseline_stock_date_keys": neon,
        "conditional_twse_baseline_replacement_keys": hypothetical,
        "conditional_increment_over_neon_only_baseline": hypothetical-neon,
        "same_roster_identifiers_and_snapshot_vintage_verified": False,
        "conditional_replacement_is_not_verified_five_year_union": True,
        "five_year_per_stock_depth_recomputed": False,
        "five_year_history_complete": False,
        "historical_pit_total_return_verified": False,
        "production_neon_writes": 0,
        "line_messages_sent": 0,
        "paid_upgrade_requested": False,
        "model_release": "BLOCKED",
    }


def private_path(raw):
    p = Path(raw).expanduser().resolve()
    require(not any((q/".git").exists() for q in (p.parent, *p.parents)))
    return p


def load(p):
    require(p.is_file())
    with p.open("rb") as f:
        raw = f.read(LIMIT+1)
    require(len(raw) <= LIMIT)
    def unique_pairs(pairs):
        obj = {}
        for k, v in pairs:
            require(k not in obj)
            obj[k] = v
        return obj
    return json.loads(raw, object_pairs_hook=unique_pairs), hashlib.sha256(raw).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("union-2021", "density-2022", "neon-five-year", "out"):
        p.add_argument("--"+name, required=True)
    args = p.parse_args()
    try:
        paths = [private_path(getattr(args, x)) for x in
                 ("union_2021", "density_2022", "neon_five_year", "out")]
        require(len(set(paths)) == 4 and not paths[3].exists())
        sources = [load(x) for x in paths[:3]]
        report = reconcile(*(x[0] for x in sources))
        report["input_receipt_sha256"] = dict(zip(("union_2021","density_2022","neon_five_year"),
                                                 (x[1] for x in sources)))
        with paths[3].open("x", encoding="utf-8") as f:
            json.dump(report, f, indent=2, allow_nan=False)
            f.write("\n")
        print(json.dumps({"status": "CONDITIONAL_RECEIPT_ARITHMETIC_PASS",
                          "conditional_increment": report["conditional_increment_over_neon_only_baseline"],
                          "model_release": "BLOCKED"}))
    except Exception:
        raise SystemExit("Private receipt reconciliation failed; no Neon or LINE action") from None


if __name__ == "__main__":
    main()
