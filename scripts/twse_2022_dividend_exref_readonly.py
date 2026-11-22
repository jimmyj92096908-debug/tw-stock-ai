"""2022 2327/2603 dated cash dividend ex-reference parity, owner-local READ ONLY.

Reverify owner-private official TWSE 2022 AES and unchanged READ ONLY Neon
frozen20 panel. Require prior #225 known dividends absent from corporate_actions.
Compare four real pre/ex-date stock bars to historical dated issuer/TAIFEX
cash announcement and retrospective exchange ex-reference. Never repair
corporate_actions, persist prices, compute investable adjusted total return,
or authorize a model release.

This bounded event witness DOES NOT assert a complete corporate-action
universe, original archive capture timestamp, or time-correct backtest.
"""
from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from scripts.twse_2022_aes_factor_readiness import audit as audit_2022
from scripts.twse_2022_aes_neon_readonly_240_panel import (
    _authenticated_rows, _read_neon_2022_frozen_panel, reconcile,
)
from scripts.twse_2022_corporate_halt_audit import classify as classify_halts
from scripts.twse_2021_22_traded_240_warmup_readonly import (
    SOURCE_KEYS, _private_archives, _private_file,
)
from scripts.twse_2022_known_dividend_gap_offline import (
    SCOPE as GAP_SCOPE, classify_historical_dividend_gaps,
)
from scripts.twse_archive_key_vault import resolve_archive_key

SCOPE = "OWNER_2022_TWSE_TWO_STOCK_DATED_EX_DIVIDEND_REFERENCE_RESEARCH_ONLY"

# 2327: 2022-06-24 official TAIFEX notice specifically states Yageo's
# 2022-06-17 dividend declaration is exactly 10.10281345/share.
# 2603: 2022-05-31 issuer's MOPS announcement reproduced verbatim
# (including 17.99999637, ex-date and scheduled cash payment).
# Published ex-reference quotes are display-rounded; compare to
# mathematical no-rounding value within <0.01, NOT exact equality.
EVENTS = {
    "2327": {
        "pre_ex_trade": date(2022, 7, 1),
        "ex_trade": date(2022, 7, 4),
        "issuer_announcement_date": date(2022, 6, 17),
        "payout_scheduled": date(2022, 7, 22),
        "declared_cash_per_old_share": Decimal("10.10281345"),
        "independently_reported_pre_ex_close": Decimal("282"),
        "independently_reported_ex_reference": Decimal("271.89"),
        "issuer_amount_evidence": "https://www.taifex.com.tw/file/taifex/CHINESE/11/attach/2327_20220704.pdf",
        "prior_close_evidence": "https://tw.stock.yahoo.com/news/%E6%95%B4%E5%90%88%E5%9F%BA%E7%BE%8E%E6%95%88%E6%87%89%E7%BA%8C%E7%99%BC%E5%A8%81-%E5%9C%8B%E5%B7%A8-q2%E5%8F%AF%E6%9C%9B%E8%B3%BA%E9%80%BE-%E5%80%8B%E8%82%A1%E6%9C%AC-201000158.html",
        "reference_evidence": "https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=13b96ec7-a471-46d2-8dcd-485c49d09a78",
    },
    "2603": {
        "pre_ex_trade": date(2022, 6, 28),
        "ex_trade": date(2022, 6, 29),
        "issuer_announcement_date": date(2022, 5, 31),
        "payout_scheduled": date(2022, 7, 28),
        "declared_cash_per_old_share": Decimal("17.99999637"),
        "independently_reported_pre_ex_close": Decimal("108.5"),
        "independently_reported_ex_reference": Decimal("90.50"),
        "issuer_amount_evidence": "https://news.cnyes.com/news/id/4882348",
        "prior_close_evidence": "https://www.findprice.com.tw/f/2603/dividend",
        "reference_evidence": "https://superpy.kgieworld.com.tw/kgipythonapi/stockInfo/finance/exDividend?stockCode=2603",
    },
}


