"""Offline evidence: bounded, official, read-only TWSE raw-factor canary."""
from unittest import TestCase
from unittest.mock import MagicMock,patch

from scripts import twse_raw_factor_canary as canary
from tests.test_raw_factor_feature_bridge import bars


class TWSEInMemoryCanaryTests(TestCase):
    def test_only_latest_official_current_listed_stocks_are_allowed(self):
        self.assertIn("official_current_listed",canary.CANDIDATES_SQL)
        self.assertIn("INTERVAL '14 days'",canary.CANDIDATES_SQL)
        self.assertIn("m.valid_days>=240",canary.CANDIDATES_SQL)
        self.assertIn("m.latest=l.day",canary.CANDIDATES_SQL)
        self.assertIn("ORDER BY trade_date DESC LIMIT %s",canary.SOURCE_SQL)
        self.assertNotIn("INSERT INTO",canary.SOURCE_SQL.upper())
        self.assertNotIn("UPDATE",canary.SOURCE_SQL.upper())
        with self.assertRaisesRegex(ValueError,"DATABASE_URL"):
            canary.run("")

    def test_causal_source_reconstruction_has_no_persistent_factor_writes(self):
        from datetime import date
        stocks=[str(2330+i) for i in range(5)]
        last=date(2025,11,17)
        # Make current market date the last synthetic fixture session.
        raw=bars(320,stock="2330")
        last=raw[-1]["trade_date"]
        eligible=[{"stock_id":sid,"valid_days":320,"market_day":last}
                  for sid in stocks]
        records={sid:[dict(r,stock_id=sid,market="twse",
                           source="TWSE_MI_INDEX_ALLBUT0999")
                      for r in bars(320,stock=sid)]
                 for sid in stocks}
        conn=MagicMock()
        conn.__enter__.return_value=conn
        def query(sql,params=None):
            response=MagicMock()
            if sql.startswith("SET "):
                return response
            if "pg_database_size" in sql:
                response.fetchone.return_value={"bytes":550_000_000}
            elif sql==canary.CANDIDATES_SQL:
                response.fetchall.return_value=eligible
            elif sql==canary.SOURCE_SQL:
                response.fetchall.return_value=records[params[0]]
            else:
                raise AssertionError("Unexpected SQL")
            return response
        conn.execute.side_effect=query
        with patch.object(canary.psycopg,"connect",return_value=conn) as connected:
            result=canary.run("postgresql://disposable-stub")
        self.assertEqual(result["real_stock_sample_count"],5)
        self.assertEqual(result["original_source_price_rows"],1600)
        self.assertEqual(result["verified_no_future_suffix_samples"],5)
        self.assertEqual(result["persistent_technical_or_smc_rows_written"],0)
        self.assertFalse(result["trading_approved"])
        self.assertFalse(result["independent_future_model_validation_proven"])
        self.assertIn("default_transaction_read_only=on",
                      connected.call_args.kwargs["options"])
        self.assertIn("READ ONLY",conn.execute.call_args_list[0].args[0])
