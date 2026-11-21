"""Offline safety regression for source ledger and real OHLCV acceptance."""
from datetime import date
from unittest import TestCase
from unittest.mock import MagicMock,patch

from scripts import twse_five_year_source_integrity as audit


def evidence(**overrides):
    return {
        "processed_days":368,"imported_days":344,"closed_days":24,
        "invalid_progress_days":0,"inserted_receipts":356906,
        "official_price_rows":359023,"official_price_dates":344,
        "invalid_ohlcv_rows":0,"earliest_official_date":date(2025,6,25),
        "database_bytes":584_466_432,"missing_five_year_weekdays":937,
        **overrides,
    }


class TWSEHistoricalSourceAcceptanceTests(TestCase):
    def test_real_source_progress_does_not_pretend_five_years_are_complete(self):
        proof=audit.evaluate(evidence())
        self.assertTrue(proof["official_date_progress_reconciled"])
        self.assertTrue(proof["raw_source_ohlcv_validated"])
        self.assertFalse(proof["five_year_dates_fully_examined"])
        self.assertFalse(proof["model_holdout_validated"])
        self.assertFalse(proof["live_trading_enabled"])
        self.assertEqual(proof["database_mutations"],0)
        self.assertIn("invalid_ohlcv_rows",audit.STATE_SQL)
        self.assertIn("twse_history_day_progress",audit.STATE_SQL)
        self.assertIn("missing_five_year_weekdays",audit.STATE_SQL)
        self.assertIn("Asia/Taipei",audit.STATE_SQL)
        self.assertNotIn("INSERT INTO",audit.STATE_SQL.upper())
        self.assertNotIn("UPDATE ",audit.STATE_SQL.upper())
        future=evidence(processed_days=1124,imported_days=1100,
                        official_price_dates=1100,official_price_rows=1100000,
                        missing_five_year_weekdays=0)
        self.assertTrue(audit.evaluate(future)["five_year_dates_fully_examined"])

    def test_mismatched_progress_and_corrupted_official_price_data_fail_closed(self):
        for change in (
            {"processed_days":367},
            {"imported_days":343},
            {"invalid_progress_days":1},
            {"official_price_dates":340},
            {"invalid_ohlcv_rows":1},
            {"official_price_rows":0},
            {"missing_five_year_weekdays":-1},
        ):
            with self.subTest(change=change),self.assertRaises(RuntimeError):
                audit.evaluate(evidence(**change))

    def test_database_transaction_is_strictly_readonly(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        def execute(sql):
            result=MagicMock()
            if sql==audit.STATE_SQL:
                result.fetchone.return_value=evidence()
            return result
        conn.execute.side_effect=execute
        with patch.object(audit.psycopg,"connect",return_value=conn) as connected:
            proof=audit.run("postgresql://disposable-fake")
        self.assertEqual(proof["database_mutations"],0)
        self.assertIn("default_transaction_read_only=on",
                      connected.call_args.kwargs["options"])
        self.assertIn("READ ONLY",conn.execute.call_args_list[0].args[0])
        with self.assertRaisesRegex(ValueError,"DATABASE_URL"):
            audit.run("")
