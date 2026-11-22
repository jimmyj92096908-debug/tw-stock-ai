"""Strict synthetic AES archive tests; never use owner data, Neon or LINE."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
import unittest

from scripts.twse_local_encrypted_archive import encrypt_rows
from scripts.twse_2022_aes_factor_readiness import (
    MIN_FACTOR_SESSIONS, _bar_ok, audit,
)

SOURCE = "TWSE_MI_INDEX_ALLBUT0999"


def fake_row(day, stock, i):
    close = Decimal("55.0") + Decimal(i) / 100 + (
        Decimal(int(stock) % 11) / 10
    ) + Decimal((i * 7) % 15) / 20
    return {
        "market": "twse", "stock_id": stock, "trade_date": day,
        "open": close - Decimal("0.10"),
        "high": close + Decimal("0.50"),
        "low": close - Decimal("0.60"),
        "close": close,
        "volume": 100_000 + i * 5,
        "turnover": close * Decimal(100_000 + i * 5),
        "price_change": Decimal("0.01"),
        "transactions": 125,
        "source": SOURCE,
        "retrieved_at": datetime(2026, 11, 22, 1, tzinfo=timezone.utc),
    }


def sessions(n):
    d = date(2022, 1, 3)
    result = []
    while len(result) < n:
        if d.weekday() < 5:
            result.append(d)
        d += timedelta(days=1)
    return result


def create_files(directory, key, count=241):
    days = sessions(count)
    grouped = {}
    for i, day in enumerate(days):
        group = grouped.setdefault((day.year, day.month), [])
        for stock in ("1103", "2330"):
            group.append(fake_row(day, stock, i))
    paths = []
    for (y, m), records in sorted(grouped.items()):
        start = min(x["trade_date"] for x in records)
        end = max(x["trade_date"] for x in records)
        path = Path(directory) / f"twse-archive-{y}-{m:02d}.twseenc"
        encrypt_rows(sorted(records, key=lambda r: (
            r["trade_date"], r["stock_id"]
        )), path, start=start, end=end, hex_key=key)
        paths.append(path)
    return paths


class OwnerLocalAesFactorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.key = secrets.token_hex(32)

    def test_239_sessions_never_pads_240_day_factors(self):
        files = create_files(self.tmp.name, self.key, count=239)
        report = audit(files, hex_key=self.key)
        self.assertEqual(report["authentic_distinct_2022_source_sessions"], 239)
        self.assertEqual(report["additional_real_market_sessions_needed_before_240_session_warmup"], 1)
        self.assertEqual(report["exact_decimal_240_sma_computed_in_memory"], 0)
        self.assertEqual(report["causal_12_technical_smc_vectors_spotchecked"], 0)
        self.assertIsNone(report["aggregate_factor_fingerprint_sha256"])
        self.assertFalse(report["complete_five_year_trading_days_proven"])
        self.assertEqual(report["neon_connections"], 0)
        self.assertEqual(report["factor_rows_persisted"], 0)
        self.assertEqual(report["live_model_release_decision"], "BLOCKED")

    def test_241_real_aes_decoded_sessions_generate_sma_and_causal_prefix(self):
        files = create_files(self.tmp.name, self.key, count=241)
        report = audit(files, hex_key=self.key)
        self.assertEqual(report["authenticated_source_rows"], 482)
        self.assertEqual(report["authentic_distinct_2022_source_sessions"], 241)
        self.assertEqual(report["stocks_with_complete_last_240_source_sessions"], 2)
        self.assertEqual(report["exact_decimal_240_sma_computed_in_memory"], 2)
        self.assertEqual(report["causal_12_technical_smc_vectors_spotchecked"], 2)
        self.assertEqual(report["previous_signal_12_vector_prefix_parity_checked"], 2)
        self.assertEqual(len(report["aggregate_factor_fingerprint_sha256"]), 64)
        self.assertEqual(report["neon_rows_written"], 0)
        self.assertEqual(report["line_messages_sent"], 0)
        self.assertFalse(report["historical_survivorship_bias_resolved"])
        self.assertFalse(report["dividend_and_split_adjusted_features_or_labels"])

    def test_missing_last_session_for_one_stock_does_not_invent_price(self):
        days = sessions(241)
        rows = [fake_row(day, "1103", i) for i, day in enumerate(days)]
        rows += [fake_row(day, "2330", i) for i, day in enumerate(days[:-1])]
        grouped = {}
        for row in rows:
            month = row["trade_date"].month
            grouped.setdefault(month, []).append(row)
        paths = []
        for month, records in sorted(grouped.items()):
            path = Path(self.tmp.name) / f"m{month:02d}.twseenc"
            encrypt_rows(sorted(records,key=lambda r:(r["trade_date"],r["stock_id"])),
                         path, start=min(r["trade_date"] for r in records),
                         end=max(r["trade_date"] for r in records),hex_key=self.key)
            paths.append(path)
        report = audit(paths, hex_key=self.key)
        self.assertEqual(report["stocks_with_complete_last_240_source_sessions"], 1)
        self.assertEqual(report["exact_decimal_240_sma_computed_in_memory"], 1)

    def test_corruption_wrong_key_and_repeated_archive_refuse(self):
        files = create_files(self.tmp.name, self.key, count=4)
        with self.assertRaises((ValueError, Exception)):
            audit(files, hex_key=secrets.token_hex(32))
        with self.assertRaises(ValueError):
            audit(files + files, hex_key=self.key)
        original = files[0].read_bytes()
        files[0].write_bytes(original[:-17] + b"CORRUPT_FILE_12345")
        with self.assertRaises((ValueError, Exception)):
            audit(files, hex_key=self.key)

    def test_outside_2022_or_explicitly_excluded_fails_closed(self):
        bar = fake_row(date(2022, 1, 3), "1589", 0)
        with self.assertRaises(ValueError):
            _bar_ok(bar)
        bar = fake_row(date(2023, 1, 3), "2330", 0)
        with self.assertRaises(ValueError):
            _bar_ok(bar)
        bar = fake_row(date(2022, 1, 3), "2330", 0)
        bar["low"] = Decimal("-1")
        with self.assertRaises(ValueError):
            _bar_ok(bar)

    def test_mixed_year_folder_authenticates_and_excludes_2023(self):
        old = create_files(self.tmp.name, self.key, count=4)
        later = Path(self.tmp.name) / "other-year.twseenc"
        encrypt_rows([fake_row(date(2023, 3, 3), "2330", 11)],
                     later, start=date(2023, 3, 3),
                     end=date(2023, 3, 3), hex_key=self.key)
        report = audit(old + [later], hex_key=self.key)
        self.assertEqual(report["authenticated_archive_files"], len(old))
        self.assertEqual(report["other_year_archives_authenticated_and_excluded"], 1)
        self.assertEqual(report["excluded_other_archive_year_counts"], {"2023": 1})
        self.assertEqual(report["authentic_distinct_2022_source_sessions"], 4)
        self.assertEqual(report["neon_rows_written"], 0)
        self.assertEqual(report["live_model_release_decision"], "BLOCKED")

    def test_corrupted_excluded_year_archive_is_not_silently_ignored(self):
        old = create_files(self.tmp.name, self.key, count=3)
        later = Path(self.tmp.name) / "other-year.twseenc"
        encrypt_rows([fake_row(date(2023, 3, 3), "2330", 11)],
                     later, start=date(2023, 3, 3),
                     end=date(2023, 3, 3), hex_key=self.key)
        later.write_bytes(later.read_bytes()[:-1])
        with self.assertRaises(Exception):
            audit(old + [later], hex_key=self.key)

    def test_cross_year_archive_is_rejected_even_if_authenticated(self):
        old = create_files(self.tmp.name, self.key, count=3)
        crossing = Path(self.tmp.name) / "cross-year.twseenc"
        records = [fake_row(date(2022, 12, 30), "2330", 2),
                   fake_row(date(2023, 1, 3), "2330", 3)]
        encrypt_rows(records, crossing, start=date(2022, 12, 30),
                     end=date(2023, 1, 3), hex_key=self.key)
        with self.assertRaisesRegex(ValueError, "Cross-year"):
            audit(old + [crossing], hex_key=self.key)

    def test_no_public_stock_prices_in_aggregate_report(self):
        files = create_files(self.tmp.name, self.key, count=2)
        report = audit(files, hex_key=self.key)
        self.assertNotIn("price_rows", report)
        self.assertNotIn("stock_ids", report)
        self.assertFalse(report["source_captured_at_2022_trading_time_verified"])
        self.assertEqual(report["additional_real_market_sessions_needed_before_240_session_warmup"], 238)
        self.assertEqual(report["authenticated_archive_files"], 1)


if __name__ == "__main__":
    unittest.main()
