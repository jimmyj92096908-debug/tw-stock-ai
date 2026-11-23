# 2022 上市 116 檔內部行情來源日期缺口：AES＋Neon 唯讀盤點

## 前置驗收和適用範圍

前次擁有者已在本機成功驗收 PR #232：官方**目前仍上市**且排除 1589 的 TWSE 股票 1,092 檔；2022 年 AES 已認證來源日 162，加 Neon 官方整批來源日 84，合併 246 個**已觀測來源日**。其中 825 檔有全部 246 日來源紀錄；另 129 檔全年無 2022 來源紀錄（後續 129 檔官方目前上市日查核在 2023 年以後），20 檔只缺最初日期，2 檔只缺最後日期，0 檔只缺兩端，**104 檔只有首末筆紀錄之間缺日期、12 檔同時有中間和邊界缺日期，共 116 檔**。

此新流程只對 **104＋12＝116 檔在「有來源紀錄的第一日和最後一日之間」未觀測到行情的情況** 做逐股票／月份／連續缺口形狀統計。這種缺口不代表官方確認該日應有成交，也不能證明資料爬取失敗。可能是歷史停牌、暫停交易、某些交易日沒有可用來源、券商／市場板別紀錄差異或尚未核實的歷史股票身分。不得自動補收盤價／以 0 成交虛構 K 線。

## 精確資料處理

選擇 `--internal-gap-triage`，原有已驗證腳本先重新認證 AES 2022 官方來源原始 SHA、既有 3 份不可覆寫的私有驗收報告與 1,092 股票最新官方名單，再於 Neon 單一 `REPEATABLE READ READ ONLY` 快照中讀取有來源且正價格的 2022 日期、代號和來源標籤；不傳回實際股價。只對 **AES ∪ Neon 的逐檔、逐日來源日期鍵** 計算資料存在性。

產生新的擁有者私有 JSON，包含 116 檔各自代號、首尾實際觀測日、中間無來源日總數、獨立連續缺口段數、最長來源日缺口段及**最多兩段最長缺口的日期示例**；全體每個月份的缺口股票日期對數、影響股票數，以及缺口段長度分布（一日、2–5 日、6 日以上）。只按**已觀測來源日索引**計算段長，不會把休市或未驗證日曆直接當缺口。

必須與 PR #232 的 104／12 分類以及既有名目內部股票日期缺口總數完全相同；資料變更時程式應報錯，不虛構成功報告。舊版報告及 CLI 預設行為保持不變；不額外跑官方網站、Neon 不寫入、LINE 不修改也不發送，沒有付費 API、金鑰不輸出，`model_release=BLOCKED`。**這是排查優先級的研究檔，不是官方已確認必須回補的名單。**

## Windows PowerShell 5.1 本機驗收

Neon URI 只允許設在你原本安全保管的本機環境變數 `DATABASE_URL`，絕不可貼入聊天室或 GitHub。此步同時需要先前本機 AES vault 解密權限。完成只產生新檔，不會覆寫任何成功報告。

```powershell
& {
    $ErrorActionPreference = 'Stop'
    cd "$HOME\tw-stock-ai"
    git pull --ff-only origin main
    if ($LASTEXITCODE -ne 0) { throw 'GitHub 更新失敗' }
    if ($env:DATABASE_URL -notmatch '^postgres(ql)?://') {
        throw '請先在同一 PowerShell 視窗安全設定 Neon DATABASE_URL'
    }

    $env:TWSE_KEY_GUI_PROMPT = '1'
    $base = "$HOME\TwStockPrivate"
    $panel = Join-Path $base 'aes-neon-240-stock-gaps-20261123.json'
    $five = Join-Path $base 'aes-neon-five-year-current-listed-cohort-20261123.json'
    $overlay = Join-Path $base 'aes-neon-2022-five-year-source-overlay-20261123.json'
    $out = Join-Path $base 'aes-neon-2022-116-internal-source-gap-triage-20261123.json'
    foreach ($f in @($panel,$five,$overlay)) {
        if (!(Test-Path $f)) { throw '缺少先前驗收報告' }
    }
    if (Test-Path $out) { throw '輸出檔案已存在，禁止覆寫' }

    python -m scripts.twse_2022_aes_neon_eligible_density_readonly `
        --archive-2022 "$env:LOCALAPPDATA\tw-stock-private\prices" `
        --key-vault "$env:LOCALAPPDATA\tw-stock-private\history.twsekey" `
        --source-panel-report "$panel" `
        --five-year-neon-report "$five" `
        --prior-overlay-report "$overlay" `
        --internal-gap-triage `
        --out "$out"
    if ($LASTEXITCODE -ne 0) { throw '116 檔缺口分布唯讀驗收失敗' }
    if (!(Test-Path $out)) { throw '新報告未產生' }

    $r = Get-Content $out -Raw | ConvertFrom-Json
    $d = $r.owner_private_2022_116_internal_source_absence_triage
    $d.source_observation_gap_count_signatures | Format-List
    $d.monthly_internal_unobserved_eligible_stock_source_pairs |
        Format-Table -AutoSize
    $d.private_2022_current_stock_internal_absence_research_rows |
        Select-Object -First 10 stock_id, observation_signature,
            internal_unobserved_source_day_count,
            longest_internal_absence_run_source_days |
        Format-Table -AutoSize
}
```

成功狀態：`TWSE_2022_116_INTERNAL_SOURCE_ABSENCE_TRIAGE_READONLY_PASS`。**請只貼終端機彙總輸出**，不要貼 Neon 連線網址、AES 金鑰或完整私有 JSON。

下一步要針對真正需要優先查看的股票／日期，在官方 2022 年停牌、恢復交易、原始 TWSE 單股交易紀錄與板別異動中查證；任何沒有官方對應交易義務的日期都不能為了提升覆蓋率而填充虛擬價格。研究中的歷史 PIT、生存者偏差、公司行動、調整後報酬、五年資料、樣本外 walk-forward 均尚未通過；正式模型維持 `BLOCKED`。