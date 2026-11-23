# 2022 TWSE 官方在市股票：AES＋Neon 逐檔逐日行情存在性驗收

## 已有本機實測基礎

擁有者 Windows 紀錄已通過：PR #230 `TWSE_2022_AES_NEON_FIVE_YEAR_SOURCE_DAY_OVERLAY_OFFLINE_PASS`；本機 162 個已認證 AES 官方來源日、Neon 原始 84 個官方整批來源日，重疊為零、合併 246 個 2022 來源日期。PR #229 全市場五年 Neon-only 合法來源核對：當前 TWSE 1,092 檔官方在市研究股票（排除下市及 1589），2022 年 Neon 有任一檔 246 日，其中每日含至少 500 檔有效資料者僅 84 日，Neon 2022 合法來源股票日紀錄總筆數 83,294。

以上**只證明兩份報告中的總數**，而不是逐日個股行情。新工具真正做 2022 個股股票日 key 的不重複聯集。

## 受控唯讀操作

`scripts.twse_2022_aes_neon_eligible_density_readonly` 先驗證三份已接受的私人驗收報告不曾被竄改（2022 frozen20、五年 Neon-only、PR #230 日曆聯集），然後以本機 AES vault 金鑰重新認證 162 天原始來源，全部保留在記憶體、不輸出原始 OHLCV/股價。從 Neon **同一個 `REPEATABLE READ READ ONLY` 快照**下載的只有 2022 年 TWSE `trade_date`,`stock_id`,`source`（最多 180,000 列；先前計數為 83,294），不包含任何實際股價。

股票資格分母來自最新 14 天內官方上市名單，嚴格排除目前下市、`1589` 及 `model_stock_exclusions`，須跟前次 1,092 檔一致。讀 Neon 的來源只准 `TWSE_MI_INDEX_ALLBUT0999`／`TWSE_STOCK_DAY`，並要求該來源行 `close > 0`、`volume >= 0`（這只是來源存在性檢查，不能充當所有 OHLCV 經濟合理性認證）。

驗證真實本機 AES 162 日期、Neon 原始官方 bulk 84 日期，且兩者無來源日期重疊，原始日期聯集仍 246。**逐日期、逐股票鍵去重**聯集（非僅 162+84 算術相加），計算：

- AES 162 日期中，真正具有至少 500 檔目前上市有效股票行情的日期數與每日最小／最大檔數
- Neon 2022 年 83,294 筆合法來源股票日記錄的日期分布，與 84 個官方 bulk 日、84 個 `≥500` 檔來源日是否**完全同一組日期**；有不同就明確報告來源日期（而不是只比較總數）
- AES＋Neon 的 246 日期中逐日 `≥500` 檔的真實日期數，及各月份覆蓋檔數範圍
- 現今仍上市股票有多少至少具有 240／246 個 2022 來源交易日，或有全部 246 日期；**不把 IPO、股票停牌、2022 當年未上市誤判為回補缺漏**

即使每個來源日期都 `≥500` 檔，也不等於每一檔都有完整 2022 原始行情、所有 246 日都是經獨立驗證的完整市場交易日曆、歷史沒有下市存活者偏差，或已完整除權息、減資及 total return。正式交易、模型訓練及 walk-forward 都保持 `BLOCKED`，Neon 沒有任何寫入，沒有新增付費及 LINE 改動。

## Windows PowerShell 唯讀本機驗收

本次需要你先前安全保管的 `DATABASE_URL`（只在**目前這個 PowerShell 視窗**環境變數）及 AES vault。不要在聊天或 GitHub 貼任何連線 URI／金鑰。確保報告寫在現有 `TwStockPrivate` 資料夾，工具一律拒絕覆寫。

```powershell
& {
  $ErrorActionPreference = 'Stop'
  cd "$HOME\tw-stock-ai"
  git pull --ff-only origin main
  if ($LASTEXITCODE -ne 0) { throw 'GitHub 更新失敗' }
  if ($env:DATABASE_URL -notmatch '^postgres(ql)?://') { throw '請先在這個視窗安全設定 Neon 連線網址' }
  $base = "$HOME\TwStockPrivate"
  $panel = Join-Path $base 'aes-neon-240-stock-gaps-20261123.json'
  $fiveYear = Join-Path $base 'aes-neon-five-year-current-listed-cohort-20261123.json'
  $overlay = Join-Path $base 'aes-neon-2022-five-year-source-overlay-20261123.json'
  $out = Join-Path $base 'aes-neon-2022-current-listed-source-density-20261123.json'
  foreach ($p in @($panel,$fiveYear,$overlay)) { if (!(Test-Path $p)) { throw '缺少先前驗收報告' } }
  if (Test-Path $out) { throw '新輸出已存在，禁止覆寫' }
  $env:TWSE_KEY_GUI_PROMPT = '1'
  python -m scripts.twse_2022_aes_neon_eligible_density_readonly `
    --archive-2022 "$env:LOCALAPPDATA\tw-stock-private\prices" `
    --key-vault "$env:LOCALAPPDATA\tw-stock-private\history.twsekey" `
    --source-panel-report "$panel" `
    --five-year-neon-report "$fiveYear" `
    --prior-overlay-report "$overlay" `
    --out "$out"
  if ($LASTEXITCODE -ne 0) { throw '2022 全上市逐日來源覆蓋率尚未通過' }
  $r = Get-Content $out -Raw | ConvertFrom-Json
  [PSCustomObject]@{
    AES來源日 = $r.aes_prior_2022_source_calendar_dates
    AES達500檔日期 = $r.aes_dates_with_at_least_500_current_eligible_stock_bars
    Neon原始整批來源日 = $r.neon_original_bulk_source_calendar_dates
    Neon84高密度與整批日期集合相同 = $r.neon_bulk_date_set_matches_500_stock_density_date_set
    合併後246日達500檔數 = $r.aes_neon_merged_days_with_at_least_500_current_eligible_stock_bars
    2022有至少240日行情的目前上市股票數 = $r.aes_neon_current_listed_stocks_with_at_least_240_of_246_source_dates
  } | Format-List
  $r.aes_neon_2022_monthly_source_date_density | Format-Table -AutoSize
}
```

預期輸出狀態 `TWSE_2022_FULL_CURRENT_COHORT_AES_NEON_DENSITY_READONLY_PASS`，不預先猜測 162 日每日至少 500 檔或 246 日 100% 逐日行情完整。若當前官方上市名單、Neon 2022 來源資料或 AES 私有檔變動，將停止而不是製造資料。全研究仍 `BLOCKED`。