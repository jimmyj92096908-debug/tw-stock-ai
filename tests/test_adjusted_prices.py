from adjusted_prices import adjust_bars
import pytest

def bars():
 return [
  {"market":"twse","stock_id":"2330","trade_date":"2024-01-01","open":100,"high":110,"low":90,"close":100,"volume":1000,"turnover":100000,"price_change":0,"transactions":10},
  {"market":"twse","stock_id":"2330","trade_date":"2024-01-02","open":50,"high":55,"low":45,"close":50,"volume":2000,"turnover":100000,"price_change":-50,"transactions":20},
 ]
def test_split_adjusts_only_pre_ex_date_bars():
 out=adjust_bars(bars(),[{"ex_date":"2024-01-02","price_factor":0.5,"share_factor":2}])
 assert out[0]["close"]==50 and out[0]["volume"]==2000
 assert out[1]["close"]==50 and out[1]["volume"]==2000
 assert out[0]["adjustment_status"]=="ADJUSTED"
 assert out[1]["adjustment_status"]=="UNADJUSTED"
def test_cash_dividend_adjusts_price_not_shares():
 out=adjust_bars(bars(),[{"ex_date":"2024-01-02","price_factor":0.98,"share_factor":1}])
 assert out[0]["close"]==pytest.approx(98)
 assert out[0]["volume"]==1000
def test_multiple_events_compound():
 out=adjust_bars(bars(),[
  {"ex_date":"2024-01-02","price_factor":0.5,"share_factor":2},
  {"ex_date":"2024-01-03","price_factor":0.9,"share_factor":1.1},
 ])
 assert out[0]["close"]==pytest.approx(45)
 assert out[0]["volume"]==pytest.approx(2200)
def test_invalid_factor_rejected():
 with pytest.raises(ValueError):
  adjust_bars(bars(),[{"ex_date":"2024-01-02","price_factor":0,"share_factor":1}])

def test_duplicate_identical_events_are_applied_once():
 event={"ex_date":"2024-01-02","action_type":"CASH_DIVIDEND","price_factor":0.98,"share_factor":1.0,"cash_amount":1.0}
 out=adjust_bars(bars(),[event,{**event,"source_event_id":"duplicate-row"}])
 assert out[0]["close"]==pytest.approx(98)
 assert out[0]["price_adjustment_factor"]==pytest.approx(0.98)

def test_distinct_same_day_events_still_compound():
 out=adjust_bars(bars(),[
  {"ex_date":"2024-01-02","action_type":"CASH_DIVIDEND","price_factor":0.98,"share_factor":1},
  {"ex_date":"2024-01-02","action_type":"STOCK_DIVIDEND","price_factor":0.95,"share_factor":1.05},
 ])
 assert out[0]["close"]==pytest.approx(100*0.98*0.95)
 assert out[0]["volume"]==pytest.approx(1000*1.05)
