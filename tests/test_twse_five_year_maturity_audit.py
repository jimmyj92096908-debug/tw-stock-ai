"""Offline read-only SQL and threshold guard for TWSE source maturity."""
from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch

from scripts import twse_five_year_maturity_audit as audit


def state(**extra):
    return {
        "active_stocks":1092,"mature_240":20,"mature_1000":20,
        "no_valid_price":1,"minimum_days":0,
        "average_days":Decimal("192.0"),
        "official_bulk_sessions":190,
        "raw_twse_rows":210000,"database_bytes":540_000_000,
        **extra,
    }


class FakeConnection:
    def __init__(self,row):
        self.row=row
        self.sql=[]
    def __enter__(self):return self
    def __exit__(self,*_):return False
    def execute(self,sql):
        self.sql.append(sql)
        return self
    def fetchone(self):return self.row


class MaturityTests(TestCase):
    def test_current_official_issuer_join_and_no_fabricated_five_year_claim(self):
        sql=audit.MATURITY_SQL
        self.assertIn("official_current_listed",sql)
        self.assertIn("14 days",sql)
        self.assertIn("LEFT JOIN public.daily_prices p",sql)
        self.assertIn("p.close>0 AND p.volume>=0",sql)
        self.assertIn("count(DISTINCT trade_date)",sql)
        self.assertNotIn("UPDATE public.daily_prices",sql.upper())
        report=audit.describe(state())
        self.assertFalse(report["fully_five_year_verified"])
        self.assertFalse(report["derived_240_day_ready"])
        self.assertFalse(report["trading_approved"])
        self.assertFalse(report["line_messages_sent"])

    def test_readonly_connection_and_real_active_scope(self):
        connection=FakeConnection(state())
        with patch.object(audit.psycopg,"connect",return_value=connection) as connect:
            row=audit.capture("postgresql://disposable-fake")
        self.assertEqual(row["active_stocks"],1092)
        self.assertIn("SET TRANSACTION",connection.sql[0])
        self.assertIn("READ ONLY",connection.sql[0])
        self.assertIn("default_transaction_read_only=on",
                      connect.call_args.kwargs["options"])

    def test_maturity_cutoff_cannot_be_padded_by_outdated_or_invalid_scope(self):
        for fields in (
            {"active_stocks":0},
            {"mature_1000":22},
            {"mature_240":1100},
            {"no_valid_price":1093},
            {"raw_twse_rows":-1},
            {"official_bulk_sessions":"190"},
        ):
            with self.subTest(fields=fields):
                with patch.object(audit.psycopg,"connect",
                                  return_value=FakeConnection(state(**fields))):
                    with self.assertRaises(RuntimeError):
                        audit.capture("postgresql://disposable-fake")
        s=state(mature_240=1000,official_bulk_sessions=240)
        self.assertTrue(audit.describe(s)["derived_240_day_ready"])
        self.assertTrue(audit.describe(state(database_bytes=800_000_000))["db_capacity_stop"])
