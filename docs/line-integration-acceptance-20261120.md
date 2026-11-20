# LINE 單一官方帳號整合：2026-11-20 當日驗收紀錄

這是部署／資料／流程的可稽核狀態，**非投資訊號或正式長期切換授權**。所有時間以 Asia/Taipei 為主。正式資料庫只做聚合 SELECT；本紀錄不含 LINE user ID、訊息內容、私密憑證、連線字串。

## 已完成

- 原版 `linewebhook`：Neon Deployment 4，completed，仍由 LINE 官方入口提供私人文字處理；2026-11-20 22:55 使用者實測 `你好` 成功收到原版回覆，當時兩筆 Function invoke begin/end 未再記錄權限錯誤。
- 原版寫入權限修復：見 [line-legacy-permission-incident-20261120.md](line-legacy-permission-incident-20261120.md)。僅額外授予 `line_stock_delivery` 對 `public.line_messages.id` 的 SELECT 與 `received_at` 的 INSERT，私人文字／使用者 ID 的 SELECT 仍被拒。
- 新版 `linestockgateway`：Neon Deployment 6 completed，設定 `LINE_SINGLE_ACCOUNT_ENABLED=false`（已於最後一次受控試驗後重新部署停用）。
- LINE 真實受控測試：2026-11-20 22:16–22:20，GitHub [#44751814649](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/runs/44751814649)，四分鐘切換工作 success、兩次 `ROLLBACK_VERIFIED original_active=true`；使用者截圖確認 `清單`、`6213` 已回覆，正式 `line_reply_delivery` 有 4 筆 `sent`。**未驗證每一項股票指令或所有一般文字經新閘道轉送的完整 E2E**。
- 官方簽章空事件：GitHub [#44747808850](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/runs/44747808850) 回應 200。
- 原有 Webhook 唯讀驗證：GitHub [#44748946247](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/runs/44748946247) 確認原版 active，候選 GET /health=200。新版本未作長期 URL 切換。
- 原有每日報告：正式資料表含 2 筆 `outgoing_daily_report`，兩筆不同事件識別碼，當時有效文字收件者數量 1，最近一筆紀錄建立於 2026-11-20 00:30 本地時間，報告交易日 2026-11-19。程式 `src/send_line_report.py` 僅在 LINE Push API 2xx 後記錄成功；這是歷史成功紀錄，**不是今晚 23:30 的結果**。

## 2026-11-20 行情重大品質風險

- `public.daily_prices` 2026-11-19 有收盤價 **1,966 檔**；2026-11-20 最新日期**只有 11 檔**（台灣證交所 5、櫃買 6）。
- `public.daily_composite_scores` 最新有效評分日期為 2026-11-19，不能作為 2026-11-20 的新評分。
- GitHub [Full Market Daily Data Rotation #44756944568](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/runs/44756944568) 失敗，日誌包含 `還原行情建立筆數為 0` 與部分股票更新失敗。此批次每個市場只輪替一部分，與完整交易日官方快照屬不同流程，不能把單一批次的失敗當作官方全市場快照已失敗的證據。
- `.github/workflows/daily-official-market-snapshot.yml` 計畫在台灣時間 23:00（工作日）補入官方交易日快照。需要**實際執行紀錄與最新覆蓋率**驗證是否已完成；GitHub schedule 可能延遲。
- 2026-11-20 已在 `src/send_line_report.py` 加入嚴重行情缺漏的 **live-only fail-closed gate**。抓取前一個已存交易日的不同上市／上櫃股票有效收盤價檔數；若前一日至少 100 檔、最新日少於其 70%，直接在 LINE Push API 前拋錯停止推播。如果前一日無資料但候選宇宙大於 100 檔，最新少於宇宙 10% 也停止。只傳回聚合計數，不輸出收件者身分。 `--dry-run` 保留作診斷。
- 最新 CI：[Python Tests #44759539634](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/runs/44759539634) success；[Daily LINE Stock Data Report dry-run #44759539559](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/runs/44759539559) success，日誌確認 `DRY RUN：未發送 LINE`，預覽顯示 `行情覆蓋：11/1,991 檔股票`、評分日期 11/19。**不能因 CI green 就稱今晚已推播成功**。

## 仍需通過才可長期啟用新版 LINE 入口

1. 官方快照的日終覆蓋完整性，及每日推播排程結果（需核對當次 GitHub Actions + Neon 事件）。
2. 新版閘道的**非股票私人文字轉送至原版程式**，在本次最小權限修復之後需重驗；四分鐘試驗結束後發出的普通文字只能證明原版直接處理正常，不能證明新閘道代理轉送正常。
3. 追蹤、取消傳送、群組或非文字訊息與原版的相容性；Reply API 失敗、重送及同一 Token 去重的上線端到端監控。離線測試代替不了這些實測。
4. 如未再次明確授權，**不要重新切換 LINE 官方註冊 Webhook URL**，或啟用 `LINE_SINGLE_ACCOUNT_ENABLED`。每日推播只按既有排程與已授權腳本運作，不做額外手動 Push。

## 無資料破壞／隱私邊界

本次新增的是判斷是否應停止 LINE Push 的唯讀品質檢查，並沒有修改行情或評分資料庫表，沒有自動下單，也沒有修改 LINE 官方正式 Webhook URL。

## 2026-11-20 23:14 官方 11/20 行情缺漏補齊（使用者明確授權）

- 使用者明確核准：使用現有 `src/official_snapshot_ingest.py` 與官方來源補入 2026-11-20 上市、上櫃缺漏日 K；不得覆寫既有行情、變更 LINE Webhook 或額外發送 LINE 訊息。
- 一次性受控 GitHub Actions [#44761144734](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/runs/44761144734) 執行成功。執行前檢查雙市場實際來源日期必須為 `2026-11-20`，且 TWSE 至少 800 檔、TPEx 至少 650 檔；官方解析與資料合法性單元測試共 7 項通過。
- 執行使用原本 `run(..., apply=True, fetcher=checked_fetch, today=date(2026,11,20))`，沿用 `write_missing` 和 `ON CONFLICT (market,stock_id,trade_date) DO NOTHING`，僅新增不存在的 `daily_prices` 主鍵列。
- GitHub 真實匯入日誌：
  - `AUTHORIZED_IMPORT market=twse date=2026-11-20 qualified=1090 inserted=1085 mode=apply`
  - `AUTHORIZED_IMPORT market=tpex date=2026-11-20 qualified=883 inserted=877 mode=apply`
- **實際新增總計 1,962 筆**。正式 Neon 經唯讀查核：2026-11-20 TWSE 1,091 列／有效收盤價 1,090 檔（保留一筆原有空收盤價列）；TPEx 883 列／有效收盤價 883 檔；合計有效收盤價 **1,973 檔**。無 `close <= 0` 的記錄。
- 11/20 `source` 聚合：TWSE `TWSE_MI_INDEX_ALLBUT0999` 1,085 列、既有 `TWSE_STOCK_DAY` 6 列；TPEx `TPEX_DAILY_CLOSE_OPENAPI` 877 列、既有 `TPEX_TRADING_STOCK` 6 列。符合只新增缺漏、不覆寫既有列的約束。
- 前交易日 2026-11-19 的正式 Neon 有效收盤價維持 TWSE 1,090 + TPEx 876 = 1,966 檔，無覆寫該交易日的計畫或 SQL。
- 有效綜合評分最新日期仍為 **2026-11-19**，未生成或假設 11/20 評分；LINE 日報應繼續明示評分與行情日期不同。
- 執行後刪除一次性 GitHub 工作流程 `.github/workflows/one-time-authorized-1120-price-import.yml`；歷史 GitHub 執行日誌保留。
- 本次匯入工作只讀官方兩市場資料與 `stock_master`、寫入缺漏 `daily_prices`；沒有 LINE API 呼叫、沒有變更任何 LINE Function 或正式 Webhook。原有 23:30 排程為獨立流程，其執行狀態需要另外查核，不能由本次匯入推定已成功發送。
