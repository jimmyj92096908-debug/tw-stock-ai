# 2021 年 28 個官方 AES＋Neon 來源日零紀錄的 153 檔：當前證交所上市日期核查

## 已驗收證據

2026-11-23 擁有者 Windows 完成 PR #243 真實驗收：`TWSE_2021_28DAY_AES_NEON_STOCK_DATE_UNION_READONLY_PASS`。2021-11-23～2021-12-30 的 28 個已認證原始來源日、當前仍上市 TWSE 共 1,092 檔（排除已下市股票與 1589），AES 為 **26,120 筆股票日期鍵**、Neon 為 **552 筆**，Neon 的 552 全部已在 AES，實際去重聯集仍是 **26,120**。900 檔 28 日都有紀錄，916 檔至少 26 日，**153 檔這 28 個來源日一筆有效來源日期鍵都沒有**。這 153 檔可能在 2021 年尚未上市；不得當作 153 檔歷史行情一定遺漏。

## 本 PR 範圍

新增 `scripts.twse_2021_153_zero_source_current_listing_triage`。必須先讀取**不可覆寫**的 PR #241 2021 AES、原始五年 Neon-only、PR #243 2021 AES＋Neon 精確去重三份私有報告；要與之前 28／1,092／26,120／552／900／916／153 原樣一致。

在擁有者 Windows 重新驗證私有 AES-GCM 原始封存，檢查全檔認證、2021 的 28 個真實來源日、AES 檔案 SHA256 前後未變；只用 Neon **單一 `REPEATABLE READ READ ONLY`** 快照讀取當前官方上市 TWSE 名單與 2021 有效來源的股票／日期鍵，不回傳價量；必須完整重算並與先前私有 PR #241、#243 報告**完全相等**。只有這三個證據全部成立，才取真正 `2021 AES ∪ Neon` 一筆都未出現的股票代號集合，必須恰好 153 檔。

對這 153 檔使用之前已驗證的免費 TWSE 官方 OpenAPI `https://openapi.twse.com.tw/v1/opendata/t187ap03_L` 做**一次**上市公司基本資料查詢，要求官方發布日期不超過 14 天、HTTPS 官方站、公司代號唯一及有效 `上市日期`；比對當前官方**上市日期**落在 **2021 年 11 月 23 日當日或更早**、**2021 年 11 月 24 日至 12 月 30 日**、**2021 年 12 月 31 日**、**2022／2023／2024／2025／2026 年**、**日期缺失或無效**等類別。

注意：**當前 TWSE 上市日期不是首度 IPO 日，也不是 2021 歷史 point-in-time 上市名單**。創新板轉一般板、上櫃轉上市、重新上市等，都可能使現在公告日期晚於原有有效歷史交易紀錄。因此，對上市日落在 2022 年以後的股票也**不能直接宣稱**「2021 沒有上市／沒有交易義務」。上市日早於最後 2021 來源日者，應列入**官方歷史事件與個股行情複核**，不能立刻補 K 線。缺日不代表有效收盤價不存在。

此研究新增只保存在 `TwStockPrivate`、禁止覆寫的私有 JSON。console 僅顯示匿名分組總數；股票代號及當前官方上市日期清單只存在你的私有 JSON。過去所有 PR #241／#243 驗收結果不會變更。零額外付費、不變動 Neon、LINE、正式分數、既有模型；上市歷史 PIT、總報酬與 walk-forward 仍未驗收，正式模型 `BLOCKED`。

## Windows PowerShell 5.1 執行方式

本步要求之前已保存的三份私有報告、AES vault，及目前視窗已安全設定的 `DATABASE_URL`。**不要貼出 Neon URI、AES 金鑰或私有原始行情**。

```powershell
& {
    $ErrorActionPreference = 'Stop'
    cd "$HOME\tw-stock-ai"
    git pull --ff-only origin main
    if ($LASTEXITCODE -ne 0) { throw 'GitHub 更新失敗' }

    if ($env:DATABASE_URL -notmatch '^postgres(ql)?://') {
        throw '請先在本機安全設定 Neon DATABASE_URL'
    }
    $env:TWSE_KEY_GUI_PROMPT = '1'

    $base = "$HOME\TwStockPrivate"
    $prior241 = Join-Path $base 'aes-neon-2021-28day-current-listed-aes-density-20261123.json'
    $prior5y = Join-Path $base 'aes-neon-five-year-current-listed-cohort-20261123.json'
    $prior243 = Join-Path $base 'aes-neon-2021-28day-aes-neon-deduplicated-stockdates-20261123.json'
    $output = Join-Path $base 'aes-neon-2021-153-zero-source-current-listing-triage-20261123.json'

    foreach ($p in @($prior241,$prior5y,$prior243)) {
        if (!(Test-Path $p)) { throw '缺少 2021 來源驗收報告' }
    }
    if (Test-Path $output) { throw '輸出已存在，禁止覆寫' }

    python -m scripts.twse_2021_153_zero_source_current_listing_triage `
        --archive-2021 "$HOME\TwStockPrivate\archives" `
        --key-vault "$env:LOCALAPPDATA\tw-stock-private\history.twsekey" `
        --prior-241-aes-report "$prior241" `
        --prior-five-year-neon-report "$prior5y" `
        --prior-243-union-report "$prior243" `
        --out "$output"
    if ($LASTEXITCODE -ne 0) { throw '2021 年 153 檔上市日期唯讀對帳失敗' }
    if (!(Test-Path $output)) { throw '新報告不存在，禁止標示通過' }

    $r = Get-Content $output -Raw | ConvertFrom-Json
    [PSCustomObject]@{
        去重2021來源股票日期 = $r.prior_revalidated_2021_aes_neon_deduplicated_stock_date_pairs
        完全無2021來源股票 = $r.no_2021_aes_or_neon_source_issuer_count
        需再查官方歷史事件股票 = $r.zero_source_2021_prioritize_manual_historical_listing_research
        模型狀態 = $r.model_release
    } | Format-List
    $r.current_listing_year_and_period_bucket_counts | Format-List
}
```

預期成功狀態：`TWSE_2021_153_ZERO_SOURCE_CURRENT_OFFICIAL_LISTING_TRIAGE_PASS`。如果官方欄位或來源認證改變，程式應回報失敗，並保留既有成功報告；絕不可據此強行推算缺漏、把 153 當成必須回補或修改 Neon。