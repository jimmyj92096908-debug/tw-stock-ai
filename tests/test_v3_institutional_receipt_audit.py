"""Offline summary receipt consistency tests."""
import copy
import unittest
from scripts.v3_institutional_receipt_audit import audit_receipt, audit_private_structure


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


if __name__=="__main__":
    unittest.main()
