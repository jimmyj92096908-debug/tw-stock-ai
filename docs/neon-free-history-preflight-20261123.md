# Neon Free 五年歷史回補：容量預檢與私人證據安全門（2026-11-23）

## 真實狀態與不可跨越的限制

這是「正式資料寫入之前的離線容量證據檢查」，不是容量擴充、正式回補、交易訊號發布或付費升級。

- Neon 主分支的 PostgreSQL 資料庫大小為 **751,689,728 bytes**；Neon 分支邏輯使用量為 **775,184,384 / 1,073,741,824 bytes**。這是不同口徑，不能相互扣除後就當成安全可寫入空間。
- 正式 daily_prices 資料為 **2,012,173 筆**，該關聯的表加索引物理大小為 **505,905,152 bytes**。歷史插入、索引、WAL 與 MVCC 的實際成本不可由平均值保證。
- 既有 indicator_capacity_guard.py 有 800,000,000 bytes 保護界限、50,000,000 bytes 預留，要求資料庫大小 + 預估增長 + 預留 < 800,000,000。即使以零增長計算，目前 **也超出保留門檻 1,689,728 bytes**。禁止繞過寫入門檻。
- 已驗收 2021-11-23 至 2021-12-30：官方 AES 來源 26,120 個股票日期鍵、Neon 552 個，Neon 552 全部和 AES 重複；**AES 獨有 25,568 個來源鍵**。來源日期鍵不等於經審核可以匯入的 OHLCV 價格資料。
- 2021 無來源的 153 檔，依 2026 年最新官方上市日期分布為：2022 年 24 檔、2023 年 27 檔、2024 年 37 檔、2025 年 35 檔、2026 年 30 檔；需注意轉板、歷史 PIT 首次交易日的例外，不能臆造缺失價格。
- 2022 的本機 AES 162 日與 Neon 官方批次 84 日，合併涵蓋 246 個來源交易日，但**逐檔 2022 OHLCV 缺口與應補主鍵尚未精確核實**。

## 新增程式與驗收邊界

scripts/neon_free_history_preflight_offline.py 完全離線，讀取三個已核實的本機 JSON 證據：容量快照、2021 AES+Neon 去重報告、153 檔當前上市日期分類報告。嚴格驗證其統計、模型封鎖與零寫入欄位，計算現有保護門檻餘額與來源鍵的**參考**物理占用數，將匿名結果寫至本機新檔且拒絕覆寫。

不連線 Neon、不需要 Neon URL 或 AES 金鑰、不修改資料庫、不發 LINE、不交易、不使用付費 API。程式不具備回補或解封能力，所有報告的 safe_to_run_production_backfill 永遠為 false，model_release 永遠為 BLOCKED。

## 2026-11-23 正式唯讀數據範例

容量快照必須是最近受控唯讀測得的數值，**不能拿本文舊數字當作將來的現況**：

~~~json
{
  "pg_database_bytes": 751689728,
  "neon_branch_logical_bytes": 775184384,
  "neon_branch_limit_bytes": 1073741824,
  "daily_prices_relation_bytes": 505905152,
  "daily_prices_rows": 2012173
}
~~~

若上述數字與當下已核實的 Neon 一致，可將 JSON 保存於私有資料夾 C:\Users\USER\TwStockPrivate\neon-capacity-readonly-20261123.json，**不覆寫既存檔案**。

## Windows PowerShell 5.1 執行

本步要求先前已成功驗收的 owner 私有報告，且不會重跑或覆寫 2021 的任何 AES 驗收。下列參數採用陣列傳遞，避免 PowerShell 5.1 多行貼上語法問題。

~~~powershell
& {
    $ErrorActionPreference = 'Stop'
    cd "$HOME\tw-stock-ai"
    git pull --ff-only origin main
    if ($LASTEXITCODE -ne 0) { throw 'GitHub 更新失敗' }

    $base = "$HOME\TwStockPrivate"
    $snapshot = Join-Path $base 'neon-capacity-readonly-20261123.json'
    $union = Join-Path $base 'aes-neon-2021-28day-aes-neon-deduplicated-stockdates-20261123.json'
    $listing = Join-Path $base 'aes-neon-2021-153-zero-source-current-listing-triage-20261123.json'
    $output = Join-Path $base 'aes-neon-free-history-preflight-20261123.json'

    foreach ($p in @($snapshot,$union,$listing)) {
        if (!(Test-Path $p)) { throw '缺少經核實的本機私有來源或容量快照' }
    }
    if (Test-Path $output) { throw '容量預檢報告已存在，禁止覆寫' }

    $params = @(
        '--capacity-snapshot', $snapshot,
        '--owner-2021-union', $union,
        '--owner-153-listing', $listing,
        '--out', $output
    )
    & python -m scripts.neon_free_history_preflight_offline @params
    if ($LASTEXITCODE -ne 0) { throw '容量預檢失敗' }

    $r = Get-Content $output -Raw | ConvertFrom-Json
    if ($r.safe_to_run_production_backfill -ne $false -or
        $r.model_release -ne 'BLOCKED' -or
        $r.neon_writes -ne 0) { throw '安全驗收不符' }
    Write-Host "寫入保護門檻餘額 bytes：$($r.existing_guard_headroom_before_any_growth_bytes)"
    Write-Host "2021 AES 獨有來源鍵：$($r.'2021_aes_exclusive_source_stockdate_keys_not_in_neon_receipt')"
    Write-Host "正式回補允許：$($r.safe_to_run_production_backfill)"
}
~~~

## 此後仍要完成

1. 擁有者在 Git repo 之外建立可還原的**私人加密行情及事件封存**，保存 SHA256 清單、來源日期與股票主鍵；做獨立還原測試後才能談 Neon 容量調整，**不能先刪任何正式資料**。
2. 對 2021 與 2022 原始來源逐主鍵、逐價量對帳，並處理現行上市名單與歷史 PIT 名單的區別；停牌或尚未上市的日期不能補假收盤價。
3. 在新的容量唯讀檢查、逐主鍵差異清單、具體安全匯入方案與責任審核完成前，不修改容量門檻、不刪正式庫／索引、不升級付費、不觸碰 LINE。
4. 不得把本輪程式測試當成模型獲利證據；既有負樣本外表現、無全新未見驗證仍維持 BLOCKED。

本次只新增可重現的**安全阻擋證據**，沒有宣稱五年資料回補完成。
