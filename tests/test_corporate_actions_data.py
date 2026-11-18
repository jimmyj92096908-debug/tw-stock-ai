import pytest
from corporate_actions_data import normalize, parse_date, unpack

def test_roc_date():
 assert parse_date("115年11月19日")=="2026-11-19"
def test_cash_dividend_is_auto_verified():
 row={"除權息日期":"115年11月19日","股票代號":"6213","除權息前收盤價":"100","除權息參考價":"98","權/息":"息"}
 item=normalize(row,"twse")
 assert item["verified"] is True
 assert item["action_type"]=="CASH_DIVIDEND"
 assert item["price_factor"]==pytest.approx(.98)
 assert item["share_factor"]==1
def test_stock_right_requires_review():
 row={"除權息日期":"115年11月19日","股票代號":"6213","除權息前收盤價":"100","除權息參考價":"90","權/息":"權"}
 item=normalize(row,"twse")
 assert item["verified"] is False
 assert item["price_factor"]==1
def test_combined_right_dividend_requires_review():
 row={"除權息日期":"115年11月19日","股票代號":"6213","除權息前收盤價":"100","除權息參考價":"88","權/息":"權息"}
 assert normalize(row,"twse")["verified"] is False
def test_unrelated_stock_ignored():
 row={"除權息日期":"115年11月19日","股票代號":"2330","除權息前收盤價":"100","除權息參考價":"98","權/息":"息"}
 assert normalize(row,"twse") is None
def test_tpex_payload_object_list():
 assert len(unpack([{"代號":"8937"}]))==1
def test_twse_payload_field_matrix():
 p={"fields":["股票代號","除權息日期"],"data":[["6213","115年11月19日"]]}
 assert unpack(p)==[{"股票代號":"6213","除權息日期":"115年11月19日"}]
