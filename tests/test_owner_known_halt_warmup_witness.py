from datetime import date,timedelta
from unittest import TestCase
from unittest.mock import patch
from scripts import owner_known_halt_warmup_witness as m

class HaltWitnessTests(TestCase):
    def fixture(self):
        market={k:[] for k in m.MONTHS}
        d=date(2024,7,1)
        while d<=date(2026,8,31):
            if d.weekday()<5:market[d.isoformat()[:7]].append(d.isoformat())
            d+=timedelta(days=1)
        rows=[{"stock_id":sid,"trade_date":date.fromisoformat(d)}
              for sid in ("1101","1231") for days in market.values() for d in days
              if not(sid=="1101" and d==m.HALT)]
        return market,rows,[{"signal_date":"2025-08-29","stock_id":"1231"}]
    def test_exact_halt_only(self):
        market,rows,features=self.fixture()
        with patch.object(m,"SIGNALS",("2025-08-29",)):
            result=m.verify(["1101","1231"],features,rows,market)
            self.assertEqual(result[0]["required_actual_sessions"],240)
            self.assertEqual(len(result),1)
            rows=[r for r in rows if not(r["stock_id"]=="1101" and r["trade_date"]==date(2025,8,15))]
            with self.assertRaises(ValueError):m.verify(["1101","1231"],features,rows,market)
    def test_partial_calendar_not_accepted(self):
        market,rows,features=self.fixture()
        del market["2025-08"]
        with self.assertRaises(ValueError):m.verify(["1101","1231"],features,rows,market)
