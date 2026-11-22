"""Five-session price-only factor in runner memory, causal and no-write tests."""
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

from scripts import twse_stateless_2022_factor_canary as factor


def cohort_rows(day, n=700, shift=0):
    day_num=factor.DATES.index(day)
    output=[]
    for stock in range(1100,1100+n+1):
        sid=f"{stock:04d}"
        if sid=="1589":
            continue
        px=Decimal("100.0000")+Decimal(day_num)*Decimal("0.2500")
        output.append({
            "market":"twse", "stock_id":sid, "trade_date":day,
            "open":px, "high":px+Decimal("1"),
            "low":px-Decimal("1"),"close":px,
            "volume":100_000, "turnover":px*100_000,
            "transactions":100,"price_change":Decimal("0.25"),
            "source":"TWSE_MI_INDEX_ALLBUT0999"
        })
    return output[:n]


def allowed_cohort():
    return {("twse",r["stock_id"]) for r in cohort_rows(factor.DATES[0])}


class StatelessFactorCanaryTests(TestCase):
    def test_five_verified_sessions_create_exact_price_only_momentum(self):
        allowed=allowed_cohort()
        data=[cohort_rows(d) for d in factor.DATES]
        out=factor.compute_stateless_price_factor(data,allowed=allowed)
        self.assertEqual(out["fully_observed_five_session_stock_cohort"],700)
        self.assertEqual(out["official_current_allowed_bars_per_day"],[700]*5)
        self.assertEqual(Decimal(out["raw_price_only_median_4_interval_return"]),
                         Decimal("0.01"))
        self.assertEqual(out["raw_price_only_positive_momentum_stock_count"],700)
        self.assertEqual(out["as_of_session"],"2022-01-10")
        self.assertEqual(len(out["feature_input_sha256"]),64)
        self.assertFalse(out["historical_issuer_survivorship_free"])
        self.assertFalse(out["total_return_dividend_adjusted"])
        self.assertFalse(out["five_year_technical_factor_coverage_proven"])
        self.assertFalse(out["live_trading_approved"])
        self.assertEqual(out["source_ohlcv_rows_written"],0)
        self.assertEqual(out["model_derived_rows_written"],0)

    def test_reject_incomplete_or_mixed_dates_or_source(self):
        base=[cohort_rows(d) for d in factor.DATES]
        for altered in ("wrong_date","bad_source","missing_last_day",
                        "unpriced_close","missing_one_session"):
            rows=[[dict(x) for x in sample] for sample in base]
            if altered=="wrong_date":
                rows[2][0]["trade_date"]=factor.DATES[1]
            elif altered=="bad_source":
                rows[0][0]["source"]="UNKNOWN"
            elif altered=="missing_last_day":
                rows[-1]=rows[-1][:400]
            elif altered=="unpriced_close":
                rows[1][0]["close"]=None
            else:
                rows=rows[:4]
            with self.subTest(altered=altered),self.assertRaises(ValueError):
                factor.compute_stateless_price_factor(rows,allowed=allowed_cohort())

    def test_run_uses_only_readonly_roster_and_five_bounded_http_gets(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        seen=[]
        def get_source(day):
            seen.append(day)
            return cohort_rows(day)
        with (
            TemporaryDirectory() as td,
            patch("psycopg.connect",return_value=conn) as dial,
            patch.object(factor,"load_current_twse_allowed",return_value=allowed_cohort()),
            patch.object(factor,"_processed_days",return_value=set()),
        ):
            dest=Path(td)/"aggregates.json"
            report=factor.execute("postgresql://fake",fetcher=get_source,
                                  pause_seconds=0,output=dest)
            self.assertEqual(seen,list(factor.DATES))
            self.assertEqual(report["fully_observed_five_session_stock_cohort"],700)
            self.assertEqual(report["model_derived_rows_written"],0)
            self.assertEqual(report["line_messages_sent"],0)
            self.assertFalse(report["independent_out_of_sample_alpha_proven"])
            self.assertTrue(dest.is_file())
            content=dest.read_text()
            self.assertEqual(json.loads(content),report)
            self.assertNotIn("stock_id",content)
            self.assertNotIn("2330",content)
            self.assertEqual(conn.execute.call_args_list[0].args[0],
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            self.assertIn("default_transaction_read_only=on",
                          dial.call_args.kwargs["options"])

    def test_processed_days_refused_before_official_get(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        calls=[]
        with (
            patch("psycopg.connect",return_value=conn),
            patch.object(factor,"load_current_twse_allowed",return_value=allowed_cohort()),
            patch.object(factor,"_processed_days",return_value={factor.DATES[2]}),
        ):
            with self.assertRaisesRegex(ValueError,"no longer missing"):
                factor.execute("fake",fetcher=lambda x:calls.append(x),
                               pause_seconds=0)
        self.assertEqual(calls,[])

    def test_currently_excluded_stock_never_enters_factor(self):
        allowed=allowed_cohort()|{("twse","1589")}
        with self.assertRaises(ValueError):
            factor.compute_stateless_price_factor(
                [cohort_rows(d) for d in factor.DATES],allowed=allowed
            )
        self.assertEqual(factor.MAX_SOURCE_CALLS,5)
