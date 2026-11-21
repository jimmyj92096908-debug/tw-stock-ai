"""Offline-only retrospective research audit; needs no Neon or LINE secrets."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.research_walkforward import walk_forward_diagnostics  # noqa: E402
from src.research_risk import concentration, market_regime  # noqa: E402


def audit_local(rows, *, first_test_date, fold_signals=3, max_folds=12,
                verified_benchmark_returns=None, index_prices=None,
                as_of_date=None, holdings=None):
    report = walk_forward_diagnostics(
        rows, first_test_date=first_test_date, fold_signals=fold_signals,
        max_folds=max_folds, verified_benchmark_returns=verified_benchmark_returns)
    report["market_regime"] = (
        market_regime(index_prices, as_of_date=as_of_date)
        if index_prices is not None and as_of_date is not None
        else {"regime": "UNAVAILABLE", "reason": "verified_market_index_history_not_supplied"}
    )
    report["portfolio_concentration"] = concentration(holdings or [])
    report["data_mode"] = "offline_user_supplied_historical_evidence"
    report["production_database_modified"] = False
    report["trading_approved"] = False
    return report


def main():
    p = argparse.ArgumentParser(description="Offline walk-forward and risk research diagnostics")
    p.add_argument("--rows", type=Path, required=True,
                   help="Verified research JSON list with forward adjusted labels; not committed secrets")
    p.add_argument("--first-test-date", required=True)
    p.add_argument("--fold-signals", type=int, default=3)
    p.add_argument("--max-folds", type=int, default=12)
    p.add_argument("--benchmark", type=Path,
                   help="Optional user-supplied exact-entry/exit-horizon net benchmark JSON mapping")
    p.add_argument("--index-prices", type=Path,
                   help="Optional sorted official market index JSON rows")
    p.add_argument("--as-of-date")
    p.add_argument("--holdings", type=Path,
                   help="Optional user-supplied, normalized holdings-weight JSON array")
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()

    def load(path):
        return json.loads(path.read_text(encoding="utf-8")) if path else None

    if a.index_prices and not a.as_of_date:
        p.error("--as-of-date required with --index-prices")
    result = audit_local(
        load(a.rows), first_test_date=a.first_test_date,
        fold_signals=a.fold_signals, max_folds=a.max_folds,
        verified_benchmark_returns=load(a.benchmark),
        index_prices=load(a.index_prices), as_of_date=a.as_of_date,
        holdings=load(a.holdings))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2, ensure_ascii=False,
                                    allow_nan=False, default=str)+"\n", encoding="utf-8")
    print(json.dumps({"output": str(a.output), "research_status": result["research_status"],
                      "tested_windows": result["nonoverlapping_risk"]["observations"],
                      "orders_enabled": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
