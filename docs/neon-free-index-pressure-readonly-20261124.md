# Neon Free 五年行情：純唯讀資料表／索引容量驗收

## 目標及安全界線

2026-11-24 前瞻封存流程 PR #264、#265 已建立兩道防護：**資料庫大小達 650,000,000 bytes** 或實際 Neon 傳輸額度不可認證，必須先停止新增昂貴研究；若之後安全條件確實成立，才使用已存在索引的日期限定查詢。這不等於整體五年資料完成。

Neon 已觀察到資料庫約 **753,147,904 bytes**，高於 650,000,000 bytes 研究警戒；專案另設 800,000,000 bytes 程式硬停止線。這三項是 PostgreSQL 實際占用與**專案自行設定**的警戒，不能誤稱 Neon 官方帳單儲存、傳輸、compute 用量或使用者尚餘付費額度。為符合「零額外付費、不修改 LINE、正式 Neon 唯讀、排除 1589 與下市股」，不得直接提高限制或在正式庫大批回補。

## 已從正式 Neon 執行的唯讀觀測

2026-11-24 使用 SELECT 從 pg_catalog 及 pg_stat_* 查看；沒有新增索引、VACUUM、DDL、DML、TRUNCATE、交易或額外 LINE 訊息。

| 資料表 | 含索引實際空間 | 其中索引空間 |
| --- | ---: | ---: |
| daily_prices | 506,331,136 bytes | 215,588,864 bytes |
| daily_adjusted_prices | 70,336,512 bytes | 27,590,656 bytes |
| daily_technicals | 57,868,288 bytes | 16,474,112 bytes |
| daily_smc | 52,174,848 bytes | 27,574,272 bytes |
| daily_composite_scores | 42,958,848 bytes | 4,775,936 bytes |

**原始行情表的三個索引全都觀察到使用：**

| 索引 | Bytes | 已觀察 idx_scan |
| --- | ---: | ---: |
| daily_prices_pkey | 107,323,392 | 4,307,144 |
| idx_daily_prices_stock_date | 89,767,936 | 1,372,889 |
| idx_daily_prices_date | 18,497,536 | 18,341 |

注意索引計數通常自最近一次 PostgreSQL 統計重置起累積，**不是**單日使用率、完整生命週期保證、刪除可行性或表物理回收估算。死 tuple 估計值也不能換算為「立刻能回收的 GB」。上述數字是查詢時點快照，會變動。

## 新增程式與驗收

執行 scripts.neon_free_index_pressure_readonly 時，僅使用 PostgreSQL 強制 default_transaction_read_only=on、REPEATABLE READ READ ONLY 與 6 秒 statement_timeout；固定做四種內容（設定交易、設定逾時、讀整庫大小及統計重置日期、讀五個表的 heap/index 空間、讀最多 40 個索引大小和累計掃描次數）。**不查詢個別股票代號、股價、個股指標、AES 加密封存、LINE 或 Neon 帳單 API。**

本地 JSON 僅存在 Git 工作樹外的私人目錄，以排他建立，不覆寫之前驗收；成功摘要僅公開整庫 bytes、警戒狀態、表數和索引數，拒絕輸出私人 URI／路徑。索引大小帳本與各表 pg_indexes_size **必須完全對帳**，缺欄位、錯誤數字、重複索引、未列出全部表／索引就 fail closed。資料庫高於 650 MB 應回報 ABSTAIN_STORAGE_WARN；低於也只能表示「本次表資料觀測成功」，**不是**核准實際回補或任何索引變更。五年歷史覆蓋率與模型 alpha 不會因這個工具變成通過。

## Windows PowerShell 5.1（僅做私人唯讀核對）

以下只在程式合併至 main 且前後 GitHub CI PASS 後可選擇執行。需要原本**已保護的** DATABASE_URL 環境變數，但不得在聊天或 GitHub 輸出連線字串。

~~~powershell
& {
    $ErrorActionPreference = 'Stop'
    cd "$HOME\tw-stock-ai"
    git pull --ff-only origin main
    if ($LASTEXITCODE -ne 0) { throw 'GitHub 更新失敗' }

    if ([string]::IsNullOrWhiteSpace($env:DATABASE_URL)) {
        throw '未設定原本受保護的 Neon DATABASE_URL，請勿貼出連線資訊'
    }
    $out = Join-Path "$HOME\TwStockPrivate" 'neon-free-index-pressure-20261124.json'
    if (Test-Path -LiteralPath $out) {
        throw '私人來源報告已存在，禁止覆寫'
    }
    & python -m scripts.neon_free_index_pressure_readonly --out $out
    if ($LASTEXITCODE -ne 0) { throw '只能分享匿名 diagnostic_stage' }

    $r = Get-Content -LiteralPath $out -Raw | ConvertFrom-Json
    if ($r.scope -ne 'NEON_FREE_FIVE_YEAR_HISTORY_TABLE_INDEX_PRESSURE_READONLY_BLOCKED' -or
        $r.major_table_count -ne 5 -or
        $r.all_inspected_index_count -lt 5 -or
        $r.production_price_backfill_approved -ne $false -or
        $r.production_index_ddl_approved -ne $false -or
        $r.neon_billing_quota_verified_by_this_script -ne $false -or
        $r.neon_writes -ne 0 -or
        $r.line_messages_sent -ne 0 -or
        $r.model_release -ne 'BLOCKED') {
        throw '唯讀統計或安全驗收未通過'
    }
    Write-Host 'Neon 主要索引容量唯讀驗收 PASS'
    Write-Host "資料庫 bytes：$($r.database_bytes_from_pg_database_size)"
    Write-Host "650MB 門檻：$($r.storage_workflow_preflight_status)"
    Write-Host "資料表／索引：$($r.major_table_count)／$($r.all_inspected_index_count)"
    Write-Host "資料回補核准：$($r.production_price_backfill_approved)"
    Write-Host "Neon 寫入：$($r.neon_writes)"
    Write-Host "模型狀態：$($r.model_release)"
}
~~~

只分享最後安全摘要，不上傳 JSON、DATABASE_URL、本機路徑或股票資料。若報表因索引變動或 6 秒保守逾時而失敗，不擅自放寬資料量上限／時間上限，也不把失敗當成可刪除索引的理由。

## 五年資料尚未完成：下一步依據

已驗證的 2021 年 AES 28 個來源日（2021-11-23 至 12-30）、2022 年本機 162 AES 日與 Neon 84 個官方批次來源日，以及 2023–2026 年 Neon 現存歷史資料，屬**不同來源與覆蓋範圍**，不得只加日期數就宣稱 1,990 檔今日上市股票全部達到五年可交易資料。尤其歷史上市、停牌、2022 年小量逐股紀錄、總報酬公司行動與歷史倖存者偏差尚待處理。

**本次只完成可重複的資料庫容量來源驗證。** 既有 owner-private AES／Neon 五年覆蓋盤點與公司行動資料維持原狀；正式庫新增歷史交易日、建立或刪除索引、移除表和修改 LINE 一律未授權。完整模型 BLOCKED，issue #176 仍 OPEN。後續可用本地 AES 的來源日與 Neon 既有來源日期清單做分月／逐股缺口分析，但任何回補都須在免費容量、歷史 PIT 及明確寫入權限驗證後分別批准。
