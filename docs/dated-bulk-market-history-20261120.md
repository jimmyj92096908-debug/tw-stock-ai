# 2026-11-20 官方日期型批次歷史資料回補

## 背景與來源

目前正式資料庫已有近全數候選股的單日行情快照，但大部分股票缺乏長期 OHLCV，無法可信計算完整技術指標或多期評分。

官方證交所 TWSE MI_INDEX 可指定 `date=YYYYMMDD` 並要求 `type=ALLBUT0999`，回應含每日全市場收盤行情；既有 `src/official_market_feed.py` 會核對標題的實際交易日期、四位代碼、成交量、開高低收、數值合法性。TPEx 的目前 OpenAPI 每日收盤行情只提供最新一日；上櫃歷史暫保留已驗證的逐檔有上限回補方式，**不能假設帶日期的 TPEx OpenAPI 支援歷史查詢**。

## 本次已實際執行

- 在 Neo​​n `twstock` 正式資料分支建立回補前獨立快照 `before-twse-bulk-history-20261120`（ID `br-flat-cake-a17lebfs`）；未刪除既有快照。
- 先於 GitHub Actions #44669443064 以**唯讀**方式驗證 2026-11-18 與 2026-11-19 的官方 TWSE 指定日期來源；兩日各回傳 1,090 檔符合 stock_master 的行情，無寫入。
- GitHub Actions #44669656277 在離線測試及無寫入官方預覽通過後，執行一次**最多 8 個交易日**的缺漏行情插入。
- 8 個已驗證交易日為 2026-11-19、18、17、16、13、12、11、10；11/19 原有資料故新寫入為 0，其餘 7 日共**7,488 筆**新增交易日 K 線。寫入採 `ON CONFLICT (market,stock_id,trade_date) DO NOTHING`，不覆蓋既有原始資料；進度記在 `public.twse_history_day_progress`，避免重跑重複請求。
- 已建立 `src/twse_dated_history.py` 和日期進度檢查，預設 dry run，寫入需 `--apply` 且 `STOCK_TWSE_HISTORY_WRITE_ENABLED=yes`。每次最多 8 個日期、最多回看 366 個日曆日，兩次官方 HTTP 之間至少 2 秒，資料不足或無法驗證日期時立即失敗。
- 執行後將一次性的真實寫入 GitHub workflow 移除，避免之後重新提交程式意外重跑。
- 準備於主分支排定週二至週六凌晨 01:50（台灣時間）繼續每次最多 8 個日期的上市全市場歷史回補。手動執行仍預設不寫入。

## 技術指標與評分的正確前置條件

- 只有 `daily_prices` 的有效收盤價交易日達到至少 **60** 個、最後行情日未過期且技術／SMC 指標不足的候選股票，才會進入 `src/batch_indicator_catchup.py`。
- 先依已驗證公司行動建立 `daily_adjusted_prices`，再依歷史資料逐股重算 `daily_technicals` 和 `daily_smc`；不能用某一天市場快照造出 20/60/120/240 日技術指標。
- 單次指標批次最多上市 20 檔、上櫃 20 檔。尚不足 60 個有效日的股票保持**資料不足**，不是「看空／看多」評分。
- 日期型回補成功的排程可觸發指標補計，成功後再觸發綜合評分。所有流程只使用已儲存有效行情和既有評分規則。
- **60 日不是全長期指標已完整的保證**：120/240 日均線需要更多歷史交易日；應繼續依現有資料覆蓋權重顯示不足。

## 測試與回復

- `tests/test_twse_dated_history.py`：不接觸網路，測試官方日期錯誤、休市、部分股票缺漏、資料來源錯誤、批次上限、第二道寫入開關、dry-run 和成功進度。
- `tests/test_twse_dated_history_postgres.py`：在 **localhost/stock_ci_test** 一次性 PostgreSQL 中測試插入多股票行情與既有行情不被覆蓋；程式會拒絕其他資料庫地址。
- `tests/test_batch_indicator_catchup.py`、`tests/test_batch_indicator_catchup_postgres.py`：驗證至少 60 日才補指標、候選批次上限、不同市場、未通過驗證者不能算完成。
- 回補前 Neon 快照保留作為比對基準。若新官方來源出現錯誤，先停用指定 workflow；勿直接刪除整個行情表或使用對照資料覆蓋較新的有效行情。
- 此項修改**不會切換 LINE Webhook**。舊 `linewebhook` 的正式回覆與每日報告照原本設定執行。

## 仍待完成

歷史涵蓋需要分交易日累積。上市的日期型端點可有效降低每檔 HTTP 請求數，但 TPEx 歷史仍需另驗證不同來源，不能把尚未取得的交易日、停牌資料或長期指標臆造出來。新週期排程是否成功，需以日後實際 GitHub Actions 結果為準。
