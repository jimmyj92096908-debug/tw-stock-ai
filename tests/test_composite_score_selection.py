"""Regression checks: scoring cannot be restricted to four sample codes."""
import unittest
from datetime import date
from unittest.mock import patch

from src.composite_score import (
    SCORABLE_STOCKS_SQL, LATEST_VALID_TECH_SQL, calculate_all,
)


class FakeCursor:
    def __init__(self, data=True):
        self.data=data
        self.sql=""
        self.params=None
        self.inserted=[]
        self.chip_dates=[]

    def __enter__(self):
        return self

    def __exit__(self,*_args):
        return False

    def execute(self,sql,params=None):
        self.sql=sql
        self.params=params
        if sql.lstrip().startswith("INSERT INTO daily_composite_scores"):
            self.inserted.append(params)
        if "FROM daily_chip_scores" in sql:
            self.chip_dates.append(params)

    def fetchall(self):
        if self.sql == SCORABLE_STOCKS_SQL:
            return [("twse","2330"),("tpex","6488")]
        raise AssertionError("Unexpected fetchall query")

    def fetchone(self):
        if self.sql == LATEST_VALID_TECH_SQL:
            if not self.data:
                return (date(2026,11,19),1400,*([None]*11),None)
            return (
                date(2026,11,19),1400,1390,1380,1375,1370,1350,
                1300,1280,1200,1100,60,1000,800
            )
        if "FROM daily_smc" in self.sql:
            if not self.data:
                return None
            return (1,True,False,False,False,False,False,"bullish","bullish")
        if "FROM daily_chip_scores" in self.sql:
            return None
        raise AssertionError("Unexpected fetchone query")


class FakeDB:
    def __init__(self,data=True):
        self.cur=FakeCursor(data)

    def __enter__(self):
        return self

    def __exit__(self,*_args):
        return False

    def cursor(self):
        return self.cur


class CompositeSelectionTests(unittest.TestCase):
    def test_query_is_data_driven_and_no_hardcoded_four_tickers(self):
        self.assertIn("JOIN daily_prices p",SCORABLE_STOCKS_SQL)
        self.assertIn("p.close IS NOT NULL",SCORABLE_STOCKS_SQL)
        self.assertNotIn("6213",SCORABLE_STOCKS_SQL)
        self.assertNotIn("7827",SCORABLE_STOCKS_SQL)
        self.assertIn("JOIN daily_technicals t",LATEST_VALID_TECH_SQL)
        self.assertIn("p.trade_date DESC",LATEST_VALID_TECH_SQL)

    def test_2330_and_6488_are_scored_when_indicators_exist(self):
        fake=FakeDB()
        with patch("src.composite_score.psycopg.connect",return_value=fake):
            count=calculate_all("postgresql://mock-not-real/db")
        self.assertEqual(count,2)
        self.assertEqual(len(fake.cur.inserted),2)
        self.assertEqual({(row[0],row[1]) for row in fake.cur.inserted},
                         {("twse","2330"),("tpex","6488")})
        for row in fake.cur.inserted:
            self.assertEqual(row[2],date(2026,11,19))
            self.assertIsNotNone(row[3])
            self.assertGreaterEqual(row[4],0.5)
        self.assertEqual(fake.cur.chip_dates,[
            ("twse","2330",date(2026,11,19)),
            ("tpex","6488",date(2026,11,19))
        ])

    def test_insufficient_factors_are_not_written_as_a_score(self):
        fake=FakeDB(data=False)
        with patch("src.composite_score.psycopg.connect",return_value=fake):
            count=calculate_all("postgresql://mock-not-real/db")
        self.assertEqual(count,0)
        self.assertEqual(fake.cur.inserted,[])


if __name__=="__main__":
    unittest.main()
