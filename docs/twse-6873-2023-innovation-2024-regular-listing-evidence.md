# 6873 泓德能源：2023 創新板上市 → 2024 一般板改列，官方歷史來源日期核對

## 真正原因（已查官方來源）

原先擁有者 2026-11-23 私有正式紀錄 `TWSE_2022_SINGLE_LISTING_DATE_CONFLICT_PRIVATE_EVIDENCE_PASS` 顯示：股票代號 **6873**，Neon 的最早有效官方 TWSE 來源日 **2023-03-06**，現行 TWSE 公開公司基本資料的「上市日期」**2024-09-26**，相差 **570 個日曆日**。本案不應被視為 2023 有不合法上市股價。

官方 TWSE 2023 年歷史上市紀錄 `<https://www.twse.com.tw/company/newlisting?response=html&yy=>` 中，6873 為 **泓德能源-創**，上市買賣日為民國 `112.03.06`（2023-03-06），類別 **創新板**；官方 2024 年新聞稿 `<https://www.twse.com.tw/staticFiles/news/news/tsecnews/8a8216d691e550e301922893bdcd00e5.pdf>` 記載 2024-09-26 **創新板改列一般板**。不是從 TPEx 上櫃轉入 TWSE。

這說明同一證交所中，不同板別的上市日期與上市後改列日期**不能被混為首次上市日**。本研究的 current TWSE listing date 可指現行一般板，而非原始 TWSE 創新板初次交易日；否則會把 2023 年真正的 TWSE 創新板價格誤判為「上市前違規來源」。

## 本機再驗證（新工具）

`scripts.twse_6873_innovation_regular_listing_official_readonly` 不讀取 Neon，也不需要 AES 金鑰，只讀擁有者原本已驗收且仍完整的兩份私有報告：PR #234 `aes-neon-2022-129-official-current-listing-date-20261123.json` 與 PR #235 `aes-neon-2022-single-listing-date-conflict-20261123.json`。檢查 129 檔母體、唯一一檔矛盾的 6873、原官方 HTTPS 公司基本資料來源 SHA256、2023-03-06、2024-09-26、570 日差、Neon 0 寫、LINE 0、`BLOCKED` 均未改變。

只做**一次** TWSE 官方公開歷史上市清單 HTTPS 查詢，限定 exact TWSE 網域和端點、拒絕 HTTP 轉址、限制 6MB 原始回應與 50–2000 條歷史表列；HTML 逐欄讀取 `6873` 唯一官方上市 row，須對上 `泓德能源-創`、上市日 `112.03.06`、末欄 `創新板`，不同立即拒絕。只輸出 SHA256 和結果摘要，不儲存全量來源名錄或行情。

### PowerShell 5.1 執行

```powershell
& {
    $ErrorActionPreference = 'Stop'
    cd "$HOME\tw-stock-ai"
    git pull --ff-only origin main
    if ($LASTEXITCODE -ne 0) { throw 'GitHub 更新失敗' }

    $private = "$HOME\TwStockPrivate"
    $pr234 = Join-Path $private 'aes-neon-2022-129-official-current-listing-date-20261123.json'
    $pr235 = Join-Path $private 'aes-neon-2022-single-listing-date-conflict-20261123.json'
    $out = Join-Path $private 'aes-neon-6873-innovation-to-regular-board-20261123.json'

    if (!(Test-Path $pr234) -or !(Test-Path $pr235)) {
        throw '缺少已正式驗收的 PR234／PR235 私有報告'
    }
    if (Test-Path $out) { throw '輸出檔案已存在，禁止覆寫' }

    python -m scripts.twse_6873_innovation_regular_listing_official_readonly `
        --prior-234-official-report "$pr234" `
        --prior-235-conflict-report "$pr235" `
        --out "$out"
    if ($LASTEXITCODE -ne 0) { throw '6873 創新板轉一般板歷史事件驗收失敗' }
    if (!(Test-Path $out)) { throw '沒有產出私有驗收報告' }

    $r = Get-Content $out -Raw | ConvertFrom-Json
    [PSCustomObject]@{
        股票 = $r.stock_id
        首次TWSE創新板上市 = $r.official_2023_initial_twse_innovation_board_trading_date
        改列一般板 = $r.official_latest_current_regular_board_listing_date
        先前570天來源矛盾已經板別事件核對 = $r.prior_report_source_date_mismatch_reclassified_as_board_transition
        股價逐筆驗證完成 = $r.individual_neon_price_ohlcv_economics_verified
        模型發佈 = $r.model_release
    } | Format-List
}
```

成功狀態為 `TWSE_6873_INNOVATION_TO_REGULAR_LISTING_EVENT_PROVENANCE_PASS`。

本項**只修正歷史市場板別／日期的研究解讀**，沒有自動修正 Neon DB 內容，也不會把 6873 的所有 OHLCV、除權息、總報酬、歷史 PIT 成分或另外 116 檔 2022 內部缺口標示完成。新 JSON 仍保留 `model_release=BLOCKED`、`production_neon_writes=0`、`line_messages_sent=0`、零付費；不修改 LINE、不交易，不納入下市股票或 1589。