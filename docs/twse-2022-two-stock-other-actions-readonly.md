# 2021–2022 2327／2603：已儲存公司行動的唯讀覆蓋率稽核

前一階段 `CASH_REDUCTION_ONLY_2022_REAL_TRADED_240_SMA_RESEARCH_PASS` 表示兩檔在 2022-12-30 可以用 240 筆實際交易日行情做**單一現金減資事件價格尺度**的 SMA240 研究計算，不表示 2021-12-30～2022-12-30 期間的除權、除息、其他減資、拆併股或真實現金總報酬均已納入。**資料庫沒有該股公司行動資料，絕不等於真的沒有除息、分割或現金返還。**

本工具只用已通過的本人私有 PR #223 報告作為前置驗收，然後以 `REPEATABLE READ, READ ONLY` 從 Neon 正式現有 `corporate_actions` 取得 **2327、2603** 在已驗證的 240 個實際個股交易日對應日期區間（2021-12-30～2022-12-30）的**已儲存**事件。限制不超過 200 筆，查詢結果總數與讀到的列數須一致，否則停止，並檢查原始來源 ID、交易所、事件日期、非有限因子、重複與矛盾的經濟條件。

新本機 JSON 僅報告各檔事件筆數、已標示 verified 筆數、非現金減資事件筆數、現金股利欄位缺漏、資料首次擷取是否晚於除權息日、同日同類事件條件有無矛盾，以及仍未完成的安全阻擋。事件的每股金額、私有原始行情、AES 密語、Neon URI 或原始個股完整因子不會印在終端機，亦不會加入 GitHub。

## 在 Windows PowerShell 執行（不覆寫）

```powershell
cd "$HOME\tw-stock-ai"
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw 'GitHub 更新失敗' }

$report = "$HOME\TwStockPrivate\aes-neon-2022-event-only-sma240-20261123.json"
$output = "$HOME\TwStockPrivate\aes-neon-2022-two-stock-action-coverage-20261123.json"
if (!(Test-Path $report) -or (Test-Path $output)) { throw '前置報告不存在或輸出已存在，停止' }
if ($env:DATABASE_URL -notmatch '^postgres(ql)?://') { throw '請先安全設定 Neon 唯讀連線' }

python -m scripts.twse_2022_two_stock_action_coverage_readonly `
    --sma-report "$report" `
    --out "$output"
if ($LASTEXITCODE -ne 0) { throw '公司行動唯讀覆蓋稽核未通過' }

$r = Get-Content $output -Raw | ConvertFrom-Json
$r.per_stock_action_coverage |
    Select-Object stock_id,stored_event_rows_in_proven_240_traded_day_window,stored_non_cash_reduction_event_rows,stored_unverified_event_rows,stored_events_first_captured_after_ex_date |
    Format-Table -AutoSize
```

**驗收通過** 只代表已儲存的既有紀錄已被完整盤點。就算兩檔事件筆數為 0，也仍必須透過另行驗證的**官方歷史公司行動全量來源**、現金權益歸屬與付款日期、原始公告可得時間（as-of）才能標示為調整完整。既有 `created_at` 是資料庫首次擷取時間，不代表公司原始公告時間。

本階段不接觸 AES 金鑰、不重新下載行情、不改寫 Neon 不傳送 LINE、不加購資源、不納入下市股票或 1589。完整除權息與 total-return、五年覆蓋、PIT 股票身分、Walk-forward 前瞻驗證仍不合格，**正式模型發布 BLOCKED**。