def verify_precise_cash_reference(original, current, gap, market_days, close_witness):
    """Offline deterministic Decimal gate; private source prices never output."""
    classified = classify_halts(original)
    if (classified["known_cash_reduction_stock_halt_days"] != 14
            or classified["unknown_stock_day_count"] != 0
            or not isinstance(current, dict)
            or any(original.get(k) != current.get(k) for k in SOURCE_KEYS)
            or current.get("live_model_release_decision") != "BLOCKED"
            or current.get("neon_write_operations") != 0):
        raise ValueError("Existing 2022 AES/Neon frozen panel has drifted")
    if (not isinstance(gap, dict)
            or gap.get("schema_version") != 1
            or gap.get("scope") != GAP_SCOPE
            or gap.get("live_model_release_decision") != "BLOCKED"
            or gap.get("production_neon_writes") != 0
            or gap.get("line_messages_sent") != 0
            or gap.get("independently_dated_2022_cash_dividend_events") != 2
            or gap.get("events_confirmed_missing_from_prior_neon_cash_dividend_inventory") != 2
            or gap.get("fully_adjusted_sma240_or_true_total_return_approved") is not False):
        raise ValueError("Previous dated dividend gap evidence not accepted")
    rows = gap.get("per_stock_known_dividend_event_gaps")
    if not isinstance(rows, list) or len(rows) != len(EVENTS):
        raise ValueError("Only exact two known dated cash dividend gaps accepted")
    seen = set()
    for entry in rows:
        if not isinstance(entry, dict):
            raise ValueError("Malformed previous event gap witness")
        sid = entry.get("stock_id")
        if (sid not in EVENTS or sid in seen
                or entry.get("known_historical_cash_dividend_ex_date")
                   != EVENTS[sid]["ex_trade"].isoformat()
                or entry.get("prior_neon_stored_cash_dividend_rows_in_entire_window") != 0
                or entry.get("dated_event_vs_prior_neon_status")
                   != "CONFIRMED_MISSING_FROM_PRIOR_STORED_CASH_DIVIDEND_INVENTORY"
                or entry.get("precise_per_share_cash_amount_certified") is not False
                or entry.get("historical_dividend_event_insert_permitted") is not False):
            raise ValueError("Unverified previously missing cash dividend event")
        seen.add(sid)
    if seen != set(EVENTS):
        raise ValueError("Incomplete 2022 cash-dividend gap evidence")
    if (not isinstance(market_days, (set, list, tuple, frozenset))
            or len(set(market_days)) != 246
            or any(type(d) is not date or d.year != 2022 for d in market_days)
            or min(market_days).isoformat() != original["first_combined_session"]
            or max(market_days).isoformat() != original["last_combined_session"]
            or not isinstance(close_witness, dict)):
        raise ValueError("Observed 2022 source market calendar changed")

    market = set(market_days)
    expected_keys = {
        (sid, d)
        for sid, fact in EVENTS.items()
        for d in (fact["pre_ex_trade"], fact["ex_trade"])
    }
    if set(close_witness) != expected_keys:
        raise ValueError("Missing/phantom ex-dividend stock-day witness")
    for sid, fact in EVENTS.items():
        pre, ex = fact["pre_ex_trade"], fact["ex_trade"]
        if (pre not in market or ex not in market
                or max(d for d in market if d < ex) != pre
                or not fact["issuer_announcement_date"] < ex
                or not fact["issuer_announcement_date"] <= pre
                or not ex < fact["payout_scheduled"] <= max(market)):
            raise ValueError("As-of source announcement or calendar date boundary invalid")

    output = []
    for sid, fact in sorted(EVENTS.items()):
        pre, ex = fact["pre_ex_trade"], fact["ex_trade"]
        cash = fact["declared_cash_per_old_share"]
        old, new = close_witness[(sid, pre)], close_witness[(sid, ex)]
        if (type(old) is not Decimal or type(new) is not Decimal
                or not old.is_finite() or not new.is_finite()
                or old <= cash or new <= 0
                or cash <= 0 or not cash.is_finite()
                or old != fact["independently_reported_pre_ex_close"]):
            raise ValueError("Real pre-ex stock close conflicts with historical source")
        math_reference = old - cash
        display_reference = fact["independently_reported_ex_reference"]
        if (type(display_reference) is not Decimal
                or not display_reference.is_finite()
                or abs(math_reference - display_reference) >= Decimal(".01")):
            raise ValueError("Declared cash vs historically reported ex-reference mismatch")
        # We explicitly DO NOT misrepresent economic dividend entitlement:
        # the cash is scheduled for a later date, not available on ex-date.
        output.append({
            "stock_id": sid,
            "prior_stock_trade": pre.isoformat(),
            "cash_ex_dividend_date": ex.isoformat(),
            "issuer_declaration_date": fact["issuer_announcement_date"].isoformat(),
            "dividend_scheduled_payment_date": fact["payout_scheduled"].isoformat(),
            "contemporaneous_declared_cash_per_share_ntd": str(cash),
            "declared_cash_source": fact["issuer_amount_evidence"],
            "prior_close_crosscheck_source": fact["prior_close_evidence"],
            "display_ex_reference_crosscheck_source": fact["reference_evidence"],
            "actual_authenticated_source_pre_ex_close_matches_evidence": True,
            "true_source_ex_date_trade_close_exists": True,
            "ex_reference_formula_parity_within_0_01_ntd": True,
            "asof_after_issuer_declaration_before_event_verified_from_date": True,
            "cash_available_on_ex_dividend_day": False,
            "all_2021_22_dividends_and_corporate_actions_complete": False,
            "confirmed_verified_cash_dividend_event_inserted_to_neon": False,
            "total_return_or_adjusted_sma240_recomputed": False,
        })
    return {
        "schema_version": 1,
        "scope": SCOPE,
        "source_2022_verified_observed_market_days": len(market),
        "dated_two_dividend_event_reference_parity_count": len(output),
        "dated_two_dividend_event_research_witnesses": output,
        "prior_known_two_dividends_absent_from_neon": True,
        "full_historical_company_action_universe_proven": False,
        "original_pit_issuer_membership_and_capture_vintage_proven": False,
        "asof_before_issuer_declaration_rebuilt": False,
        "final_dividend_cash_payment_execution_or_reinvestment_proven": False,
        "fully_adjusted_sma240_or_total_return_label_approved": False,
        "source_bars_or_prices_rewritten": False,
        "production_neon_writes": 0,
        "line_messages_sent": 0,
        "paid_services_requested": False,
        "live_model_release_decision": "BLOCKED",
    }


