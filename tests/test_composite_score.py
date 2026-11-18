import unittest
from src.composite_score import technical_score, smc_score, combine_scores

class CompositeScoreTests(unittest.TestCase):
    def test_technical_score_requires_price_and_ma(self):
        self.assertIsNone(technical_score({"close":10})[0])
        self.assertIsNone(technical_score(None)[0])

    def test_technical_score_is_bounded(self):
        row={"close":12,"ma5":10,"ma10":11,"ma13":9,"ma20":8,"ma34":7,
             "ma55":6,"ma60":5,"ma120":4,"ma240":3,"rsi14":55,
             "volume_ma5":120,"volume_ma20":100}
        score,status=technical_score(row)
        self.assertGreaterEqual(score,0); self.assertLessEqual(score,100)
        self.assertEqual(status["ma_count"],9)

    def test_smc_bullish_and_bearish(self):
        bullish={"trend_direction":1,"bos_bullish":True,"liquidity_sweep_low":True,"order_block_type":"bullish","fvg_type":"bullish"}
        bearish={"trend_direction":-1,"bos_bearish":True,"liquidity_sweep_high":True,"order_block_type":"bearish","fvg_type":"bearish"}
        self.assertGreater(smc_score(bullish)[0],50)
        self.assertLess(smc_score(bearish)[0],50)

    def test_coverage_gates_publishable_score(self):
        score,cov=combine_scores({"technical":70,"smc":60,"chip":None})
        self.assertIsNone(score); self.assertEqual(cov,0.60)
        score,cov=combine_scores({"technical":70,"smc":None,"chip":None})
        self.assertIsNone(score); self.assertEqual(cov,0.35)

    def test_full_coverage(self):
        score,cov=combine_scores({"technical":70,"smc":60,"chip":80})
        self.assertIsNotNone(score); self.assertEqual(cov,1.0)

if __name__=="__main__": unittest.main()
