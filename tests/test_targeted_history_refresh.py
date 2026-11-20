"""No-network bounded history catch-up tests; never call a real database."""
import os
import unittest
from datetime import date
from unittest.mock import patch

from targeted_history_refresh import execute, TARGETS


class FakeCursor:
    def __init__(self, db):
        self.db=db
        self.params=None

    def __enter__(self):
        return self

    def __exit__(self,*_args):
        return False

    def execute(self,sql,params):
        self.params=params
        self.db.calls.append(params)

    def fetchone(self):
        market,stock_id=self.params
        earliest=date(2021,10,1) if stock_id=="2330" else date(2026,10,1)
        return {
            "market":market,"stock_id":stock_id,
            "stock_name":"test",
            "earliest_trade_date":earliest,
            "latest_trade_date":date(2026,11,19)
        }


class FakeDB:
    def __init__(self):
        self.calls=[]

    def __enter__(self):
        return self

    def __exit__(self,*_args):
        return False

    def cursor(self):
        return FakeCursor(self)


class TargetedHistoryTests(unittest.TestCase):
    def test_targets_are_explicitly_bounded(self):
        self.assertEqual(TARGETS,(("twse","2330"),("tpex","6488")))

    def test_dry_run_uses_only_selects_without_fetching_or_writing(self):
        fake=FakeDB()
        with (
            patch("targeted_history_refresh.psycopg.connect",return_value=fake),
            patch("targeted_history_refresh.refresh_one") as refresh,
        ):
            result=execute("postgresql://dummy.invalid/twstock",today=date(2026,11,20))
        self.assertEqual(result[0]["months"],1)
        self.assertEqual(result[1]["months"],4)
        self.assertEqual(result[1]["windows"],["2026-07..2026-09","2026-11..2026-11"])
        self.assertEqual(fake.calls,list(TARGETS))
        refresh.assert_not_called()

    def test_apply_has_second_gate_before_connect(self):
        with patch.dict(os.environ,{"STOCK_HISTORY_WRITE_ENABLED":""}):
            with patch("targeted_history_refresh.psycopg.connect") as conn:
                with self.assertRaisesRegex(ValueError,"disabled"):
                    execute("postgresql://not-real.invalid",apply=True)
                conn.assert_not_called()

    def test_apply_calls_same_indicator_pipeline_as_full_market(self):
        fake=FakeDB()
        with (
            patch.dict(os.environ,{"STOCK_HISTORY_WRITE_ENABLED":"yes"}),
            patch("targeted_history_refresh.psycopg.connect",return_value=fake),
            patch("targeted_history_refresh.refresh_one") as refresh,
            patch("targeted_history_refresh.build_adjusted_stock",return_value=30) as adj,
            patch("targeted_history_refresh.calculate_technical_stock",return_value=28) as tech,
            patch("targeted_history_refresh.calculate_smc_stock",return_value=28) as smc,
        ):
            result=execute("postgresql://dummy.invalid/twstock",apply=True,today=date(2026,11,20))
        self.assertEqual(refresh.call_count,2)
        self.assertEqual(adj.call_count,2)
        self.assertEqual(tech.call_count,2)
        self.assertEqual(smc.call_count,2)
        self.assertEqual(result[1]["computed"],{"adjusted":30,"technical":28,"smc":28})


if __name__=="__main__":
    unittest.main()