def run_local(*, archive_2022, key_vault, original_report, gap_report, output):
    archives = _private_archives(archive_2022)
    path_original = _private_file(original_report, should_exist=True)
    path_gap = _private_file(gap_report, should_exist=True)
    target = _private_file(output, should_exist=False)
    if len({path_original, path_gap, target}) != 3:
        raise ValueError("Owner files must be distinct; never overwrite")
    original = json.loads(path_original.read_text(encoding="utf-8"))
    gaps = json.loads(path_gap.read_text(encoding="utf-8"))
    if (classify_halts(original)["known_cash_reduction_stock_halt_days"] != 14
            or gaps.get("scope") != GAP_SCOPE
            or gaps.get("live_model_release_decision") != "BLOCKED"):
        raise ValueError("Invalid prior owner historical source/gap evidence")
    key = resolve_archive_key(
        vault_path=Path(key_vault),
        env_key=os.environ.get("STOCK_ARCHIVE_KEY_HEX", ""))
    proof = audit_2022(archives, hex_key=key, spotchecks=0)
    local_rows, digests = _authenticated_rows(
        archives, hex_key=key,
        expected_bundle_digest=proof["authenticated_file_digest_bundle_sha256"])
    calendar = set()
    closes = {}
    event_keys = {
        (sid, d) for sid, event in EVENTS.items()
        for d in (event["pre_ex_trade"], event["ex_trade"])
    }

    def record(row):
        stock_day = row["stock_id"], row["trade_date"]
        if stock_day not in event_keys:
            return
        old = closes.get(stock_day)
        if old is not None and old != row["close"]:
            raise ValueError("Conflicting AES vs Neon original stock close")
        closes[stock_day] = row["close"]

    def replay():
        for row in local_rows:
            calendar.add(row["trade_date"])
            record(row)
            yield row

    neon_dates, neon_rows = _read_neon_2022_frozen_panel()
    current = reconcile(replay(), neon_rows, neon_dates, local_audit=proof)
    if sha256(json.dumps(digests, separators=(",", ":")).encode()).hexdigest() != (
            proof["authenticated_file_digest_bundle_sha256"]):
        raise ValueError("AES file digest changed during full-price replay")
    calendar.update(neon_dates)
    for row in neon_rows:
        record(row)  # all Neon bars already validated by reconcile()
    result = verify_precise_cash_reference(original, current, gaps, calendar, closes)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({
        "status": "TWO_STOCK_2022_DECLARED_CASH_EX_REF_READONLY_PASS",
        "verified_cash_ex_reference_events":
            result["dated_two_dividend_event_reference_parity_count"],
        "complete_dividend_history_certified": False,
        "adjusted_total_return_approved": False,
        "neon_writes": 0,
        "line_messages_sent": 0,
        "model_release": "BLOCKED",
    }, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(
        description="2022 2327/2603 dated ex-dividend reference parity READ ONLY")
    parser.add_argument("--archive-2022", required=True)
    parser.add_argument("--key-vault", required=True)
    parser.add_argument("--source-report", required=True)
    parser.add_argument("--gap-report", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        run_local(
            archive_2022=args.archive_2022,
            key_vault=args.key_vault,
            original_report=args.source_report,
            gap_report=args.gap_report,
            output=args.out)
    except Exception:
        raise SystemExit(
            "Private 2022 official dated dividend reference check FAILED; "
            "no corporate action writes, LINE calls or private prices printed"
        ) from None


if __name__ == "__main__":
    main()
