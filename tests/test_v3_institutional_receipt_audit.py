"""Offline summary receipt consistency tests."""
import copy
import unittest
from scripts.v3_institutional_receipt_audit import audit_receipt, audit_private_structure, audit_factor_integrity


class InstitutionalReceiptAuditTests(unittest.TestCase):
    def receipt(self):
        return {"summary":dict(scope="OWNER_V3_TWSE_INSTITUTIONAL_HISTORY_EXPANSION",
            verified_source_dates=30,remaining_source_dates=889,required_unique_source_dates=919,
            signal_windows=2,target_signal_windows=48,remaining_signal_windows=46,calendar_ready_windows=48,
            completed_signal_dates=["2024-01-31","2024-02-29"],
            reports=[dict(signal_date="2024-01-31",candidate_rows=100,complete_factor_candidates=95,
                          zero_institutional_turnover=0,coverage_pct=95.),
                     dict(signal_date="2024-02-29",candidate_rows=50,complete_factor_candidates=40,
                          zero_institutional_turnover=0,coverage_pct=80.)],
            candidate_factor_rows=135,factor_sha256="a"*64,full_expansion_complete=False,
            production_neon_reads=0,production_neon_writes=0,line_messages_sent=0,
            approved_training_feature_rows=0,v3_model_trained=False,model_release="BLOCKED",
            paid_upgrade_requested=False,offline_replay_pass=True,original_pilot_replay_pass=True,
            historical_publication_time_verified=False,immutable_historical_vintage_verified=False)}

    def test_weighted_counts_and_missing_prioritization(self):
        r=audit_receipt(self.receipt())
        self.assertEqual(r["candidate_rows"],150)
        self.assertEqual(r["missing_factor_candidates"],15)
        self.assertEqual(r["weighted_coverage_pct"],90.)
        self.assertEqual(r["highest_missing_windows"][0]["signal_date"],"2024-02-29")
        self.assertFalse(r["underlying_digest_recomputed"])
        self.assertEqual(r["approved_training_feature_rows"],0)

    def test_count_or_coverage_mismatch_rejected(self):
        for key,value in (("remaining_source_dates",0),("candidate_factor_rows",136),
                          ("full_expansion_complete",True),("approved_training_feature_rows",1)):
            a=self.receipt()
            a["summary"][key]=value
            with self.assertRaises(ValueError):
                audit_receipt(a)
        a=self.receipt()
        a["summary"]["reports"][0]["coverage_pct"]=100.
        with self.assertRaises(ValueError):
            audit_receipt(a)

    def test_production_flags_and_dates_rejected(self):
        a=self.receipt()
        a["summary"]["production_neon_writes"]=1
        with self.assertRaises(ValueError):
            audit_receipt(a)
        a=self.receipt()
        a["summary"]["reports"].reverse()
        with self.assertRaises(ValueError):
            audit_receipt(a)

    def test_private_structure_aggregates_only_and_rejects_wrong_counts(self):
        a=self.receipt()
        a["private_candidate_factors"]=[{"score":1,"private_value":"NOT_FOR_OUTPUT"} for _ in range(135)]
        a["private_candidate_factors"][0]["score"]=None
        a["source_receipts"]=[{"date":"2024-01-01"} for _ in range(30)]
        r=audit_private_structure(a)
        self.assertTrue(r["private_payload_counts_consistent"])
        self.assertNotIn("NOT_FOR_OUTPUT",str(r))
        self.assertEqual(r["private_candidate_structure"]["fields"][1],
                         {"name":"score","present":135,"null":1,"types":["NoneType","int"]})
        a["source_receipts"].pop()
        with self.assertRaises(ValueError):
            audit_private_structure(a)

    def test_provenance_declaration_not_independent_verification(self):
        a=self.receipt()
        a["summary"]["historical_publication_time_verified"]=True
        a["summary"]["immutable_historical_vintage_verified"]=True
        r=audit_receipt(a)
        self.assertFalse(r["source_provenance_verified"])
        self.assertEqual(r["model_release"],"BLOCKED")


    def integrity_fixture(self):
        from datetime import date,timedelta
        a=self.receipt()
        days=[(date(2024,1,1)+timedelta(days=i)).isoformat() for i in range(30)]
        a["source_receipts"]=[dict(date=d,source="TWSE",params={},response_sha256="a"*64,
                                   captured_at_utc="2026-11-26T00:00:00Z") for d in days]
        a["private_candidate_factors"]=[
            dict(signal_date=r["signal_date"],stock_id=str(2300+i),market="TWSE",
                 historical_reconstruction_only=True,strict_point_in_time_verified=False,
                 approved_training_feature=False,source_dates=days[-20:],
                 institutional_net_shares_20=20,institutional_turnover_shares_20=100,
                 institutional_imbalance_20=.2)
            for r in a["summary"]["reports"] for i in range(r["complete_factor_candidates"])]
        import hashlib,json
        a["summary"]["factor_sha256"]=hashlib.sha256(json.dumps(
            a["private_candidate_factors"],sort_keys=True,separators=(",",":"),
            ensure_ascii=True,allow_nan=False).encode("utf-8")).hexdigest()
        return a

    def test_private_integrity_pass_not_training_approval(self):
        r=audit_factor_integrity(self.integrity_fixture())
        self.assertEqual(r["private_integrity_status"],"STRUCTURE_CHECKS_PASS")
        self.assertEqual(r["unique_stock_signal_keys"],135)
        self.assertTrue(r["declared_factor_digest_matches"])
        self.assertTrue(r["underlying_digest_recomputed"])
        self.assertEqual(r["post_signal_capture_date_rows"],135)
        self.assertEqual(r["net_over_turnover_hypothesis_mismatch_rows"],0)
        self.assertEqual(r["approved_training_feature_rows"],0)
        self.assertFalse(r["original_producer_digest_recipe_verified"])

    def test_private_integrity_anomalies_visible(self):
        a=self.integrity_fixture()
        a["private_candidate_factors"][0]["stock_id"]="1589"
        a["private_candidate_factors"][1]["source_dates"][-1]="2024-02-01"
        a["private_candidate_factors"][2]["institutional_imbalance_20"]=.5
        a["private_candidate_factors"][3]["approved_training_feature"]=True
        r=audit_factor_integrity(a)
        self.assertEqual(r["private_integrity_status"],"INTEGRITY_REVIEW_REQUIRED")
        self.assertEqual(r["anomaly_counts"]["invalid_or_excluded_stock"],1)
        self.assertEqual(r["excluded_stock_reason_counts"],{"1589":1})
        self.assertEqual(r["stock_format_and_exclusion_screen_rows"],134)
        self.assertFalse(r["declared_factor_digest_matches"])
        self.assertEqual(r["anomaly_counts"]["source_not_strictly_before_signal"],1)
        self.assertEqual(r["anomaly_counts"]["missing_source_receipt"],1)
        self.assertEqual(r["anomaly_counts"]["unexpected_training_flag"],1)
        self.assertEqual(r["net_over_turnover_hypothesis_mismatch_rows"],1)


if __name__=="__main__":
    unittest.main()
