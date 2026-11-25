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

    def test_json_list_is_normalized_for_real_cache_queue(self):
        stocks=["1101","1231","1301","2330","2881"]
        features=[{} for _ in range(228)]
        payload={"sample_stock_ids":stocks,"private_feature_rows":features}
        b=m.r.b
        argv=["halt","--monthly","panel.json","--price-cache","prices",
              "--calendar-cache","calendar","--out","out.json"]
        def cache_probe(actual_stocks,directory):
            self.assertIs(type(actual_stocks),tuple)
            self.assertEqual(actual_stocks,tuple(stocks))
            self.assertEqual(len(b.five.queue_for(actual_stocks,2025,3)),15)
            return [],m.r.LATE_HASH
        with patch("sys.argv",argv), patch.object(b.m,"private_path",return_value="panel.json"), \
             patch.object(b.m,"read_panel",return_value=(payload,"hash")), \
             patch.object(b,"SAMPLE_HASH",b.m.fingerprint(stocks)), \
             patch.object(m.r,"FEATURE_HASH",b.m.fingerprint(features)), \
             patch.object(b,"load_late",side_effect=cache_probe) as loader, \
             patch.object(b.c,"private_dir",side_effect=ValueError("test stop")):
            with self.assertRaisesRegex(SystemExit,"halt_stage=PRIVATE_PATHS"):
                m.main()
            loader.assert_called_once_with(tuple(stocks),"prices")
