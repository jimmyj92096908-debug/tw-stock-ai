import unittest
from scripts.owner_known_action_event_sensitivity_offline import sensitivity
class EventSensitivityTests(unittest.TestCase):
    def test_combined_entitlement(self):
        r=sensitivity(["100"]*5+["90"],"1.6","1.1")
        self.assertEqual(r["raw_gross"],"-0.100000000000")
        self.assertEqual(r["event_only_gross"],"0.006000000000")
        self.assertEqual(r["event_only_delta"],"0.106000000000")
    def test_entry_excluded_and_cash(self):
        self.assertEqual(sensitivity(["100"]*6,"0","1")["event_only_delta"],"0.000000000000")
        self.assertEqual(sensitivity(["100"]*6,"1","1")["event_only_delta"],"0.010000000000")
        with self.assertRaises(ValueError):sensitivity(["100"]*5,"1","1")
        with self.assertRaises(ValueError):sensitivity(["0"]*6,"1","1")
