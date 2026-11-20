"""Fail closed on unverified or inconsistent indicator catch-up after evidence."""
import unittest

from scripts.indicator_batch_reconcile import reconcile


def snapshot(twse_pending=1044, tpex_pending=0, *, twse_eligible=1085, tpex_eligible=21,
             day="2026-11-19"):
    return {
        "schema_version": 1,
        "latest_price_date": day,
        "database_transaction_read_only": True,
        "indicator_writes_performed": False,
        "automatic_write_schedule_activated": False,
        "candidate_selection_tested_against_real_sql": True,
        "markets": [
            {"market":"twse","eligible":twse_eligible,"pending":twse_pending,
             "complete":twse_eligible-twse_pending,"unstarted":min(twse_pending,942),
             "preview_candidate_count":min(20,twse_pending)},
            {"market":"tpex","eligible":tpex_eligible,"pending":tpex_pending,
             "complete":tpex_eligible-tpex_pending,"unstarted":0,
             "preview_candidate_count":min(20,tpex_pending)},
        ]
    }


class IndicatorBatchReconcileTests(unittest.TestCase):
    def test_twse_20_backfilled_and_tpex_idle_is_success(self):
        result = reconcile(snapshot(), snapshot(1024))
        self.assertTrue(result["progress_verified"])
        self.assertEqual(result["markets"][0]["decrease_in_pending"],20)
        self.assertEqual(result["markets"][0]["status"],"improved")
        self.assertEqual(result["markets"][1]["status"],"no_work")
        self.assertFalse(result["all_pending_cleared"])
        self.assertFalse(result["live_trade_signals_enabled"])

    def test_all_complete_from_start_is_successful_no_work(self):
        result = reconcile(snapshot(0), snapshot(0))
        self.assertTrue(result["progress_verified"])
        self.assertTrue(result["all_pending_cleared"])

    def test_zero_change_does_not_count_as_success_if_any_pending(self):
        result = reconcile(snapshot(), snapshot())
        self.assertFalse(result["progress_verified"])
        self.assertEqual(result["markets"][0]["status"],"no_proven_progress")

    def test_newly_pending_after_job_is_failure(self):
        result = reconcile(snapshot(1044), snapshot(1045))
        self.assertFalse(result["progress_verified"])
        self.assertEqual(result["markets"][0]["decrease_in_pending"],-1)

    def test_universe_change_is_inconclusive_even_if_pending_drops(self):
        result = reconcile(snapshot(), snapshot(1024,twse_eligible=1086))
        self.assertFalse(result["progress_verified"])
        self.assertEqual(result["markets"][0]["status"],"inconclusive_eligible_universe_changed")

    def test_date_change_or_missing_date_blocks_proof(self):
        with self.assertRaisesRegex(ValueError,"Price date"):
            reconcile(snapshot(),snapshot(1024,day="2026-11-20"))
        with self.assertRaisesRegex(ValueError,"Price date"):
            reconcile(snapshot(day=None),snapshot(1024,day=None))

    def test_refuse_false_readonly_claim_and_untrusted_result(self):
        for field in ("database_transaction_read_only", "indicator_writes_performed",
                      "automatic_write_schedule_activated",
                      "candidate_selection_tested_against_real_sql"):
            bad=snapshot()
            bad[field]=not bad[field]
            with self.assertRaisesRegex(ValueError,"read-only"):
                reconcile(bad,snapshot(1024))

    def test_refuse_malformed_duplicate_or_negative_market_counters(self):
        for field,value in (("pending",-1),("eligible",0),("unstarted",5000),
                            ("preview_candidate_count",100)):
            bad=snapshot()
            bad["markets"][0][field]=value
            with self.assertRaises(ValueError):
                reconcile(bad,snapshot(1024))
        bad=snapshot()
        bad["markets"][1]["market"]="twse"
        with self.assertRaisesRegex(ValueError,"duplicate"):
            reconcile(bad,snapshot(1024))

    def test_refuse_missing_market(self):
        bad=snapshot()
        bad["markets"].pop()
        with self.assertRaisesRegex(ValueError,"Both TWSE and TPEx"):
            reconcile(bad,snapshot(1024))


if __name__ == "__main__":
    unittest.main()
