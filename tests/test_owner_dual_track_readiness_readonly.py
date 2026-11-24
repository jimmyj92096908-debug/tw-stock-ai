from datetime import date,timedelta
from decimal import Decimal
import unittest
from scripts import owner_dual_track_readiness_readonly as m

class DualTrackTests(unittest.TestCase):
    def test_common_path_no_action_absence_claim(self):
        d=date(2026,9,30)
        days=[d+timedelta(days=x) for x in (1,2,5,6,7,8)]
        cal=[(x,700) for x in days]
        p=Decimal("100")
        prices=[("2330",x,p,p,p,p,100,"TWSE_STOCK_DAY") for x in days]
        r=m.inspect_window(["2330","2317"],d,cal,prices,[],"twse")
        self.assertEqual(r["raw_complete_path_rows"],1)
        self.assertEqual(r["approved_total_return_labels"],0)
        self.assertFalse(r["whole_market_signal_cohort_raw_path_complete"])
        self.assertEqual(r["reasons"]["raw_path_complete_no_stored_action_not_proof_of_absence"],1)
        r=m.inspect_window(["2330"],d,cal,prices,[("2330",2,1)],"twse")
        self.assertEqual(r["reasons"]["raw_path_complete_stored_unverified_action"],1)
        self.assertEqual(r["approved_total_return_labels"],0)

    def test_future_and_duplicates(self):
        r=m.inspect_window(["2330"],m.CUTOFF,[],[],[],"twse")
        self.assertEqual(r["raw_complete_path_rows"],0)
        with self.assertRaises(ValueError):
            m.inspect_window(["2330"],m.CUTOFF,[(m.CUTOFF+timedelta(days=3),700)],[],[],"twse")
        d=date(2026,9,30);x=d+timedelta(days=1);p=Decimal(100)
        row=("2330",x,p,p,p,p,100,"TWSE_STOCK_DAY")
        with self.assertRaises(ValueError):
            m.inspect_window(["2330"],d,[(x,700)],[row,row],[],"twse")

    def test_inventory_sql_allowlist(self):
        for table,day in m.CHIP_TABLES:
            sql=m.inventory_sql(table,day)
            self.assertIn("retrieved_at",sql)
            self.assertNotIn("INSERT",sql.upper())
        with self.assertRaises(ValueError):
            m.inventory_sql("unknown","trade_date")
