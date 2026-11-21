"""Offline conservative capacity guard and schedule order tests."""
import unittest
from pathlib import Path
from scripts.indicator_capacity_guard import assess, STOP_BYTES, RESERVE_BYTES

class IndicatorCapacityGuardTests(unittest.TestCase):
    def test_small_batch_allowed_with_real_headroom(self):
        x=assess(600_000_000,500.0,[1000,1000])
        self.assertTrue(x["allow_apply"])
        self.assertTrue(x["read_only"])
        self.assertEqual(x["candidate_count"],2)

    def test_stress_blocks_before_paid_or_stop_threshold(self):
        x=assess(730_000_000,1000.0,[1200]*20)
        self.assertFalse(x["allow_apply"])
        self.assertLess(x["database_bytes"],STOP_BYTES)
        self.assertEqual(x["maintenance_reserve_bytes"],RESERVE_BYTES)

    def test_bad_inputs_fail_closed(self):
        for bad in ([-1],[1.5],[0]*41):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    assess(610_000_000,300,bad)
        with self.assertRaises(ValueError):
            assess(0,300,[500])
        with self.assertRaises(ValueError):
            assess(610_000_000,0,[500])

    def test_capacity_gate_before_scheduled_apply(self):
        workflow=Path(".github/workflows/daily-indicator-catchup.yml").read_text(
            encoding="utf-8")
        gate=workflow.index("python scripts/indicator_capacity_guard.py")
        write=workflow.index("python src/batch_indicator_catchup.py --apply")
        self.assertLess(gate,write)
        self.assertIn("github.event_name == 'schedule'",workflow)
        self.assertIn("inputs.apply == true",workflow)

if __name__ == "__main__":
    unittest.main()
