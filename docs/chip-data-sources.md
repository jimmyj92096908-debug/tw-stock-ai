# 籌碼資料來源與更新規格

| 資料 | 上市 TWSE | 上櫃 TPEx | 頻率 |
|---|---|---|---|
| 三大法人 | TWSE T86: https://www.twse.com.tw/rwd/zh/fund/T86 | https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading | 交易日 |
| 融資融券 | TWSE OpenAPI /v1/exchangeReport/MI_MARGN | TPEx OpenAPI /v1/tpex_mainboard_margin_balance | 交易日 |
| 集保股權分散 | TDCC OpenAPI /v1/opendata/1-5 | 同一 TDCC 資料集 | 每週 |
| 董監分戶保管 | TDCC OpenAPI /v1/opendata/1-4 | 同一 TDCC 資料集 | 依官方更新 |
| 董監持股 | 公開資訊觀測站 | TPEx OpenAPI mopsfin_t187ap11_O 等 | 月報／公告 |

## 資料品質原則
- 買賣數量統一使用「股」，不可混用「張」。
- 原始 API 欄位保留在 raw_payload，標準化欄位另存。
- API 查無資料、非交易日、欄位變動、HTTP 錯誤必須分開記錄；不得把缺資料當成 0。
- TDCC 集保戶股權分散表是每週資料，不得當成每日資料。
- 董監持股是申報／公告資料，頻率不同於每日法人買賣超。
- 大戶集中度先明確定義級距口徑，再計算週變化。
- 初期先驗證四檔指定股票，通過後再擴大到全市場。

## 待完成驗證
1. 確認 TWSE T86、TPEx 三大法人端點的欄位、日期及單位。
2. 確認上市／上櫃融資融券欄位與單位。
3. 確認 TDCC 1-5、1-4 的欄位及歷史可用範圍。
4. 確認董監持股報表月份、持股及設質股數欄位。
5. 建立缺值、無資料日及欄位改版測試。
