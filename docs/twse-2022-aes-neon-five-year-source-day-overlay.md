# 2022 TWSE 本機 AES＋Neon 五年盤點對帳（只比對已驗證日期）

## 背景：2026-11-23 兩份擁有者本機驗收

- 舊 `AES_NEON_READONLY_240_PANEL_AUDIT_PASS`：2022 年 162 個本機 AES 驗證官方來源日期、Neon **84 個官方整批行情日期**，兩組來源日期沒有重疊；合併是 246 個已觀測的 2022 來源日。先前固定 20 股票的「每個市場日均有價格」RAW SMA240 為 18/20；另外兩檔有經獨立驗證的真實停牌，不准造假 K 線。
- 新 `TWSE_TPEX_FIVE_YEAR_NEON_ONLY_COHORT_BASELINE_PASS`：目前官方在市股票共 1,990 檔（TWSE 1,092、TPEx 898，排除 1589），Neon 至少 240 個個股有效日期者 1,908 檔，至少 1,000 日期者 1,686 檔；2022 TWSE 有任一 Neon 有效行情日期 246 日，卻只有 84 日有至少 500 檔目前仍上市股行情；2022 TPEx 246 日均達 500 檔。**Neon 的 246「任一有紀錄」不是 246「全市場 K 線完整」。**

以上是**兩份原始私有驗收報告**，本工具不重新解密源資料，不連接 Neon、不連 TWSE 網站，只做報告間的數學／狀態一致性驗證。

## 本工具可證明及無法證明的事

可安全辨認：2022 TWSE 原始官方來源的既有本機 AES（162 個已驗證來源日期）＋原 Neon 官方批次來源（84 日期）**來源日期去重合計 246**；這是已認證來源日曆的合併，不是個股全天候 2022 年 OHLCV 完整度、也不是官方獨立完整市場交易日曆的保證。

不可以宣稱：

- Neon 84 個大批次來源日**已逐日期驗證**等於五年盤點中「至少 500 檔」的 84 日；目前只有**總數相等**，尚未逐日對帳。
- AES 的 162 個來源日對**全部 1,092 檔目前上市股**都各有 500 檔以上有效價格；不能只憑日期數推斷股數完整性。
- 本機 AES 的 162 日全部都**完全不存在 Neon**；已知 Neon 2022 年仍有許多稀疏逐股紀錄，僅能說 162 日尚未作為全部當前股票的高密度批次資料存在於 Neon。
- 2021 年 Neon 有效日期 28 日代表當年 TWSE 官方全市場來源完整（2021 年每日期存量僅少量股票）。
- 目前上市／上櫃母體不存在生存者偏差，或 2021–2026 除權息、拆併股、總報酬與模型 Walk-forward 已完成。

## Windows PowerShell：離線彙整（不需要 Neon URI／AES 金鑰）

請直接使用已成功建立的 **兩份本機私有報告**，不要覆寫，不需要重跑任何耗時的 AES 來源鑑定。

```powershell
cd "$HOME\tw-stock-ai"
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw '更新 GitHub 失敗' }

$base = "$HOME\TwStockPrivate"
$panel = Join-Path $base 'aes-neon-240-stock-gaps-20261123.json'
$fiveYear = Join-Path $base 'aes-neon-five-year-current-listed-cohort-20261123.json'
$out = Join-Path $base 'aes-neon-2022-five-year-source-overlay-20261123.json'
if (!(Test-Path $panel) -or !(Test-Path $fiveYear) -or (Test-Path $out)) {
    throw '前置報告不存在或新輸出已存在'
}

python -m scripts.twse_2022_aes_neon_five_year_overlay_offline `
    --prior-2022-panel "$panel" `
    --neon-five-year-report "$fiveYear" `
    --out "$out"
if ($LASTEXITCODE -ne 0) { throw '2022 AES + Neon 來源日期對帳未通過' }

$r = Get-Content $out -Raw | ConvertFrom-Json
[PSCustomObject]@{
    本機2022_AES來源日 = $r.twse_2022_authenticated_local_aes_source_days
    Neon2022官方批次來源日 = $r.twse_2022_verified_neon_official_bulk_source_days
    來源日期重疊數 = $r.twse_2022_prior_source_calendar_date_overlap
    已觀測來源日去重合計 = $r.twse_2022_deduplicated_observed_source_calendar_dates
    全上市股票逐日完整 = $r.virtual_2022_twse_full_market_per_stock_coverage_verified
} | Format-List
```

即使報告結果通過，下一步仍必須先在使用者私有電腦內重新驗證**逐日、逐檔的 AES 來源資料與 Neon 官方日期及數量是否精確對帳**，確保當前仍上市 1,092 檔的實際覆蓋。不要為了填滿日期而製造股票停牌價格、假上市歷史或重複主鍵。

此工具不需要金鑰、網路或任何 API；不修改資料庫、不改 LINE、不產生訊號、不收費，不碰下市股票與 1589。報告標示 `BLOCKED`。