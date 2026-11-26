"""Regression tests for exact-key retrospective factor integration."""
import unittest
from src.v3_retrospective_factor_join import join_reconstructed_factors,join_monthly_panel,_digest
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


    def panel_inputs(self):
        a=self.inputs()
        rows=[dict(market=market,stock_id=stock,signal_date="2024-04-30",
                   feature_vector=[.1]*12,prefix_source_rows=240,prefix_source_sha256="a"*64)
              for market,stock in (("twse","2330"),("twse","1808"),("tpex","2330"))]
        markets={m:dict(accepted_feature_rows=n,prefix_only_features=True,
                       approved_total_return_labels=0,model_release="BLOCKED")
                 for m,n in (("twse",2),("tpex",1))}
        panel=dict(summary=dict(total_feature_rows=3,total_feature_values=36,
                         model_release="BLOCKED",approved_total_return_labels=0,
                         production_neon_writes=0,line_messages_sent=0,
                         historical_pit_roster_verified=False,corporate_action_coverage_verified=False,
                         feature_panel_sha256=_digest(rows),market_summaries=markets),
                   private_feature_rows=rows)
        return dict(screened=a["screened"],panel=panel)

    def test_panel_join_does_not_cross_market_and_excludes_known_code(self):
        r=join_monthly_panel(**self.panel_inputs())
        self.assertEqual(r["summary"]["matched_rows"],1)
        self.assertEqual(r["summary"]["monthly_panel_market_counts"],{"twse":2,"tpex":1})
        self.assertEqual(r["summary"]["monthly_panel_excluded_codes"],{"1808":1})
        self.assertTrue(r["summary"]["monthly_panel_digest_matches"])
        self.assertFalse(r["summary"]["original_producer_feature_order_verified"])
        self.assertEqual(r["summary"]["approved_training_feature_rows"],0)

    def test_panel_digest_and_prefix_constraints(self):
        a=self.panel_inputs()
        a["panel"]["private_feature_rows"][0]["feature_vector"][0]=.2
        with self.assertRaises(ValueError):
            join_monthly_panel(**a)
        a=self.panel_inputs()
        rows=a["panel"]["private_feature_rows"]
        rows[0]["prefix_source_rows"]=239
        a["panel"]["summary"]["feature_panel_sha256"]=_digest(rows)
        with self.assertRaises(ValueError):
            join_monthly_panel(**a)


if __name__=="__main__":
    unittest.main()
