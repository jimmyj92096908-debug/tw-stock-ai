# 2021-11-23～12-30 的 28 日：AES＋Neon 逐股票／日期真正去重聯集

## 前置 Windows 真實驗收已通過

2026-11-23 擁有者 PR #241 本機執行 `TWSE_2021_ALL_28_AES_CURRENT_COHORT_DENSITY_READONLY_PASS`：證交所 28 個來源日全數有經 AES 認證的官方行情資料，2026 年仍上市 TWSE 1,092 檔（已排除下市、1589），其中 **26,120** 個有效 AES 股票日期組合；**900** 檔全部 28 日有紀錄、**916** 檔至少 26 日、**153** 檔沒有 2021 AES 紀錄。11 月 6 日／5,573 筆，12 月 22 日／20,547 筆。先前 PR #225 Neon-only 同一 2021 起始視窗已有 **28 天、552 筆**有效 source stock-days，但不含本機 AES，因此 26,120＋552 是**未去重相加，不是已確定的可用總量**。

## 本次 PR 的真實任務

在本人 Windows 電腦完整重認證 2021 AES 原始檔（包括完整 AES-GCM chunk/footer、來源價量合法性、2330 錨點、逐檔日期鍵與 SHA256 檔案 byte hash 前後相同）；與原 PR #241 **完整私有 JSON** 重新計算做嚴格全內容相等比較，任何來源變動立即失敗。

在同一 Neon `REPEATABLE READ READ ONLY` transaction 只讀取官方最新 TWSE 上市名單（排除 1589、下市及 `model_stock_exclusions`）與 2021-11-23～12-30 之間 `daily_prices` 的 `TWSE_MI_INDEX_ALLBUT0999` 或 `TWSE_STOCK_DAY`、`close>0` 且 `volume>=0` 的**股票代號／日期／來源標籤**。固定前次 Neon 2021 28 日與 552 有效紀錄。程式拒絕未知日期、未知股票、重複 `(stock_id,trade_date)`、未知 source、來源紀錄過多，以及先前 AES 或 Neon 數量不一致。

用 `(stock_id,trade_date)` 去重計算 AES 26,120 和 Neon 552 的真正**交集與差集、去重聯集**。月度輸出分解 AES、Neon、重複、Neon 額外來源與合併後有效股票日期組合；全體 1,092 檔統計 0–28 日日期數分布、28/28、至少 26/28、0/28 檔數，核對來源日均合法、全數加總守恆。

**注意：這是「原始來源有無該股票日期」驗證，不是相同日期的兩個來源價量是否相符，也不是已修復正式 Neon 資料。** 2021 AES 加密檔一直留在擁有者本機，絕不搬回 Neon；某檔現今上市但 2021 年無來源，可能是當時尚未上市，不能認定缺漏、合成 K 線或把下市股票納入。模型五年行情除權息、減資調整、歷史 PIT、真實 SMA/報酬、樣本外 walk-forward 仍為 `BLOCKED`。

## Windows PowerShell 5.1 本機執行

需要既有安全本機環境變數 `$env:DATABASE_URL`，不須重新公開或回傳連線字串；AES 密碼用 GUI 視窗，絕不能傳到 GitHub 或聊天室。只有使用者在真實 Windows 成功驗收後，才標示聯集完成。

```powershell
& {
    $ErrorActionPreference = 'Stop'
    cd "$HOME\tw-stock-ai"
    git pull --ff-only origin main
    if ($LASTEXITCODE -ne 0) { throw 'GitHub 更新失敗' }
    if ($env:DATABASE_URL -notmatch '^postgres(ql)?://') {
        throw '請先在目前 PowerShell 視窗安全設定 Neon DATABASE_URL'
    }
    $env:TWSE_KEY_GUI_PROMPT = '1'
    $base = "$HOME\TwStockPrivate"
    $baseline = Join-Path $base 'aes-neon-five-year-current-listed-cohort-20261123.json'
    $aes = Join-Path $base 'aes-neon-2021-28day-current-listed-aes-density-20261123.json'
    $out = Join-Path $base 'aes-neon-2021-28day-aes-neon-dedup-current-listed-20261123.json'

    foreach ($f in @($baseline,$aes)) {
        if (!(Test-Path $f)) { throw '缺少已驗收 PR #241 或五年 Neon 基準報告' }
    }
    if (Test-Path $out) { throw '新輸出報告已存在，禁止覆寫' }

    python -m scripts.twse_2021_28day_aes_neon_stock_date_union_readonly `
        --archive-2021 "$HOME\TwStockPrivate\archives" `
        --key-vault "$env:LOCALAPPDATA\tw-stock-private\history.twsekey" `
        --five-year-neon-report "$baseline" `
        --prior-241-aes-report "$aes" `
        --out "$out"

    if ($LASTEXITCODE -ne 0) { throw '2021 AES＋Neon 逐股票日期聯集驗收失敗' }
    if (!(Test-Path $out)) { throw '未產生新的私有聯集報告' }
    $r = Get-Content $out -Raw | ConvertFrom-Json
    [PSCustomObject]@{
        AES股票日期 = $r.aes_current_stock_source_date_pairs
        Neon股票日期 = $r.neon_current_stock_source_date_pairs
        重疊已去重 = $r.duplicated_aes_neon_current_stock_date_pairs
        Neon真正增加 = $r.new_neon_current_stock_date_pairs_outside_aes
        合併後唯一股票日期 = $r.unique_aes_plus_neon_2021_stock_date_pairs
        完整28日股票數 = $r.aes_plus_neon_current_stocks_with_all_28_source_days
        至少26日股票數 = $r.aes_plus_neon_current_stocks_with_at_least_26_source_days
        完全無2021來源股票數 = $r.aes_plus_neon_current_stocks_with_zero_2021_source_days
        模型狀態 = $r.model_release
    } | Format-List
    $r.monthly_aes_neon_source_stock_date_union_density | Format-List
}
```

預期成功狀態：`TWSE_2021_ALL_28_AES_NEON_DEDUPED_CURRENT_COHORT_STOCK_DATE_UNION_PASS`；打印的來源紀錄筆數只有**實際 Windows 驗收成功之後**才可信。GitHub 專項及整體 CI 使用刻意設計的**合成** 26,120 AES＋552 Neon 來源鍵：包含 547 重疊與 5 額外來源組合，僅為測試去重公式，**不是實際市場結果**。

零額外付費、Neon 0 寫入、LINE 0 發送、不納入下市或 1589、既有任何成功報告不覆寫，模型正式發布仍 `BLOCKED`。