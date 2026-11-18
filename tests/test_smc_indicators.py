import unittest
from src.smc_indicators import compute_smc

def bars(closes, opens=None, highs=None, lows=None):
    rows=[]
    opens=opens or closes
    highs=highs or [x+1 for x in closes]
    lows=lows or [x-1 for x in closes]
    for i,c in enumerate(closes):
        rows.append({"market":"twse","stock_id":"2330","trade_date":f"2026-01-{i+1:02d}",
                     "open":opens[i],"high":highs[i],"low":lows[i],"close":c})
    return rows

class SMCTests(unittest.TestCase):
    def test_empty_and_order_validation(self):
        self.assertEqual(compute_smc([]),[])
        data=bars([10,11,12]); data[2]["trade_date"]=data[1]["trade_date"]
        with self.assertRaises(ValueError): compute_smc(data)

    def test_confirmed_swing_is_reported_after_right_bars(self):
        data=bars([10,11,15,12,11,12,13,12], highs=[11,12,16,13,12,13,14,13])
        result=compute_smc(data,swing_left=1,swing_right=1)
        self.assertIsNone(result[2]["swing_high"])
        self.assertEqual(result[3]["swing_high"],16)

    def test_fvg_detection(self):
        data=bars([10,11,14], highs=[11,12,15], lows=[9,10,13])
        result=compute_smc(data)
        self.assertEqual(result[2]["fvg_type"],"bullish")
        self.assertEqual(result[2]["fvg_low"],11)

    def test_sweep_high_detection(self):
        data=bars([10,11,10,11,10,10], highs=[11,12,11,13,11,11],
                  lows=[9,10,9,10,9,9])
        result=compute_smc(data,swing_left=1,swing_right=1)
        self.assertTrue(result[3]["liquidity_sweep_high"])

if __name__=="__main__": unittest.main()
