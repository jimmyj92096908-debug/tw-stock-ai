"""Budget, double source gates, exact change reconciliation, one-time wave."""
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock,patch

from scripts import tpex_factor_bounded_campaign as campaign


def state(*,complete=192,eligible=879,source_days=91,db_bytes=295_000_000,
          bad_volume=0,bad_turnover=0):
    return {
        "tpex_source_days":source_days,
        "twse_source_days":137,
        "tpex_eligible":eligible,
        "tpex_matched":eligible,
        "tpex_historical_factors_current":complete,
        "legacy_rows":26504,
        "bad_legacy_volume":bad_volume,
        "bad_legacy_turnover":bad_turnover,
        "database_bytes":db_bytes,
    }


GATES={
    "STOCK_TPEX_FACTOR_CAMPAIGN_ENABLED":"yes",
    "STOCK_TPEX_STALE_FACTOR_WRITE_ENABLED":"yes",
    "STOCK_INDICATOR_CATCHUP_WRITE_ENABLED":"yes",
    "STOCK_TPEX_STALE_SCORE_WRITE_ENABLED":"yes",
}


def mock_runner(command,**kwargs):
    assert command[1].endswith("tpex_stale_factor_refresh.py")
    assert command[2:5]==["--apply","--rounds","5"]
    assert kwargs["check"] and kwargs["timeout"]==2400
    number=int(Path(command[-1]).stem.split("-")[-1])
    stocks=[{"stock_id":str(1000+number*100+i),"status":"verified"}
            for i in range(100)]
    Path(command[-1]).write_text(json.dumps({
        "stocks":stocks,
        "raw_prices_modified":False,
        "trading_enabled":False,
    }))
    return subprocess.CompletedProcess(command,0)


class TPExBoundedCampaignTests(unittest.TestCase):
    def test_preview_never_starts_worker_and_requires_no_write_gate(self):
        reader=MagicMock(return_value=state())
        runner=MagicMock()
        with TemporaryDirectory() as directory:
            record=campaign.execute(
                "protected",apply=False,reader=reader,runner=runner,
                report_path=Path(directory)/"preview.json")
        self.assertEqual(len(record["rounds"]),0)
        self.assertFalse(record["raw_prices_modified"])
        self.assertFalse(record["line_trade_signals_sent"])
        self.assertFalse(record["paid_upgrade_requested"])
        reader.assert_called_once_with("protected")
        runner.assert_not_called()

    def test_four_gates_and_batch_cap(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaisesRegex(ValueError,"four independent"):
                campaign.execute("protected",apply=True)
        for value in (-1,6,True):
            with self.assertRaisesRegex(ValueError,"Unsafe"):
                campaign.execute("protected",max_batches=value)
        with patch.dict(os.environ,GATES):
            with self.assertRaisesRegex(ValueError,"four independent"):
                campaign.execute("protected",apply=True,max_batches=0)
        self.assertEqual(campaign.MAX_BATCHES,5)
        self.assertEqual(campaign.INNER_STOCK_CAP,100)
        self.assertEqual(campaign.INNER_ROUNDS,5)

    def test_bounded_three_consecutive_full_batches_reconcile(self):
        snapshots=[
            state(complete=192),state(complete=292),
            state(complete=392),state(complete=492),
        ]
        with TemporaryDirectory() as directory,patch.dict(os.environ,GATES):
            reader=MagicMock(side_effect=snapshots)
            report=campaign.execute("fake",apply=True,max_batches=3,
                report_path=Path(directory)/"audit.json",
                reader=reader,runner=mock_runner)
            self.assertEqual(report["latest"]["tpex_historical_factors_current"],492)
            self.assertEqual(len(report["rounds"]),3)
            self.assertEqual([x["newly_verified"] for x in report["rounds"]],
                             [100,100,100])
            self.assertFalse(report["finished"])
            persisted=json.loads((Path(directory)/"audit.json").read_text())
            self.assertEqual(persisted["latest"]["tpex_historical_factors_current"],492)
            self.assertEqual(reader.call_count,4)

    def test_last_partial_batch_finishes_without_fake_overwrite(self):
        before=state(complete=870)
        after=state(complete=879)
        def partial_runner(command,**_):
            Path(command[-1]).write_text(json.dumps({
                "stocks":[{"stock_id":str(i),"status":"verified"} for i in range(9)],
                "raw_prices_modified":False,
                "trading_enabled":False,
            }))
        with TemporaryDirectory() as directory,patch.dict(os.environ,GATES):
            reader=MagicMock(side_effect=[before,after])
            out=campaign.execute("fake",apply=True,max_batches=5,
                 report_path=Path(directory)/"evidence.json",
                 reader=reader,runner=partial_runner)
        self.assertTrue(out["finished"])
        self.assertEqual(sum(x["newly_verified"] for x in out["rounds"]),9)

    def test_fail_closed_on_unverified_source_or_extra_stock_or_no_progress(self):
        with patch.dict(os.environ,GATES):
            reader=MagicMock(return_value=state(source_days=60))
            with self.assertRaisesRegex(RuntimeError,"source/legacy"):
                campaign.execute("fake",apply=True,reader=reader)
        for before,after,stocks in (
            (state(),state(complete=192),[{"stock_id":"1234","status":"verified"}]),
            (state(),state(complete=292),[{"stock_id":"1234","status":"verified"}]),
            (state(),state(complete=193),[{"stock_id":"1234","status":"failed"}]),
            (state(),state(complete=193),[{"stock_id":"1234","status":"verified"}]*2),
            (state(),state(complete=193,db_bytes=900_000_000),
                [{"stock_id":"1234","status":"verified"}]),
            (state(),state(complete=193,eligible=880),
                [{"stock_id":"1234","status":"verified"}]),
        ):
            with self.subTest(after=after,stocks=stocks),self.assertRaises(RuntimeError):
                campaign.validate(before,after,stocks)

    def test_child_worker_failure_never_misrepresents_success(self):
        def raise_child(command,**kwargs):
            raise subprocess.TimeoutExpired(command,kwargs["timeout"])
        with TemporaryDirectory() as directory,patch.dict(os.environ,GATES):
            with self.assertRaisesRegex(RuntimeError,"failed closed"):
                campaign.execute("fake",apply=True,max_batches=1,
                    reader=lambda _:state(),
                    runner=raise_child,
                    report_path=Path(directory)/"error.json")

    def test_only_existing_workflow_and_scripts_no_trading_or_line(self):
        text=Path(campaign.__file__).read_text(encoding="utf-8")
        self.assertNotIn("UPDATE public.daily_prices",text)
        self.assertNotIn("LINE_CHANNEL",text)
        self.assertIn("MAX_BATCHES=5",text)
        self.assertIn("source/legacy",text)


if __name__=="__main__":
    unittest.main()
