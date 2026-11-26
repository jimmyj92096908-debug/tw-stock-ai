"""Regression tests for exact-key retrospective factor integration."""
import unittest
from src.v3_retrospective_factor_join import join_reconstructed_factors,_digest
from src.raw_factor_feature_bridge import FEATURE_NAMES,VERSION


class RetrospectiveJoinTests(unittest.TestCase):
    def inputs(self):
        rows=[dict(market="TWSE",stock_id=s,signal_date="2024-04-30",
                   institutional_net_shares_20=20,institutional_turnover_shares_20=100,
                   institutional_imbalance_20=.2,historical_reconstruction_only=True,
                   strict_point_in_time_verified=False,approved_training_feature=False)
              for s in ("2330","2317")]
        screened=dict(summary=dict(scope="V3_TWSE_RETROSPECTIVE_SCREENED_RESEARCH_ONLY",
                      model_release="BLOCKED",approved_training_feature_rows=0,
                      source_expansion_complete=True,screened_factor_rows=2,
                      screened_factor_sha256=_digest(rows)),retrospective_research_factors=rows)
        report=dict(feature_version=VERSION,feature_names=list(FEATURE_NAMES),
                    research_use_only=True,live_trading_approved=False,
                    source_capture_vintage_at_old_signals_independently_proven=False,
                    corporate_actions_not_applied_to_features=True,
                    included_signals=1,market="twse",stock_id="2330",requested_cutoff="2024-04-30",
                    signals=[dict(market="twse",stock_id="2330",as_of_date="2024-04-30",
                                  label_or_forward_price_observed=False,
                                  feature_vector=[.1]*len(FEATURE_NAMES))])
        return dict(screened=screened,raw_reports=[report])

    def test_exact_join_and_unmatched_counts(self):
        r=join_reconstructed_factors(**self.inputs())
        self.assertEqual(r["summary"]["matched_rows"],1)
        self.assertEqual(r["summary"]["institutional_only_rows"],1)
        self.assertEqual(len(r["retrospective_joined_factors"][0]["features"]),15)
        self.assertEqual(r["summary"]["approved_training_feature_rows"],0)
        self.assertEqual(r["summary"]["model_release"],"BLOCKED")

    def test_no_date_substitution_or_imputation(self):
        a=self.inputs()
        a["raw_reports"][0]["signals"][0]["as_of_date"]="2024-04-29"
        r=join_reconstructed_factors(**a)
        self.assertEqual(r["summary"]["matched_rows"],0)
        self.assertEqual(r["summary"]["technical_only_rows"],1)
        self.assertEqual(r["summary"]["institutional_only_rows"],2)

    def test_mutated_digest_or_duplicate_technical_key_blocks(self):
        a=self.inputs()
        a["screened"]["retrospective_research_factors"][0]["institutional_imbalance_20"]=.3
        with self.assertRaises(ValueError):
            join_reconstructed_factors(**a)
        a=self.inputs()
        a["raw_reports"]*=2
        with self.assertRaises(ValueError):
            join_reconstructed_factors(**a)

    def test_mismatched_stock_and_future_cutoff_block(self):
        a=self.inputs()
        a["raw_reports"][0]["signals"][0]["stock_id"]="2317"
        with self.assertRaises(ValueError):
            join_reconstructed_factors(**a)
        a=self.inputs()
        a["raw_reports"][0]["requested_cutoff"]="2024-04-29"
        with self.assertRaises(ValueError):
            join_reconstructed_factors(**a)


if __name__=="__main__":
    unittest.main()
