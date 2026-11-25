import json
import unittest
from scripts import owner_twse_market_session_window_witness as m

class CalendarWitnessTests(unittest.TestCase):
    def body(self,days):
        return json.dumps({"stat":"OK","fields":list(m.FIELDS),
            "data":[[d,"1,000","2,000","3","100.0","+1"] for d in days]}).encode()
    def test_month_contract(self):
        self.assertEqual(m.parse(self.body(["112/01/03","112/01/04"]),"2023-01"),
                         ["2023-01-03","2023-01-04"])
        for days in (["112/02/01"],["112/01/07"],["112/01/03","112/01/03"]):
            with self.assertRaises(ValueError):m.parse(self.body(days),"2023-01")
    def test_missing_month_and_missing_session(self):
        days=["2023-01-03","2023-01-04","2023-01-05","2023-01-06","2023-01-09","2023-01-10"]
        paths=[{"signal_date":"2022-12-30","sessions":days}]
        self.assertEqual(m.compare(paths,{"2023-01":days})["windows_pending"],1)
        market={"2022-12":["2022-12-30"],"2023-01":days}
        self.assertEqual(m.compare(paths,market)["windows_verified"],1)
        market["2023-01"]=days[1:]
        self.assertEqual(len(m.compare(paths,market)["window_mismatches"]),1)
    def test_signal_must_trade(self):
        paths=[{"signal_date":"2023-01-02","sessions":["2023-01-03"]}]
        self.assertEqual(m.compare(paths,{"2023-01":["2023-01-03"]})["windows_verified"],0)
