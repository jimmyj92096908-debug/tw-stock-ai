"""Bounded 2022 whole-market-on-demand replay and synthetic 241-day CI."""
from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

from scripts import twse_2022_shared_source_stream as m


def allowed_codes():
    ids = [f"{x:04d}" for x in range(1100, 1850) if x != 1589]
    return {("twse", x) for x in ids}


def synthetic_day(day, count=650):
    ids = sorted(x[1] for x in allowed_codes())[:count]
    # The daily OHLCV has a deterministic trend + oscillation for RSI/ATR.
    ordinal = (day-date(2022, 1, 1)).days
    bars = []
    for index, sid in enumerate(ids):
        close = (Decimal("40") + Decimal(index % 50)
                 + Decimal(ordinal)/Decimal("100")
                 + Decimal((ordinal % 7) - 3)/Decimal("10"))
        bars.append({
            "market": "twse", "stock_id": sid, "trade_date": day,
            "open": close - Decimal("0.05"),
            "high": close + Decimal("0.55"),
            "low": close - Decimal("0.65"),
            "close": close, "volume": 100_000 + ordinal,
            "turnover": close * Decimal(100_000 + ordinal),
            "transactions": 200,
            "price_change": Decimal("0.01"),
            "source": m.SOURCE_TAG,
        })
    return bars


def first_business_days(count):
    out = []
    d = date(2022, 1, 4)
    while len(out) < count:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return tuple(out)


