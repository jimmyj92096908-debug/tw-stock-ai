from datetime import date
from five_year_backfill import five_year_start, select_incomplete


def test_five_year_start_handles_leap_day():
    assert five_year_start(date(2024,2,29)) == date(2019,2,1)


def test_selects_missing_data_first_and_uses_market_filter():
    universe=[
      {"market":"上市","stock_id":"2330","stock_name":"台積電"},
      {"market":"上櫃","stock_id":"6488","stock_name":"環球晶"},
      {"market":"上市","stock_id":"9999","stock_name":"新股"},
    ]
    coverage={("twse","2330"):date(2021,1,4),("tpex","6488"):date(2024,1,1)}
    completed={("twse","2330")}
    selected=select_incomplete(universe,coverage,completed)
    assert [r["stock_id"] for r in selected]==["9999","6488"]
    assert [r["stock_id"] for r in select_incomplete(universe,coverage,completed,"tpex")]==["6488"]


def test_successfully_completed_backfill_is_excluded():
    universe=[{"market":"上市","stock_id":"2330","stock_name":"台積電"}]
    assert select_incomplete(universe,{}, {("twse","2330")})==[]

def test_skips_stocks_already_covering_target_start():
    universe=[
      {"market":"上市","stock_id":"2330","stock_name":"台積電"},
      {"market":"上櫃","stock_id":"6488","stock_name":"環球晶"},
    ]
    coverage={("twse","2330"):date(2020,1,1),("tpex","6488"):date(2024,1,1)}
    selected=select_incomplete(universe,coverage,set(),start_date=date(2021,11,1))
    assert [r["stock_id"] for r in selected]==["6488"]
