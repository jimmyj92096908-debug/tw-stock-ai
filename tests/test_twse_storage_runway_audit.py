"""Read-only storage runway assertions, no source fetch/DB/LINE."""
from unittest import TestCase

from scripts.twse_storage_runway_audit import audit


def evidence(*, before_bytes=632_750_080, after_bytes=662_331_392,
             first_days=550, end_days=656, bars=105_000):
    return {
        "baseline": {"database_bytes": before_bytes, "source_days": first_days},
        "latest": {"database_bytes": after_bytes, "source_days": end_days},
        "batches": [{"new_valid_bars": bars}],
    }


class OfficialStorageRunwayTests(TestCase):
    def test_realistic_capacity_warns_but_never_writes(self):
        report = audit(evidence(), missing_weekdays=601)
        self.assertEqual(report["new_verified_official_source_days"], 106)
        self.assertEqual(report["existing_protected_campaign_start_ceiling_bytes"],
                         742_800_000)
        self.assertTrue(report["illustrative_runway_short_of_outstanding_weekdays"])
        self.assertEqual(report["adaptive_one_day_capacity_ceiling_bytes"],
                         749_100_000)
        self.assertEqual(report["preserved_neon_maintenance_margin_bytes"],
                         50_000_000)
        self.assertGreater(report["adaptive_remaining_bytes"],
                           report["protected_remaining_bytes"])
        self.assertGreaterEqual(
            report["illustrative_adaptive_additional_verified_source_days"],
            report["illustrative_additional_verified_source_days"])
        self.assertGreater(report["illustrative_additional_verified_source_days"], 0)
        self.assertFalse(report["five_year_storage_feasibility_proven"])
        self.assertFalse(report["historical_source_data_modified"])
        self.assertFalse(report["derived_data_written"])
        self.assertFalse(report["line_messages_sent"])
        self.assertFalse(report["live_trading_approved"])
        self.assertFalse(report["paid_upgrade_requested"])

    def test_does_not_invent_growth_when_no_measurable_sessions(self):
        estimate = audit(evidence(after_bytes=632_750_080, end_days=550),
                         missing_weekdays=601)
        self.assertIsNone(estimate["illustrative_additional_verified_source_days"])
        self.assertIsNone(estimate["illustrative_adaptive_additional_verified_source_days"])
        self.assertIsNone(estimate["illustrative_runway_short_of_outstanding_weekdays"])
        estimate = audit(evidence(after_bytes=625_000_000))
        self.assertIsNone(estimate["estimated_bytes_per_new_verified_day"])

    def test_rejects_unsupported_or_negative_evidence(self):
        for bad in (-1, True, 3.1, "601"):
            with self.assertRaises(ValueError):
                audit(evidence(), missing_weekdays=bad)
        with self.assertRaisesRegex(ValueError, "regressed"):
            audit(evidence(end_days=549))
        with self.assertRaises(ValueError):
            audit(evidence(bars=-1))
        with self.assertRaises(ValueError):
            audit({"baseline": {}, "latest": {}, "batches": []})
