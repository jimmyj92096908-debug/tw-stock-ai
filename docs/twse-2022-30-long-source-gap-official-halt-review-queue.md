# 2022 年上市 116 檔內部來源缺口：全部 30 段 6 日以上來源缺口官方查證佇列

## 已驗收基礎（2026-11-23 使用者真實本機報告）

- PR #237 在 Windows 已真實通過 `TWSE_2022_116_INTERNAL_SOURCE_ABSENCE_TRIAGE_READONLY_PASS`，目前仍上市 TWSE 1,092 檔（排除下市與 1589）；104 檔只有內部缺口，另 12 檔內部和外側均有缺口。
- 此 116 檔在 2022 的 246 個已觀測 AES＋Neon 來源日期內，有 804 筆**名目缺少來源紀錄的股票日期組合**，分散為 526 段互斥連續期間：1 日 423 段、2–5 日 73 段、6 日以上 **30 段**。沒有經官方停牌、恢復交易、完整歷史上市時點核實，**804 不等於應補 K 線筆數，30 段也不等於 30 次正式停牌**。
- PR #237 原報告每檔只留**兩段最長缺口的例子**。對同一股票若有 3 段以上 6 日缺口，舊報告不能枚舉全 30 段；不得單憑舊 JSON 推斷全部 30 段的確切日期。

## 本階段工作

新增已測試的 `full_six_plus_source_gap_queue(...)` 並在原始 AES＋Neon 唯讀稽核加入 opt-in `--internal-gap-triage --long-gap-queue --prior-116-report ...`。繼續使用**已認證 162 個 AES 來源日**和**Neon 單一 `REPEATABLE READ READ ONLY` 快照**中的 2022 年官方來源日期鍵，不讀取或輸出 OHLCV、價格或金鑰、不回補、不寫入。

必須與上一份私有正式 PR #237 報告的 116 股票缺口清單、每月統計、804 筆股票日期、526 段期間、30 段長缺口、整個 JSON 局部內容**完全相等**；不等就失敗。以原始股票/日期鍵重新掃描每檔首末實際來源日間**全部**缺席段，逐段保留真正長度 >=6 的 30 筆，依長度由大至小排序，只記 4 碼股票代號、首末缺來源日期及名目連續來源日數。既有驗收報告絕不覆寫，新增存於 `TwStockPrivate` 的私有 JSON；CLI 只列彙總筆數。

這不是官方停牌驗證工具，**不宣稱有 30 次停牌、不宣稱應補 30 段股價、不假設所有已觀測來源日均是各股票歷史交易義務日**。下一步必須將私有精確日期逐一用官方的 <https://www.twse.com.tw/zh/trading/historical/twtawu.html>「暫停交易證券」歷史查詢及必要的 TWSE／重大訊息停復牌與原始個股日交易源核對。該 TWSE 歷史查詢頁自民國 100 年 10 月 3 日起提供資料，但其名錄涵蓋範圍未在本工具中查驗完整；不能因查不到資料就判定有缺漏。

## Windows PowerShell 5.1 本機驗收

只在你的 Windows 電腦執行；要求既有 Neon URI 設在安全本機 `DATABASE_URL` 環境變數，AES vault 仍由你本機的金鑰提示提供，不要貼上連線網址或金鑰。先前完整 PR237 報告仍須存在，且新輸出不可與任何舊報告同名。

```powershell
& {
  $ErrorActionPreference = 'Stop'
  cd "$HOME\tw-stock-ai"
  git pull --ff-only origin main
  if ($LASTEXITCODE -ne 0) { throw 'GitHub 更新失敗' }
  if ($env:DATABASE_URL -notmatch '^postgres(ql)?://') {
    throw '請先在目前 PowerShell 視窗安全設定既有 Neon DATABASE_URL'
  }
  $env:TWSE_KEY_GUI_PROMPT = '1'
  $p = "$HOME\TwStockPrivate"
  $panel = Join-Path $p 'aes-neon-240-stock-gaps-20261123.json'
  $five = Join-Path $p 'aes-neon-five-year-current-listed-cohort-20261123.json'
  $overlay = Join-Path $p 'aes-neon-2022-five-year-source-overlay-20261123.json'
  $prior = Join-Path $p 'aes-neon-2022-116-internal-source-gap-triage-20261123.json'
  $out = Join-Path $p 'aes-neon-2022-30-long-source-gaps-for-official-halt-check-20261123.json'
  foreach ($f in @($panel,$five,$overlay,$prior)) {
    if (!(Test-Path $f)) { throw '缺少前置 AES、Neon 或 116 檔已驗收報告' }
  }
  if (Test-Path $out) { throw '輸出報告已存在，禁止覆寫' }

  python -m scripts.twse_2022_aes_neon_eligible_density_readonly `
    --archive-2022 "$env:LOCALAPPDATA\tw-stock-private\prices" `
    --key-vault "$env:LOCALAPPDATA\tw-stock-private\history.twsekey" `
    --source-panel-report "$panel" `
    --five-year-neon-report "$five" `
    --prior-overlay-report "$overlay" `
    --internal-gap-triage `
    --long-gap-queue `
    --prior-116-report "$prior" `
    --out "$out"
  if ($LASTEXITCODE -ne 0) { throw '30 段完整長來源缺口佇列驗收未通過' }
  $r = Get-Content $out -Raw | ConvertFrom-Json
  $queue = $r.owner_private_all_30_long_source_absence_runs_official_check_queue
  [PSCustomObject]@{
    涉及內部缺口股票 = $queue.underlying_116_source_absence_stocks
    名目缺來源股票日期 = $queue.underlying_all_absent_stock_source_day_pairs
    總獨立缺口段數 = $queue.underlying_all_absent_source_day_runs
    需優先查官方停復牌的長缺口段 = $queue.at_least_six_unobserved_source_day_run_count
    已確認官方停牌 = -not $queue.official_halt_or_resumption_not_checked_by_this_offline_step
  } | Format-List
  $queue.owner_private_long_run_official_halt_check_queue |
    Select-Object -First 10 stock_id,first_unobserved_source_day,
      last_unobserved_source_day,unobserved_consecutive_source_days |
    Format-Table -AutoSize
}
```

預期成功狀態：`TWSE_2022_ALL_30_LONG_SOURCE_ABSENCE_OFFICIAL_QUEUE_READONLY_PASS`。**本機實際跑完前，不能標示資料庫私有 30 段完整還原已通過。** 只貼回彙總輸出與自行選擇的幾筆公開股票代號／日期，絕不貼帳密、完整私有行情 JSON 或 AES 原始資料。

正式模型仍 `BLOCKED`；只允許讀 Neon、AES 和原始已驗收報告，絕不改 LINE、絕不額外付費、也不加回下市或 1589。