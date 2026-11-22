"""Safety regression for one-time source-verified TWSE long-history campaign."""
import os
from unittest import TestCase
from unittest.mock import patch

from scripts import twse_long_history_campaign as campaign


def state(*, source_days=137, rows=172710, valid=172595, source_rows=145216,
          bytes_=265000000):
    return {"source_days":source_days, "raw_twse_rows":rows,
            "valid_twse_rows":valid, "source_rows":source_rows,
            "database_bytes":bytes_}


def bar(day, *, inserted=900, qualified=1000):
    return {"trade_date":day, "status":"imported",
            "inserted":inserted, "qualified":qualified}


class TWSELongHistoryCampaignTests(TestCase):
    def test_never_fetches_or_writes_on_preview(self):
        with (
            patch.object(campaign,"snapshot",return_value=state()),
            patch.object(campaign,"source_run") as run,
        ):
            report=campaign.execute("fake",apply=False)
        self.assertFalse(report["finished"])
        self.assertFalse(report["trading_enabled"])
        self.assertFalse(report["line_messages_sent"])
        run.assert_not_called()

    def test_both_apply_gates_and_strict_20_rounds(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaisesRegex(ValueError,"write gates"):
                campaign.execute("fake",apply=True)
        for n in (-1,21,100):
            with self.assertRaisesRegex(ValueError,"Unsafe"):
                campaign.execute("fake",max_rounds=n)
        with self.assertRaisesRegex(ValueError,"write gates"):
            campaign.execute("fake",apply=True,max_rounds=0)
        self.assertEqual(campaign.MAX_ROUNDS,20)
        self.assertEqual(campaign.MAX_DAYS_PER_ROUND,8)
        self.assertEqual(campaign.LOOKBACK_DAYS,1830)
        self.assertIn("TWSE_MI_INDEX_ALLBUT0999",campaign.STATE_SQL)

    def test_two_validated_rounds_reconcile_actual_rows(self):
        first=state()
        middle=state(source_days=138,rows=173610,valid=173495,
                     source_rows=146116)
        last=state(source_days=139,rows=174610,valid=174495,
                   source_rows=147116)
        with (
            patch.dict(os.environ,{
                "STOCK_TWSE_LONG_HISTORY_CAMPAIGN_ENABLED":"yes",
                "STOCK_TWSE_HISTORY_WRITE_ENABLED":"yes",
            }),
            patch.object(campaign,"snapshot",side_effect=[first,middle,last]),
            patch.object(campaign,"source_run",side_effect=[
                [bar("2026-05-04",inserted=900)],
                [bar("2026-05-01",inserted=1000)],
            ]) as source,
        ):
            report=campaign.execute("fake",apply=True,max_rounds=2)
        self.assertFalse(report["finished"])
        self.assertEqual([x["new_valid_bars"] for x in report["batches"]],[900,1000])
        self.assertEqual(report["latest"]["source_days"],139)
        self.assertEqual(source.call_count,2)
        source.assert_any_call("fake",apply=True,batch_days=8,
                               lookback_days=1830,pause_seconds=2)

    def test_stops_before_fetch_when_free_storage_reserve_insufficient(self):
        near=state(bytes_=745_000_000)
        with (
            patch.dict(os.environ,{
                "STOCK_TWSE_LONG_HISTORY_CAMPAIGN_ENABLED":"yes",
                "STOCK_TWSE_HISTORY_WRITE_ENABLED":"yes",
            }),
            patch.object(campaign,"snapshot",return_value=near),
            patch.object(campaign,"source_run",side_effect=AssertionError("unsafe fetch")) as run,
        ):
            report = campaign.execute("fake",apply=True,max_rounds=1)
        run.assert_not_called()
        self.assertTrue(report["capacity_guard_blocked"])
        self.assertFalse(report["finished"])
        self.assertEqual(report["batches"],[])
        self.assertEqual(report["capacity_pause_reason"],
                         "neon_free_maintenance_reserve")

    def test_pauses_safely_after_verified_insert_before_next_unsafe_round(self):
        initial=state(bytes_=700_000_000)
        near_limit=state(source_days=138, rows=173610, valid=173495,
                         source_rows=146116, bytes_=745_000_000)
        with (
            patch.dict(os.environ,{
                "STOCK_TWSE_LONG_HISTORY_CAMPAIGN_ENABLED":"yes",
                "STOCK_TWSE_HISTORY_WRITE_ENABLED":"yes",
            }),
            patch.object(campaign,"snapshot",side_effect=[initial,near_limit]),
            patch.object(campaign,"source_run",
                         return_value=[bar("2026-05-04",inserted=900)]) as importer,
        ):
            report=campaign.execute("fake",apply=True,max_rounds=20)
        self.assertEqual(importer.call_count,1)
        self.assertEqual(report["batches"][0]["new_valid_bars"],900)
        self.assertEqual(report["latest"]["source_days"],138)
        self.assertTrue(report["capacity_guard_blocked"])
        self.assertFalse(report["finished"])
        self.assertFalse(report["line_messages_sent"])

    def test_duplicate_source_date_refused(self):
        with self.assertRaisesRegex(RuntimeError,"Unverified"):
            campaign.inspect_batch([bar("2026-05-04"),bar("2026-05-04")],
                                   already_seen=set())
        with self.assertRaisesRegex(RuntimeError,"Unverified"):
            campaign.inspect_batch([bar("2026-05-04")],
                                   already_seen={"2026-05-04"})
        with self.assertRaisesRegex(RuntimeError,"Unverified"):
            campaign.inspect_batch([bar("2026-05-04",qualified=500,inserted=600)],
                                   already_seen=set())
        with self.assertRaisesRegex(RuntimeError,"unbounded"):
            campaign.inspect_batch([bar(str(i)) for i in range(9)],
                                   already_seen=set())

    def test_unverifiable_delta_fails_closed(self):
        with (
            patch.dict(os.environ,{
                "STOCK_TWSE_LONG_HISTORY_CAMPAIGN_ENABLED":"yes",
                "STOCK_TWSE_HISTORY_WRITE_ENABLED":"yes",
            }),
            patch.object(campaign,"snapshot",side_effect=[
                state(),state(source_days=138,rows=173000,valid=172800,
                              source_rows=145700)]),
            patch.object(campaign,"source_run",
                         return_value=[bar("2026-05-04",inserted=900)]),
        ):
            with self.assertRaisesRegex(RuntimeError,"reconciliation"):
                campaign.execute("fake",apply=True,max_rounds=1)

    def test_suspicious_holiday_streak_stops(self):
        closed=lambda x:{"trade_date":x,"status":"closed",
                         "qualified":0,"inserted":0}
        with (
            patch.dict(os.environ,{
                "STOCK_TWSE_LONG_HISTORY_CAMPAIGN_ENABLED":"yes",
                "STOCK_TWSE_HISTORY_WRITE_ENABLED":"yes",
            }),
            patch.object(campaign,"snapshot",return_value=state()),
            patch.object(campaign,"source_run",side_effect=[
                [closed("2026-05-04")],[closed("2026-05-01")],
            ]),
        ):
            with self.assertRaisesRegex(RuntimeError,"Repeated zero-insert"):
                campaign.execute("fake",apply=True,max_rounds=2)
