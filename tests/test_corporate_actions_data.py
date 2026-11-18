import pytest
from corporate_actions_data import normalize, normalize_reduction, parse_date, unpack

def test_roc_date():
 assert parse_date("115年11月19日")=="2026-11-19"
def test_cash_dividend_is_verified():
 row={"除權息日期":"115年11月19日","股票代號":"6213","除權息前收盤價":"100","除權息參考價":"98","權/息":"息"}
 item=normalize(row,"twse")
 assert item["verified"] is True and item["price_factor"]==pytest.approx(.98)
def test_stock_right_requires_review():
 row={"除權息日期":"115年11月19日","股票代號":"6213","除權息前收盤價":"100","除權息參考價":"90","權/息":"權"}
 assert normalize(row,"twse")["verified"] is False
def test_combined_right_dividend_requires_review():
 row={"除權息日期":"115年11月19日","股票代號":"6213","除權息前收盤價":"100","除權息參考價":"88","權/息":"權息"}
 assert normalize(row,"twse")["verified"] is False
def test_reduction_requires_share_ratio():
 row={"恢復買賣日期":"2025-12-08","股票代號":"6213","停止買賣前收盤價":"100","恢復買賣參考價":"120"}
 assert normalize_reduction(row,"twse")["verified"] is False
def test_reduction_uses_official_share_ratio():
 row={"恢復買賣日期":"2025-12-08","股票代號":"6213","停止買賣前收盤價":"100","恢復買賣參考價":"120","每仟股換發股數":"833"}
 item=normalize_reduction(row,"twse")
 assert item["verified"] is True
 assert item["price_factor"]==pytest.approx(1.2)
 assert item["share_factor"]==pytest.approx(.833)
def test_unrelated_stock_ignored():
 row={"除權息日期":"115年11月19日","股票代號":"2330","除權息前收盤價":"100","除權息參考價":"98","權/息":"息"}
 assert normalize(row,"twse") is None
def test_tpex_payload_object_list():
 assert len(unpack([{"代號":"8937"}]))==1
def test_twse_payload_matrix():
 assert unpack({"fields":["股票代號"],"data":[["6213"]]})==[{"股票代號":"6213"}]
