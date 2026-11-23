# 2021 年 28 個 AES＋Neon 真實來源股票日期鍵去重聯集（僅唯讀）

## 實際已驗證的 2026-11-23 基準

**PR #241 擁有者 Windows 真實驗收通過**：`TWSE_2021_ALL_28_AES_CURRENT_COHORT_DENSITY_READONLY_PASS`。2021-11-23 至 2021-12-30 的 28 個已認證 AES 原始官方來源日含 **26,120** 筆符合「2026 年目前仍上市且排除 1589」的 TWSE 股票日期鍵。1,092 檔現今上市股票中，900 檔在全部 28 日有紀錄、916 檔至少 26 日、153 檔全年 28 個來源日一筆都沒有。2021 年 11 月 6 個來源日 5,573 筆，12 月 22 個來源日 20,547 筆。

同一滾動五年 Neon-only 官方已驗收 2021 28 個來源日有 **552 筆**符合當前母體的有效股票日期鍵。先前資料庫不包含私有 AES，因此不能把 552 筆誤當成 2021 年只有 552 筆歷史行情；但也不能把 26,120＋552 當成 26,672 筆已去重行情，因可能同股票同日期重疊。PR #241 明確標示 `2021_current_cohort_aes_neon_deduplicated_stock_day_union_verified=false`，因此本階段須精確算股票代號與來源日期複合鍵的集合聯集。

## 這個 PR 改善的驗證方式

新 `scripts.twse_2021_28day_aes_neon_stockdate_union_readonly` 必須讀取原本兩份不可覆寫的私有報告：2021 AES 28 日覆蓋率 PR #241、五年 Neon-only 原始基準。先驗證它們原先的 **2021-11-23～2026-11-23** 五年基準、1,092 現今上市 TWSE 股票、原始 AES 26,120、Neon 552、900／916／153 原樣一致且 `model_release=BLOCKED`。

接著僅在 owner Windows 透過既有 vault 解密驗證 2021 全部私有 AES 封存，包含官方 2330 錨定、2021 28 個來源日期、價格為真實正價、完整 AES-GCM footer／SHA。對同一受控 Neon `REPEATABLE READ READ ONLY` 快照中目前官方上市且不含 1589 的股票名單，讀取 2021 28 日的來源股票日期鍵（只選取 `trade_date`, `stock_id`, `source`，且檢查儲存有正收盤價與非負成交量）。Neon 2021 來源必須恰好 552 筆、在全部 28 個日期都有紀錄，否則拒絕輸出成功。

實際用集合 `AES ∪ Neon`、`AES ∩ Neon` 算出兩者重複筆數、AES 獨有筆數、Neon 獨有筆數與最終不重複股票日期鍵數，進一步重算 0–28 日每檔出現日數直方圖與 11／12 月份彙總。**與原 PR241 完整報告逐欄重新核算且完全一致**才可認證，新增結果不能覆寫之前報告。

這次只核對**來源日期鍵**，不是所有原始價量都與 Neon 經濟意義相同；不會自動匯入私人 AES 到正式 Neon，也不會修補 1472／1538 在 2022 年官方沒有正價的 15 日期。2021 的 153 檔無來源可能是當時尚未上市、轉板、停牌或其它合法原因；真正歷史 point-in-time 上市名單仍待確認。2022–2026 真正全面逐檔行情、配息／減資調整報酬、資料洩漏及 walk-forward 測試尚不能視為完成，正式模型 `BLOCKED`。

## Windows PowerShell 5.1 一次性本機驗收

需你的本機現有 Neon 連線環境變數 `DATABASE_URL`，請勿把 PostgreSQL URI、AES vault 密碼、私有來源原始資料貼到聊天室或 GitHub。新輸出只放 `TwStockPrivate` 且禁止覆寫。不新增付費服務，不傳輸原始價量到外部。

```powershell
& {
    $ErrorActionPreference = 'Stop'
    cd "$HOME\tw-stock-ai"
    git pull --ff-only origin main
    if ($LASTEXITCODE -ne 0) { throw 'GitHub 更新失敗' }

    if ($env:DATABASE_URL -notmatch '^postgres(ql)?://') {
        throw '請在此 PowerShell 視窗安全設定既有 Neon DATABASE_URL'
    }
    $env:TWSE_KEY_GUI_PROMPT = '1'
    $base = "$HOME\TwStockPrivate"
    $priorAes = Join-Path $base 'aes-neon-2021-28day-current-listed-aes-density-20261123.json'
    $prior5Y = Join-Path $base 'aes-neon-five-year-current-listed-cohort-20261123.json'
    $out = Join-Path $base 'aes-neon-2021-28day-aes-neon-deduplicated-stockdates-20261123.json'

    foreach ($f in @($priorAes,$prior5Y)) {
        if (!(Test-Path $f)) { throw '缺少 PR241 或原始五年 Neon 已驗收報告' }
    }
    if (Test-Path $out) { throw '新輸出已存在，禁止覆寫' }

    python -m scripts.twse_2021_28day_aes_neon_stockdate_union_readonly `
        --archive-2021 "$HOME\TwStockPrivate\archives" `
        --key-vault "$env:LOCALAPPDATA\tw-stock-private\history.twsekey" `
        --prior-241-aes-report "$priorAes" `
        --prior-five-year-neon-report "$prior5Y" `
        --out "$out"

    if ($LASTEXITCODE -ne 0) { throw '2021 AES + Neon 股票來源日去重驗收失敗' }
    if (!(Test-Path $out)) { throw '沒有產出受控驗收報告' }

    $r = Get-Content $out -Raw | ConvertFrom-Json
    [PSCustomObject]@{
        AES原始股票日期 = $r.prior_2021_aes_source_stock_date_pairs
        Neon原始股票日期 = $r.prior_2021_neon_source_stock_date_pairs
        相同股票同日期重複 = $r.aes_neon_overlapping_source_stock_date_pairs
        Neon獨有股票日期 = $r.neon_exclusive_source_stock_date_pairs
        最終去重股票日期 = $r.actual_deduplicated_aes_neon_stock_date_pairs
        完整28日來源股票 = $r.current_stocks_with_all_28_original_source_dates
        完全沒有來源股票 = $r.current_stocks_with_no_source_day_in_2021
        模型發布狀態 = $r.model_release
    } | Format-List
    $r.source_monthly_deduplicated_density | Format-List
}
```

預期成功狀態：`TWSE_2021_28DAY_AES_NEON_STOCK_DATE_UNION_READONLY_PASS`。CI 中只能驗證**合成股票日期鍵**，絕不會讀到本機 AES、Neon URI 或真實驗收報告。本機真實結果通過前，不得聲稱 AES＋Neon 完整聯集已驗收。

依然維持 0 Neon 寫入、0 LINE 發送、0 額外付費、排除下市與 1589、無價格插值，正式預測模型 `BLOCKED`。