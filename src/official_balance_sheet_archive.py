"""Official latest GENERAL-INDUSTRY balance sheet first-seen research snapshots.

TWSE and TPEx publish latest-quarter balances, not verified individual issuer
filing times or complete point-in-time historical archives. Research-only.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from hashlib import sha256
import json
import re

from src.official_revenue_archive import aware, decimal_or_none
from src.official_quarterly_income_archive import fiscal_quarter, official_day

SOURCES = {
    "twse": "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_ci",
    "tpex": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap07_O_ci",
}
MAX_ROWS = 2500
ALIASES = {
    "stock": ("公司代號", "SecuritiesCompanyCode", "CompanyCode"),
    "year": ("年度", "Year"),
    "quarter": ("季別", "Season", "Quarter"),
    "table_day": ("出表日期", "DateOfPublication", "TableDate"),
    "assets": ("資產總計", "TotalAssets"),
    "liabilities": ("負債總計", "TotalLiabilities"),
    "equity": ("權益總計", "TotalEquity"),
    "current_assets": ("流動資產", "CurrentAssets"),
    "current_liabilities": ("流動負債", "CurrentLiabilities"),
    "parent_equity": ("歸屬於母公司業主之權益合計", "EquityAttributableToOwnersOfParent"),
}


def field(row, name):
    for key in ALIASES[name]:
        if key in row:
            return row[key]
    return None


def parse_snapshot(market, rows, *, observed_at):
    if market not in SOURCES:
        raise ValueError("Unknown official general-industry balance-sheet market")
    at = aware(observed_at)
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS:
        raise ValueError("Invalid bounded balance-sheet source row count")
    records, seen = [], set()
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("Official source balance-sheet rows must be objects")
        stock = str(field(raw, "stock") or "").strip()
        if not re.fullmatch(r"[0-9]{4,6}", stock):
            continue
        year, quarter, period = fiscal_quarter(field(raw, "year"), field(raw, "quarter"))
        if period > at.date():
            raise ValueError("Official balance-sheet fiscal period is in the future")
        key = (market, stock, period)
        if key in seen:
            raise ValueError("Duplicate issuer-quarter in official balance sheet")
        seen.add(key)
        table = official_day(field(raw, "table_day"), period=period, observed=at.date())
        values = {
            name: decimal_or_none(field(raw, name))
            for name in ("assets", "liabilities", "equity",
                         "current_assets", "current_liabilities", "parent_equity")
        }
        # Do not archive incomplete principal accounting identity as validated
        # book values, nor synthesize 0 for missing financial line items.
        if any(values[k] is None for k in ("assets", "liabilities", "equity")):
            continue
        if values["assets"] <= 0 or values["liabilities"] < 0:
            raise ValueError("Invalid official assets or total liabilities")
        for name in ("current_assets", "current_liabilities"):
            if values[name] is not None and values[name] < 0:
                raise ValueError("Invalid negative current accounting amount")
        gap = abs(values["assets"] - values["liabilities"] - values["equity"])
        tolerance = max(Decimal("5"), abs(values["assets"]) * Decimal("0.0001"))
        identity_matches = gap <= tolerance
        # Preserve an actual official mismatch, but make it explicitly
        # UNQUALIFIED for future leverage/ROE calculations.
        material = {
            "market": market, "stock_id": stock,
            "fiscal_year": year, "fiscal_quarter": quarter,
            "period_end": period.isoformat(),
            "official_table_date": table.isoformat() if table else None,
            "assets_thousands_ntd": str(values["assets"]),
            "liabilities_thousands_ntd": str(values["liabilities"]),
            "equity_thousands_ntd": str(values["equity"]),
            "current_assets_thousands_ntd": str(values["current_assets"])
                if values["current_assets"] is not None else None,
            "current_liabilities_thousands_ntd": str(values["current_liabilities"])
                if values["current_liabilities"] is not None else None,
            "parent_equity_thousands_ntd": str(values["parent_equity"])
                if values["parent_equity"] is not None else None,
            "accounting_identity_verified": identity_matches,
        }
        digest = sha256(json.dumps(material, ensure_ascii=False,
                                  sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        records.append({
            **material, "first_observed_at": at.isoformat(),
            "source_url": SOURCES[market], "payload_sha256": digest,
        })
    if not records:
        raise ValueError("No complete real issuer balance sheet in official response")
    return records


def asof_balance(records, *, market, stock_id, signal_cutoff):
    cutoff = aware(signal_cutoff)
    if (cutoff.hour, cutoff.minute, cutoff.second, cutoff.microsecond) != (13, 30, 0, 0):
        raise ValueError("Only actual Taiwan 13:30 signal cutoff accepted")
    if market not in SOURCES or not re.fullmatch(r"[0-9]{4,6}", str(stock_id)):
        raise ValueError("Invalid known market or company")
    if not isinstance(records, list) or len(records) > 100:
        raise ValueError("Bounded saved balance observation history required")
    known = []
    for record in records:
        if record.get("market") != market or record.get("stock_id") != stock_id:
            continue
        captured = aware(record["first_observed_at"])
        period = date.fromisoformat(record["period_end"])
        if period > captured.date():
            raise ValueError("Stored balance sheet's period exceeds its first observation")
        if captured <= cutoff:
            known.append(record)
    latest = max(known, key=lambda v: (
        v["period_end"], aware(v["first_observed_at"]), v["payload_sha256"]
    )) if known else None
    return {
        "market": market, "stock_id": stock_id, "signal_cutoff": cutoff.isoformat(),
        "balance": latest, "covered": latest is not None,
        "safe_for_ratio_research": bool(latest and latest["accounting_identity_verified"]),
        "issuer_published_at_known": False,
        "historical_backdate_prohibited": True,
        "production_model_modified": False, "live_trading_approved": False,
    }