class StatelessMarketReplayTests(TestCase):
    def test_twelve_authentic_day_canary_shape_source_and_cohort(self):
        dates = first_business_days(12)
        report = m.compute_stream(dates, allowed_codes(), synthetic_day)
        self.assertEqual(report["authentic_source_days_evaluated"], 12)
        self.assertEqual(report["complete_common_stock_cohort"], 650)
        self.assertEqual(report["daily_current_eligible_source_bar_counts"], [650]*12)
        self.assertEqual(report["raw_price_return_intervals"], 11)
        self.assertEqual(report["stock_ma240_passes"], 0)
        self.assertEqual(report["technical_smc_240_prefix_checks"], 0)
        self.assertFalse(report["synthetic_full_241_session_stress_verified"])
        self.assertFalse(report["stock_ma240_historical_proof"])
        self.assertFalse(report["survivorship_free_historical_universe_verified"])
        self.assertFalse(report["live_trading_approved"])
        self.assertEqual(report["raw_price_or_factor_rows_persisted"], 0)
        self.assertEqual(report["neon_rows_written"], 0)
        self.assertEqual(len(report["source_content_sha256"]), 64)
        self.assertNotIn("stock_id", report)

    def test_241_day_stress_proves_ma240_for_many_and_5_feature_prefixes(self):
        days = first_business_days(241)
        result = m.compute_stream(days, allowed_codes(), synthetic_day)
        self.assertEqual(result["synthetic_source_days_evaluated"], 241)
        self.assertEqual(result["authentic_source_days_evaluated"], 0)
        self.assertEqual(result["fully_observed_stock_cohort"], 650)
        self.assertEqual(result["stock_ma240_passes"], 650)
        self.assertEqual(result["technical_smc_240_prefix_checks"], 5)
        self.assertFalse(result["real_2022_241_session_source_replayed"])
        self.assertEqual(result["neon_rows_written"], 0)
        self.assertFalse(result["live_trading_approved"])

    def test_missing_date_wrong_source_duplicate_or_invalid_ohlc_fails_closed(self):
        days = first_business_days(12)
        for wrong in ("missing_stock", "duplicate", "bad_source",
                      "fake_1589", "bad_close", "bad_date", "bad_decimal"):
            def feed(day):
                original = synthetic_day(day)
                if day == days[4]:
                    if wrong == "missing_stock":
                        return original[:400]
                    if wrong == "duplicate":
                        return original + [dict(original[0])]
                    if wrong == "bad_source":
                        original[0]["source"] = "TWSE_STOCK_DAY"
                    if wrong == "fake_1589":
                        original[0]["stock_id"] = "1589"
                    if wrong == "bad_close":
                        original[0]["close"] = Decimal("-1")
                    if wrong == "bad_date":
                        original[0]["trade_date"] = days[3]
                    if wrong == "bad_decimal":
                        original[0]["high"] = float(original[0]["high"])
                return original

            # The full-market filter explicitly drops disallowed 1589: a
            # single extra 1589 source row must NOT poison accepted data.
            if wrong == "fake_1589":
                result = m.compute_stream(days, allowed_codes(), feed)
                self.assertEqual(result["complete_common_stock_cohort"], 649)
            else:
                with self.subTest(case=wrong), self.assertRaises(ValueError):
                    m.compute_stream(days, allowed_codes(), feed)

    def test_real_pilot_protection_readonly_and_twelve_source_call_cap(self):
        dates = first_business_days(12)
        conn = MagicMock()
        conn.__enter__.return_value = conn
        cur = MagicMock()
        cur.__enter__.return_value = cur
        cur.fetchall.return_value = [(d,) for d in dates]
        conn.cursor.return_value = cur
        seen = []
        pauses = []
        def fetcher(day):
            seen.append(day)
            return synthetic_day(day)
        with (
            TemporaryDirectory() as td,
            patch("psycopg.connect",return_value=conn) as dial,
            patch.object(m,"load_current_twse_allowed",
                         return_value=allowed_codes()),
            patch.object(m,"_processed_days",return_value=set()),
        ):
            output=Path(td)/"aggregates-only.json"
            result=m.execute(
                "postgres://fake",fetcher=fetcher,
                sleeper=pauses.append,output=output,
            )
            self.assertEqual(seen,list(dates))
            self.assertEqual(len(pauses),11)
            self.assertEqual(set(pauses),{2.0})
            self.assertEqual(result["actual_official_http_requests"],12)
            self.assertEqual(result["maximum_official_http_requests"],12)
            self.assertTrue(output.is_file())
            doc=output.read_text()
            self.assertEqual(json.loads(doc),result)
            self.assertNotIn('"stock_id"',doc)
            self.assertNotIn('"close"',doc)
            self.assertNotIn('"2330"',doc)
            self.assertIn("default_transaction_read_only=on",
                          dial.call_args.kwargs["options"])
            self.assertEqual(conn.execute.call_args_list[0].args[0],
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cur.execute.assert_called_once_with(
                m.REFERENCE_CALENDAR_SQL,(m.START,m.END,m.PILOT_SOURCE_DAYS),
            )

    def test_existing_import_receipt_blocks_before_http(self):
        dates=first_business_days(12)
        conn=MagicMock()
        conn.__enter__.return_value=conn
        cur=MagicMock()
        cur.__enter__.return_value=cur
        cur.fetchall.return_value=[(d,) for d in dates]
        conn.cursor.return_value=cur
        seen=[]
        with (
            patch("psycopg.connect",return_value=conn),
            patch.object(m,"load_current_twse_allowed",
                         return_value=allowed_codes()),
            patch.object(m,"_processed_days",return_value={dates[5]}),
        ):
            with self.assertRaisesRegex(ValueError,"already|imported"):
                m.execute("fake",fetcher=lambda day:seen.append(day))
        self.assertEqual(seen,[])

    def test_untrusted_date_order_weekend_overbudget_and_unlisted_guard(self):
        dates=first_business_days(12)
        for bad in (
            dates[::-1],
            (dates[0],dates[0]),
            (date(2022,1,8),dates[1]),
            dates+(date(2023,1,2),),
            first_business_days(242),
        ):
            with self.assertRaises(ValueError):
                m.validate_days(bad)
        with self.assertRaises(ValueError):
            m.validate_days(first_business_days(13),real_pilot=True)
        with self.assertRaises(ValueError):
            m.compute_stream(dates, {("twse","1589")}|allowed_codes(),
                             synthetic_day)
        with self.assertRaises(ValueError):
            m.compute_stream(dates, {("twse","2330")},synthetic_day)
        self.assertLessEqual(m.MAX_STREAM_SESSIONS,241)
        self.assertEqual(m.PILOT_SOURCE_DAYS,12)
        self.assertEqual(m.SOURCE_TAG,"TWSE_MI_INDEX_ALLBUT0999")
