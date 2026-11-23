# 2021 年 11–12 月全部 28 個官方來源日：2026 仍上市 TWSE 股票 AES 逐檔密度（唯讀）

## 為何這是五年模型的重要關卡

以 2026-11-23 為基準，**往前滾動五年從 2021-11-23 開始**，不是從 2021-01-01 開始，因此五年計算本來就不要求把 2021 年 1–10 月補進這份 2026-11-23 的滾動五年資料。已有的 2021 完整官方交易來源基準是 2021-11-23～2021-12-30 共 **28 個交易來源日**，原 AES 來源封存在使用者 Windows `TwStockPrivate\archives`；先前 Neon-only 2021 也觀測到 28 個日，但僅有 552 個 current-listed TWSE 有效股票日期鍵（不是全市場）。不能混淆「Neon 裡的 2021 價格筆數少」與「完整私人 AES 加 Neon 歷史資料不存在」。

已通過 PR #240 實際核查：2022 年 30 段長缺口中有 28 段官方單月股票日行情沒有對應日期列；另 2 段（1472、1538）在 2022 年共有 15 個 official STOCK_DAY／MI_INDEX 股票日期列，但**兩組官方來源都沒有可驗證的正收盤價**。這些不應被虛構成可直接回補的 K 棒，更不能把來源缺席直接當正式停牌。由於 PR #240 完成後收益逐漸下降，下一步先擴大五年模型真正的 2021 起始期間逐股票完整性研究。

## 執行內容

新 `scripts.twse_2021_28day_aes_current_cohort_density_readonly`，首先校驗既有 `aes-neon-five-year-current-listed-cohort-20261123.json` 必須仍為 2021-11-23～2026-11-23 基線、Neon TWSE 2021 有 28 天、552 筆有效價格鍵、當前 TWSE 排除 1589 後 1,092 檔、Neon 寫入 0／LINE 0／model_release BLOCKED。

接著只在你的 Windows 私有電腦中用 vault 解密並**驗證所有 2021 AES 檔案每筆資料與完整 footer SHA**（會二次重驗，期間原 AES 檔案 bytes 摘要必須未變），要求 2021 真實官方來源日恰好是 28 個、所有交易日原始檔有至少 500 檔真實股票價格來源且有 2330 錨點。最後僅向 Neon 做**一次受控 `REPEATABLE READ READ ONLY` 交易**取得最新官方目前上市 TWSE、排除下市及 1589 的 1,092 檔股票代號清單，與 AES 中**有效來源**的股票／日期鍵做記憶體去重，輸出每個來源日的股票數、當月彙總與每檔觀測 0–28 日的直方圖。

**這個新研究報告不會**從 Neon 搬資料到 AES，不會重抓行情，不會推斷每個 2026 上市股票在 2021 也有上市資格，不會因無法找到某股 2021 原始交易日而自動補價。2021 AES+Neon 的逐股票日期聯集尚未直接計算，這次只證明已有的原 AES 覆蓋率。完整 2022–2026 stock panel、公司行動 total-return 及 walk-forward 預測測試仍未驗收。

## Windows PowerShell 5.1 本機命令

Neon 連線網址只放在既有本機工作階段的 `DATABASE_URL`；不能把 URI 或 AES vault 密碼上傳 GitHub 或本聊天室。2021 AES 檔案位於以前已成功封存使用的 `$HOME\TwStockPrivate\archives`，與 2022 AES 不同路徑。

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
    $old = "$HOME\TwStockPrivate\aes-neon-five-year-current-listed-cohort-20261123.json"
    $out = "$HOME\TwStockPrivate\aes-neon-2021-28day-current-listed-aes-density-20261123.json"
    if (!(Test-Path $old)) { throw '缺少先前已驗收的五年 Neon-only 報告' }
    if (Test-Path $out) { throw '新報告已存在，禁止覆寫' }

    python -m scripts.twse_2021_28day_aes_current_cohort_density_readonly `
        --archive-2021 "$HOME\TwStockPrivate\archives" `
        --key-vault "$env:LOCALAPPDATA\tw-stock-private\history.twsekey" `
        --five-year-neon-report "$old" `
        --out "$out"
    if ($LASTEXITCODE -ne 0) { throw '2021 28 個 AES 來源日逐檔密度驗收未通過' }
    if (!(Test-Path $out)) { throw '沒有產出新的私有驗收報告' }
    $r = Get-Content $out -Raw | ConvertFrom-Json
    [PSCustomObject]@{
        來源日期 = $r.authenticated_2021_owner_aes_source_days
        現今上市股票數 = $r.'2021_aes_current_2026_twse_survivor_eligible_count'
        AES實際股票日期紀錄 = $r.'2021_aes_current_2026_twse_stock_date_presence_pairs'
        完整28日的股票 = $r.'2021_2026_current_stocks_with_all_28_observed_source_days'
        至少26日的股票 = $r.'2021_2026_current_stocks_with_at_least_26_of_28_days'
        2021來源日完全沒有紀錄的現今上市股票 = $r.'2021_2026_current_stocks_with_no_2021_source_day'
        模型狀態 = $r.model_release
    } | Format-List
    $r.monthly_authenticated_2021_current_cohort_source_density | Format-List
}
```

成功狀態：`TWSE_2021_ALL_28_AES_CURRENT_COHORT_DENSITY_READONLY_PASS`。這次 GitHub CI 只檢驗合成測試；**必須等你電腦真正執行成功，才能標示私有 AES 覆蓋率完成**。

所有價量只留本機驗證運算記憶體，報告只有匿名彙總與 SHA256，不含個股價位與股票名單。Neon 0 寫入、LINE 0 發送、免費、排除下市股票及 1589；模型正式發布 `BLOCKED`。