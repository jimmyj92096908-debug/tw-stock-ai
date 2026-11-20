"""Model output safety tests independent of evaluation labels."""
import unittest
from datetime import date
from src.factor_model import ranking, LATEST_RANKING_SQL


def stock(code, score, date_value=date(2026,11,19),coverage=.6,close=100):
    return {"market":"twse","stock_id":code,"stock_name":"test",
            "as_of_date":date_value,"total_score":score,
            "coverage_weight":coverage,"close":close}


class RankingModelTests(unittest.TestCase):
    def test_rankings_are_deterministic_and_bounded(self):
        rows=[stock("2330",70),stock("6213",85),stock("4919",85)]
        a=ranking(rows,limit=2)
        b=ranking(list(reversed(rows)),limit=2)
        self.assertEqual(a,b)
        self.assertEqual([x["stock_id"] for x in a["ranked"]],["4919","6213"])
        self.assertEqual(a["signal_date"],"2026-11-19")
        self.assertTrue(a["not_a_trading_signal"])

    def test_rejects_invalid_and_excluded(self):
        rows=[stock("1808",99),stock("2330",80,coverage=.1),
              stock("6213",77,close=-1),stock("4919",60)]
        output=ranking(rows)
        self.assertEqual(output["eligible_universe"],1)
        self.assertEqual(output["ranked"][0]["stock_id"],"4919")

    def test_does_not_mix_dates(self):
        with self.assertRaisesRegex(ValueError,"cross-date"):
            ranking([stock("2330",70),stock("6213",80,date(2026,11,18))])

    def test_does_not_count_duplicate_rows(self):
        self.assertEqual(ranking([stock("2330",70),stock("2330",70)])["eligible_universe"],1)

    def test_invalid_limit(self):
        for limit in (0,101,-1,True,2.5):
            with self.assertRaises(ValueError):
                ranking([],limit=limit)

    def test_sql_only_same_day_matched_price_and_filtered_stock(self):
        self.assertIn("p.trade_date=s.as_of_date",LATEST_RANKING_SQL)
        self.assertIn("s.coverage_weight >= %s",LATEST_RANKING_SQL)
        self.assertIn("s.stock_id <> '1808'",LATEST_RANKING_SQL)
        self.assertNotIn("UPDATE ",LATEST_RANKING_SQL)
        self.assertNotIn("INSERT ",LATEST_RANKING_SQL)


if __name__=="__main__":
    unittest.main()
