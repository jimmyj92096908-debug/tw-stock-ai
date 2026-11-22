"""Owner-only 2022 cash-reduction reference price independent-source audit.

Validate last pre-halt original TWSE close against dated contemporary news
AND the exchange's cash-capital-reduction reference-price equation.
Read owner 2022 AES plus existing Neon source with READ ONLY + rollback.
No adjusted histories, repaired bars, backtests, forecasts or release.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path
import sys

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from scripts.twse_2022_aes_factor_readiness import audit as audit_aes
from scripts.twse_2022_aes_neon_readonly_240_panel import (
    _authenticated_rows, _read_neon_2022_frozen_panel, reconcile,
)
from scripts.twse_2022_corporate_halt_audit import (
    EXPECTED_HALT_SESSIONS, classify,
)
from scripts.twse_2021_22_traded_240_warmup_readonly import (
    _private_archives, _private_file, SOURCE_KEYS,
)
from scripts.twse_archive_key_vault import resolve_archive_key


# In-year evidence, no contemporary website requests or dependence on
# future-adjusted online charts. Source-article dates precede 2022 resumes.
# The published ex-date theoretical reference (not the opening bid tick)
# is NOT an actual post-resumption market trade.
EVENTS = {
    "2327": {
        "last_old_trade": date(2022, 10, 19),
        "first_new_trade": date(2022, 10, 31),
        "cash_refund_payment": date(2022, 11, 3),
        "cash_per_old_share": Decimal("2.0407502943"),
        "new_shares_per_old": Decimal("0.79592497057"),
        "published_old_close": Decimal("268"),
        "published_theoretical_reference": Decimal("334.15"),
        "announcement_date": date(2022, 10, 7),
        "issuer_exchange_announcement_reproduction":
            "https://www.moneydj.com/kmdj/news/newsviewer.aspx?"
            "a=85c1b885-37e6-4918-81a4-5f1919977754",
        "contemporary_reference_report":
            "https://tw.stock.yahoo.com/news/"
            "%E5%9C%8B%E5%B7%A8%E6%9C%88%E5%BA%95%E6%81%A2%E5%BE%A9%E4%BA%A4%E6%98%93",
        "old_close_evidence":
            "https://tw.stock.yahoo.com/news/"
            "%E5%9C%8B%E5%B7%A831%E6%97%A5%E6%81%A2%E5%BE%A9%E4%BA%A4%E6%98%93-"
            "%E5%8F%83%E8%80%83%E5%83%B9334-15%E5%85%83-201000402.html",
    },
    "2603": {
        "last_old_trade": date(2022, 9, 6),
        "first_new_trade": date(2022, 9, 19),
        "cash_refund_payment": date(2022, 9, 29),
        "cash_per_old_share": Decimal("6"),
        "new_shares_per_old": Decimal("0.4"),
        "published_old_close": Decimal("80.8"),
        "published_theoretical_reference": Decimal("187"),
        "announcement_date": date(2022, 8, 24),
        "issuer_exchange_announcement_reproduction":
            "https://www.moneydj.com/kmdj/news/newsviewer.aspx?"
            "a=0b187777-3784-4e7d-aeed-60e3a85b216f",
        "contemporary_reference_report":
            "https://www.cna.com.tw/news/afe/202209190033.aspx",
        "old_close_evidence":
            "https://www.cna.com.tw/news/afe/202209060152.aspx",
    },
}
TWSE_RULE = (
    "https://investoredu.twse.com.tw/pages/TWSE_InvestmentQA.aspx?ID=1"
)


def pure_reference_cash_reduction(old_close: Decimal, cash_per_old: Decimal,
                                  new_shares_per_old: Decimal) -> Decimal:
    """Unrounded theoretical TWSE ex-cash-capital-reduction reference price."""
    values = (old_close, cash_per_old, new_shares_per_old)
    if (any(type(x) is not Decimal or not x.is_finite() for x in values)
            or old_close <= cash_per_old or cash_per_old < 0
            or not Decimal("0") < new_shares_per_old < Decimal("1")):
        raise ValueError("Invalid exact original close / cash / exchange ratio")
    return (old_close - cash_per_old) / new_shares_per_old


def economic_one_old_share_value(new_trade_close: Decimal,
                                 cash_refund: Decimal,
                                 new_shares_per_old: Decimal) -> Decimal:
    """Gross entitlement value, NOT a realizable return before cash payment."""
    if (any(type(x) is not Decimal or not x.is_finite()
            for x in (new_trade_close, cash_refund, new_shares_per_old))
            or new_trade_close <= 0 or cash_refund < 0
            or not 0 < new_shares_per_old < 1):
        raise ValueError("Invalid new share and cash entitlement")
    return new_shares_per_old * new_trade_close + cash_refund


def prove_cash_reduction_references(original, recomputed, market_days, closes):
    """Pure deterministic stock-day witness; store no individual private price."""
    classified = classify(original)
    if (classified["known_cash_reduction_stock_halt_days"] != 14
            or classified["unknown_stock_day_count"] != 0
            or not isinstance(recomputed, dict)
            or any(original.get(k) != recomputed.get(k)
                   for k in SOURCE_KEYS)
            or original["frozen_stocks_with_complete_last_240_source_sessions"] != 18
            or recomputed.get("neon_write_operations") != 0
            or recomputed.get("live_model_release_decision") != "BLOCKED"):
        raise ValueError("Original frozen20 read-only 2022 source proof changed")
    if (not isinstance(market_days, (set, frozenset, list, tuple))
            or len(set(market_days)) != 246
            or any(type(d) is not date or d.year != 2022 for d in market_days)
            or min(market_days).isoformat() != original["first_combined_session"]
            or max(market_days).isoformat() != original["last_combined_session"]
            or not isinstance(closes, dict)):
        raise ValueError("2022 verified date/source calendar changed")
    all_days = set(market_days)
    exact_keys = set()
    forbidden_keys = set()
    for stock, facts in EVENTS.items():
        exact_keys.update({
            (stock, facts["last_old_trade"]),
            (stock, facts["first_new_trade"]),
        })
        forbidden_keys.update(
            (stock, date.fromisoformat(day))
            for day in EXPECTED_HALT_SESSIONS[stock]
        )
    if (set(closes) != exact_keys or forbidden_keys & set(closes)
            or not {day for _, day in exact_keys | forbidden_keys} <= all_days):
        raise ValueError("Original last-trade/resumption/halt stock-day witnesses invalid")

    results = []
    for stock, ev in sorted(EVENTS.items()):
        old = closes[(stock, ev["last_old_trade"])]
        new = closes[(stock, ev["first_new_trade"])]
        if (old != ev["published_old_close"]
                or type(new) is not Decimal or not new.is_finite() or new <= 0
                or ev["announcement_date"] > ev["last_old_trade"]
                or ev["cash_refund_payment"] <= ev["first_new_trade"]
                or ev["new_shares_per_old"] * 10 + ev["cash_per_old_share"]
                   != Decimal("10")):
            raise ValueError("Contemporaneous old close or capital facts conflict")
        theoretical = pure_reference_cash_reduction(
            old, ev["cash_per_old_share"], ev["new_shares_per_old"])
        if abs(theoretical - ev["published_theoretical_reference"]) >= Decimal(".01"):
            raise ValueError("Historical TWSE published reference price parity failed")
        # The correct cash-plus-new-shares event portfolio identity is also
        # checked, but NOT exported or labeled as a tradable/reinvested return.
        gross = economic_one_old_share_value(
            new, ev["cash_per_old_share"], ev["new_shares_per_old"])
        if gross <= 0:
            raise ValueError("Invalid event portfolio economic value")
        results.append({
            "stock_id": stock,
            "last_original_stock_trade": ev["last_old_trade"].isoformat(),
            "first_resumed_stock_trade": ev["first_new_trade"].isoformat(),
            "known_halt_market_days_without_synthetic_bars":
                len(EXPECTED_HALT_SESSIONS[stock]),
            "authenticated_old_close_equals_preexisting_2022_report": True,
            "cash_reduction_exchange_ratio_independent_source_parity": True,
            "theoretical_exchange_reference_price_parity_within_0_01": True,
            "post_resume_trade_close_authenticated_but_not_disclosed": True,
            "gross_cash_plus_new_shares_identity_checked": True,
            "refund_cash_payment_date": ev["cash_refund_payment"].isoformat(),
            "issuer_exchange_announcement_reproduction":
                ev["issuer_exchange_announcement_reproduction"],
            "contemporary_old_close_evidence": ev["old_close_evidence"],
            "contemporary_reference_report": ev["contemporary_reference_report"],
            "twse_reference_price_method": TWSE_RULE,
            "sma240_from_corporate_action_adjusted_ohlc_completed": False,
            "cash_payment_proven_received_at_resumption": False,
            "complete_total_return_and_cost_model_verified": False,
        })
    return {
        "scope": "OWNER_ONLY_2022_TWSE_CASH_REDUCTION_OFFICIAL_REFERENCE_PARITY",
        "stocks_with_2022_actual_source_and_historical_reference_parity": len(results),
        "frozen20_market_day_sma240_complete_unchanged": 18,
        "traded_240_warmup_current_stocks_unchanged": 2,
        "halt_market_days_not_rewritten_as_trades": 14,
        "stock_action_research_witnesses": results,
        "no_observation_time_future_leakage_claim": True,
        "actual_price_or_cash_entitlement_emitted": False,
        "adjusted_daily_ma240_computed": False,
        "stock_buy_sell_execution_or_cash_settlement_verified": False,
        "historical_pit_stock_universe_verified": False,
        "model_walkforward_release_verified": False,
        "neon_writes": 0,
        "line_messages_sent": 0,
        "paid_upgrade_requested": False,
        "live_model_release_decision": "BLOCKED",
    }


def run_local(*, archive_dir, vault, source_report, output):
    files = _private_archives(archive_dir)
    source = _private_file(source_report, should_exist=True)
    dest = _private_file(output, should_exist=False)
    original = json.loads(source.read_text(encoding="utf-8"))
    classified = classify(original)
    if (classified["known_cash_reduction_stock_halt_days"] != 14
            or classified["unknown_stock_day_count"] != 0):
        raise ValueError("2022 preflight did not confirm 14 known stock halts")
    hex_key = resolve_archive_key(
        vault_path=Path(vault),
        env_key=os.environ.get("STOCK_ARCHIVE_KEY_HEX", ""),
    )
    local_proof = audit_aes(files, hex_key=hex_key, spotchecks=0)
    stream, digest = _authenticated_rows(
        files, hex_key=hex_key,
        expected_bundle_digest=local_proof["authenticated_file_digest_bundle_sha256"])
    witness = {}
    calendar = set()
    event_windows = {
        sid: (ev["last_old_trade"], ev["first_new_trade"])
        for sid, ev in EVENTS.items()
    }

    def track(row):
        sid = row["stock_id"]
        d = row["trade_date"]
        if sid in event_windows:
            start, end = event_windows[sid]
            if start <= d <= end:
                key = (sid, d)
                if key in witness and witness[key] != row["close"]:
                    raise ValueError("Different archive close for same event stock-day")
                witness[key] = row["close"]

    def replay():
        for row in stream:
            calendar.add(row["trade_date"])
            track(row)
            yield row

    neon_days, neon_rows = _read_neon_2022_frozen_panel()
    updated = reconcile(replay(), neon_rows, neon_days,
                        local_audit=local_proof)
    if (sha256(json.dumps(digest, separators=(",", ":")).encode())
            .hexdigest() != local_proof["authenticated_file_digest_bundle_sha256"]):
        raise ValueError("Private AES archive digest changed between verified passes")
    calendar.update(neon_days)
    for row in neon_rows:
        track(row)  # entire row was already validated by reconcile()
    proof = prove_cash_reduction_references(original, updated, calendar, witness)
    with dest.open("x", encoding="utf-8") as f:
        json.dump(proof, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")
    print(json.dumps({
        "status": "2022_CASH_REDUCTION_REFERENCE_AUDIT_PASS",
        "stock_reference_parity_count":
            proof["stocks_with_2022_actual_source_and_historical_reference_parity"],
        "halt_stock_days_preserved":
            proof["halt_market_days_not_rewritten_as_trades"],
        "corporate_action_adjusted_sma240": False,
        "neon_writes": 0,
        "line_messages_sent": 0,
        "model_release": "BLOCKED",
    }, ensure_ascii=False))


def main():
    cli = argparse.ArgumentParser(
        description="Owner-only 2022 cash reduction TWSE reference-price source audit")
    cli.add_argument("--archive-2022", required=True)
    cli.add_argument("--key-vault", required=True)
    cli.add_argument("--source-report", required=True)
    cli.add_argument("--out", required=True)
    args = cli.parse_args()
    try:
        run_local(
            archive_dir=args.archive_2022,
            vault=args.key_vault,
            source_report=args.source_report,
            output=args.out,
        )
    except Exception:
        raise SystemExit(
            "Private historical cash reduction reference parity FAILED; "
            "no production writes, LINE notifications or secrets printed"
        ) from None


if __name__ == "__main__":
    main()
