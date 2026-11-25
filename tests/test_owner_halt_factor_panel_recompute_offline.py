from datetime import date,timedelta
from unittest import TestCase
from unittest.mock import patch
from scripts import owner_halt_factor_panel_recompute_offline as m

class RecomputeTests(TestCase):
    def fixture(self):
        stocks=("1101","1231","1301","2330","2881")
        dates=[];d=date(2021,11,1)
        while d<=date(2026,11,20):
            if d.weekday()<5:dates.append(d)
            d+=timedelta(days=1)
        groups={s:[{"trade_date":d} for d in dates if not(s==m.h.SID and d.isoformat()==m.h.HALT)] for s in stocks}
        months={d.isoformat()[:7]:d.isoformat() for d in dates if d>=date(2022,12,1)}
        months.update({s[:7]:s for s in m.h.SIGNALS})
        def fake(prefix,*,stock_id,cutoff,signal_dates,market):
            signal=cutoff.isoformat()
            return {"included_signals":1,"raw_last_date":signal,
                "raw_source_fingerprint_sha256":m.b.m.fingerprint([x["trade_date"].isoformat() for x in prefix]),
                "signals":[{"as_of_date":signal,"label_or_forward_price_observed":False,"feature_vector":[1.0]*12}]}
        original=[];proof=[]
        for signal in sorted(months.values()):
            day=date.fromisoformat(signal)
            for sid in stocks:
                prefix=[x for x in groups[sid] if x["trade_date"]<=day]
                if sid==m.h.SID and signal in m.h.SIGNALS:
                    proof.append({"stock_id":sid,"signal_date":signal,
                        "session_sha256":m.b.m.fingerprint([x["trade_date"].isoformat() for x in prefix[-240:]])})
                else:
                    z=fake(prefix,stock_id=sid,cutoff=day,signal_dates=[day],market="twse")
                    original.append({"stock_id":sid,"market":"twse","signal_date":signal,"feature_vector":[1.0]*12,
                        "prefix_source_rows":len(prefix),"prefix_source_sha256":z["raw_source_fingerprint_sha256"]})
        return stocks,original,groups,proof,fake
    def test_exact_replay_and_halt_extension(self):
        s,f,g,p,engine=self.fixture()
        with patch.object(m.r,"FEATURE_HASH",m.b.m.fingerprint(f)),patch.object(m,"build_research_features",side_effect=engine):
            result=m.extend(s,f,g,p)
            self.assertEqual(len(result),240)
            self.assertEqual([x for x in result if not(x["stock_id"]==m.h.SID and x["signal_date"] in m.h.SIGNALS)],f)
            p[0]["session_sha256"]="bad"
            with self.assertRaisesRegex(ValueError,"calendar witness"):m.extend(s,f,g,p)
    def test_prior_row_drift_rejected(self):
        s,f,g,p,engine=self.fixture()
        f[0]["feature_vector"][0]=2.0
        with patch.object(m.r,"FEATURE_HASH",m.b.m.fingerprint(f)),patch.object(m,"build_research_features",side_effect=engine):
            with self.assertRaisesRegex(ValueError,"exact factor replay"):m.extend(s,f,g,p)

    def test_discovery_deduplicates_and_rejects_conflicting_sets(self):
        start=date(2022,1,1);end=date(2023,1,1)
        rows=[{"stock_id":"1101","trade_date":date(2022,1,3),"close":1}]
        with patch.object(m.b.depth,"_private_archives",side_effect=lambda root:[root]), \
             patch.object(m,"header_interval",return_value=(start,date(2022,12,30))), \
             patch.object(m.b.depth,"digest",side_effect=lambda p:"same" if p in ("a","copy") else "other"), \
             patch.object(m.b.early,"archive_bars",return_value=(rows,{date(2022,1,3)})) as replay:
            found,days,paths=m.discover_archive_rows(["a","copy"],("1101",),"unused",start,end,1)
            self.assertEqual(found,rows)
            self.assertEqual(paths,["a"])
            self.assertEqual(replay.call_count,1)
            replay.side_effect=[(rows,days),([dict(rows[0],close=2)],days)]
            with self.assertRaisesRegex(ValueError,"No unique authenticated"):
                m.discover_archive_rows(["a","b"],("1101",),"unused",start,end,1)
