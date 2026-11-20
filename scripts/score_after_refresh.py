"""Opt-in composite-score job runner; no work unless explicitly executed.

The accompanying workflow is disabled by default and cannot auto-write to the
Neon database without an authorized repository setting change.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from composite_score import calculate_all  # noqa: E402
from tdcc_data import normalize_database_url  # noqa: E402


def rebuild_scores(database_url: str) -> int:
    if not database_url:
        raise ValueError("DATABASE_URL is required")
    url = normalize_database_url(database_url)
    return calculate_all(url)


def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("Missing DATABASE_URL")
    # Deliberately do not print any database URL, credentials or stock-by-stock
    # report rows into GitHub Actions logs.
    total = rebuild_scores(database_url)
    print(f"綜合評分批次完成：處理 {int(total)} 檔候選股票；請另查資料日期是否最新。")


if __name__ == "__main__":
    main()
