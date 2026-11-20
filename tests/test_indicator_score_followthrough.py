"""Offline contracts for live indicator-to-composite score acceptance."""
import unittest

from scripts.indicator_score_followthrough import assess


def audit(valid, latest, date="2026-11-19", score_date=None):
    return {
        "latest": {
            "latest_price_date":date,
            "latest_score_date":score_date if score_date is not None else date,
        },
        "analysis_readiness":{
            "scored_stocks":valid,
            "scored_latest_price_day":latest,
        }
    }

def proof(delta=20, date="2026-11-19"):
    return {
        "progress_verified":True,
        "schema_version":1,
        "live_trade_signals_enabled":False,
        "price_date":date,
        "markets":[
            {"market":"twse","decrease_in_pending":delta},
            {"market":"tpex","decrease_in_pending":0}
        ]
    }

class ScoreFollowThroughTests(unittest.TestCase):
    def test_composite_score_increases_after_verified_indicators(self):
        result=assess(audit(166,155),audit(186,175),proof())
        self.assertEqual(result["valid_scored_added"],20)
        self.assertEqual(result["indicator_stocks_newly_completed"],20)
        self.assertTrue(result["no_trade_signals_approved"])

    def test_missing_indicator_proof_rejected(self):
        bad=proof()
        bad["progress_verified"]=False
        with self.assertRaisesRegex(ValueError,"verified indicator"):
            assess(audit(166,155),audit(186,175),bad)
        bad=proof()
        bad["live_trade_signals_enabled"]=True
        with self.assertRaisesRegex(ValueError,"verified indicator"):
            assess(audit(166,155),audit(186,175),bad)

    def test_no_score_increase_is_not_success(self):
        for after in (audit(166,155),audit(166,175),audit(186,155)):
            with self.assertRaisesRegex(ValueError,"did not increase"):
                assess(audit(166,155),after,proof())

    def test_date_and_newest_score_must_match_prices(self):
        with self.assertRaisesRegex(ValueError,"Daily price date"):
            assess(audit(166,155),audit(186,175,date="2026-11-20"),proof())
        bad=audit(186,175)
        bad["latest"]["latest_score_date"]="2026-11-18"
        with self.assertRaisesRegex(ValueError,"stale"):
            assess(audit(166,155),bad,proof())

    def test_decreased_score_coverage_never_accepted(self):
        for after in (audit(165,155),audit(166,154)):
            with self.assertRaisesRegex(ValueError,"decreased"):
                assess(audit(166,155),after,proof())

    def test_no_work_is_idempotent(self):
        result=assess(audit(166,155),audit(166,155),proof(delta=0))
        self.assertEqual(result["valid_scored_added"],0)
        self.assertTrue(result["completed_indicator_to_score_research_pipeline"])

if __name__=="__main__":
    unittest.main()
