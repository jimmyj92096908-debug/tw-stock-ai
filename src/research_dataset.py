"""Conservative, reproducible *historical* research dataset assembly.

The input is the existing as-of-day composite joined to adjusted future prices.
It is not a complete listed/delisted universe, and historical adjusted closes
can change after corporate actions. Missing labels exclude the whole signal
date cohort, never only the losing or unavailable ticker.
"""
from __future__ import annotations

from collections import defaultdict, Counter
from datetime import date, datetime
from hashlib import sha256
import json
import math
import re

FACTOR_FIELDS = (
    "total_score", "technical_score", "smc_score",
    "short_term_score", "swing_score", "long_term_score",
)
REQUIRED_FIELDS = ("market", "stock_id", "as_of_date", "total_score",
                   "coverage_weight", "adjusted_close", "entry_date",
                   "entry_close", "exit_date", "exit_close")
RESEARCH_ONLY = "RETROSPECTIVE_SCORED_COHORT_NOT_TRADABLE"


def _date(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Expected YYYY-MM-DD research date")
    return date.fromisoformat(value).isoformat()


def _num(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        n = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return n if math.isfinite(n) else None


def _identity(row):
    if not isinstance(row, dict):
        raise ValueError("Research row must be a JSON object")
    market = row.get("market")
    stock = str(row.get("stock_id", ""))
    if market not in ("twse", "tpex") or not re.fullmatch(r"[0-9]{4,6}", stock) or stock in ("1808", "1589"):
        raise ValueError("Invalid or explicitly excluded stock in dataset")
    return market, stock


def _normalize(row):
    market, stock = _identity(row)
    for field in REQUIRED_FIELDS:
        if field not in row:
            raise ValueError("Missing required research field: " + field)
    day = _date(row["as_of_date"])
    factor_values = {}
    for factor in FACTOR_FIELDS:
        v = _num(row.get(factor))
        if factor == "total_score" and (v is None or not 0 <= v <= 100):
            raise ValueError("Missing or invalid original factor score")
        if v is not None and not 0 <= v <= 100:
            raise ValueError("Invalid factor range: " + factor)
        factor_values[factor] = v
    coverage = _num(row.get("coverage_weight"))
    if coverage is None or not 0.5 <= coverage <= 1:
        raise ValueError("Factor coverage is below publishability threshold")
    normalized = {"market": market, "stock_id": stock, "as_of_date": day,
                  **factor_values, "coverage_weight": coverage}
    for name in ("adjusted_close", "entry_close", "exit_close"):
        normalized[name] = _num(row[name])
    for name in ("entry_date", "exit_date"):
        normalized[name] = _date(row[name]) if row[name] is not None else None
    return normalized


def _fingerprint(rows):
    serialized = json.dumps(rows, sort_keys=True, ensure_ascii=True,
                            separators=(",", ":"), allow_nan=False)
    return sha256(serialized.encode("utf-8")).hexdigest()


def build_research_dataset(rows, *, start, end, label_cutoff,
                           min_universe=5, max_rows=40000,
                           source_mode="offline_user_supplied_unverified"):
    """Filter whole date cohorts only; emit tamper-evident (not signed) output.

    Label cutoff is the last *actual known* historical session allowed for
    forward exits, not the latest factor date. No missing label is invented.
    """
    start, end, cutoff = _date(start), _date(end), _date(label_cutoff)
    if not start <= end <= cutoff:
        raise ValueError("Require start <= end <= known label cutoff")
    if (date.fromisoformat(end) - date.fromisoformat(start)).days > 366:
        raise ValueError("Research window is limited to 366 calendar days")
    if type(min_universe) is not int or min_universe < 5 or min_universe > 100:
        raise ValueError("min_universe out of range")
    if type(max_rows) is not int or not 1 <= max_rows <= 40000:
        raise ValueError("max_rows out of range")
    if not isinstance(rows, list) or len(rows) > max_rows:
        raise ValueError("Input is not a bounded research rows list")
    groups = defaultdict(list)
    seen = set()
    for raw in rows:
        row = _normalize(raw)
        day = row["as_of_date"]
        if not start <= day <= end:
            raise ValueError("Input row outside explicitly bounded signal window")
        ident = (day, row["market"], row["stock_id"])
        if ident in seen:
            raise ValueError("Duplicate historical score primary key")
        seen.add(ident)
        groups[day].append(row)
    accepted = []
    excluded = Counter()
    for day, cohort in sorted(groups.items()):
        if len(cohort) < min_universe:
            excluded["insufficient_scored_universe"] += 1
            continue
        def valid_label(row):
            p0, p1, p2 = (row[k] for k in ("adjusted_close","entry_close","exit_close"))
            entry, exit_ = row["entry_date"], row["exit_date"]
            return (p0 is not None and p0 > 0 and
                    p1 is not None and p1 > 0 and p2 is not None and p2 > 0 and
                    entry is not None and exit_ is not None and
                    day < entry < exit_ <= cutoff)
        if not all(valid_label(item) for item in cohort):
            excluded["incomplete_or_unmatured_forward_labels"] += 1
            continue
        # A single common holding window is required for fair cross-sectional
        # factor effectiveness. Suspensions create incomparable horizons.
        if len({row["entry_date"] for row in cohort}) != 1 or len(
                {row["exit_date"] for row in cohort}) != 1:
            excluded["unmatched_holding_windows"] += 1
            continue
        accepted.extend(sorted(cohort, key=lambda r:(r["market"],r["stock_id"])))
    output = {
        "schema_version": 1,
        "rows": accepted,
        "manifest": {
            "research_status": RESEARCH_ONLY,
            "source_mode": source_mode,
            "window_start": start,
            "window_end": end,
            "label_cutoff": cutoff,
            "raw_scored_rows": len(rows),
            "raw_scored_dates": len(groups),
            "included_rows": len(accepted),
            "included_dates": len({row["as_of_date"] for row in accepted}),
            "excluded_dates_by_reason": dict(sorted(excluded.items())),
            "source_population": "historically_scored_stocks_only_not_full_exchange_universe",
            "sample_selection_and_survivorship_bias_audited": False,
            "adjusted_price_corporate_action_vintage_verified": False,
            "pristine_future_holdout_proven": False,
            "read_only": True,
            "orders_enabled": False,
            "line_signals_enabled": False,
            "rows_sha256": _fingerprint(accepted),
        },
    }
    return output


def verify_dataset(dataset):
    if not isinstance(dataset, dict) or not isinstance(dataset.get("manifest"), dict):
        raise ValueError("Dataset requires a research manifest")
    m = dataset["manifest"]
    if m.get("research_status") != RESEARCH_ONLY or m.get("orders_enabled") is not False:
        raise ValueError("Research safeguards missing")
    reproduced = build_research_dataset(
        dataset.get("rows"), start=m["window_start"], end=m["window_end"],
        label_cutoff=m["label_cutoff"], min_universe=5,
        max_rows=40000, source_mode=m.get("source_mode", "unverified"))
    clean = reproduced["rows"]
    if clean != dataset["rows"] or _fingerprint(clean) != m.get("rows_sha256"):
        raise ValueError("Dataset rows changed since manifest checksum")
    if (len(clean) != m.get("included_rows") or
            len({x["as_of_date"] for x in clean}) != m.get("included_dates")):
        raise ValueError("Dataset manifest counts do not match rows")
    return clean
