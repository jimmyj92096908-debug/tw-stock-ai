# 2021 官方 AES vs Neon 552 個共同來源股票日期：逐欄位經濟價量唯讀核查

## 為何要做

2026-11-23 擁有者已驗收 2021-11-23～2021-12-30 共 28 日目前仍上市 TWSE 來源股票日期聯集：AES 26,120、Neon 552、重複 552、Neon 獨有 0、AES 獨有 25,568。這只是「股票＋日期主鍵」重疊，**並不能證明 552 筆開高低收、成交量、成交值都與原始 AES 完全一致**。

正式 Neon 目前這 552 筆來源標籤為 TWSE_STOCK_DAY；AES 使用原始官方 MI_INDEX_ALLBUT0999。在 2026-11-23 的唯讀 SQL 快照中，552 筆中的 7 筆 price_change 為 NULL。不同官方來源的次要欄位可能不一致：必須將「價量不相符」和「來源欄位缺值、不能比較」區分，不能用 0 填補或把缺值視為相等。

## 新增內容

- scripts/twse_2021_552_aes_neon_ohlcv_overlap_readonly.py：擁有者 Windows 執行，先驗證既有私有 AES＋Neon 去重報告。重新完整驗證 2021 AES-GCM 封存中 28 個真實來源交易日，要求來源數與官方當前存活股票名單吻合。
- Neon 以 REPEATABLE READ READ ONLY + default_transaction_read_only=on 的單一快照讀取最新 14 日官方上市名單和 2021-11-23～2021-12-30 的 552 筆有效來源紀錄，排除 1589 與 model_stock_exclusions。不修改任何正式表，不查 LINE。
- 僅比對逐一相同股票、相同交易日期的 open/high/low/close/volume（核心）及 turnover/price_change/transactions（擴充）；使用 Decimal 原始型別，不做浮點數轉換、補值或人為容差。
- private 報告包含匿名統計以及**只有在擁有者本機**保存的例外股票與日期，不輸出原始價量、Neon URL 或 AES 金鑰。對帳可以得到「部分差異」，即程式正常完成不代表 552 個欄位全相等。
- 不核准把 AES-only 的 25,568 個來源日期鍵轉成 25,568 筆 OHLCV 寫入；這還需逐筆交易可用性、原始價量和歷史 point-in-time 上市資格驗證。
- 始終保持 safe_to_write_production_history=false、model_release=BLOCKED。無額外付費、資料刪除、LINE 變更或訂單。

## Windows PowerShell 5.1 真實驗收

在原本已有 DATABASE_URL、AES vault 和先前驗收 JSON 的擁有者電腦執行。不能把私有報告寫到 Git checkout，也不得覆寫同名檔案。

~~~powershell
& {
    $ErrorActionPreference = 'Stop'
    cd "$HOME\tw-stock-ai"
    git pull --ff-only origin main
    if ($LASTEXITCODE -ne 0) { throw 'GitHub 更新失敗' }

    if ($env:DATABASE_URL -notmatch '^postgres(ql)?://') {
        throw 'Neon DATABASE_URL 未安全設定'
    }
    $env:TWSE_KEY_GUI_PROMPT = '1'
    $base = "$HOME\TwStockPrivate"
    $prior = Join-Path $base 'aes-neon-2021-28day-aes-neon-deduplicated-stockdates-20261123.json'
    $output = Join-Path $base 'aes-neon-2021-552-overlap-ohlcv-parity-20261123.json'
    if (!(Test-Path -LiteralPath $prior -PathType Leaf)) {
        throw '缺少已驗收的 PR #243 AES-Neon 去重報告'
    }
    if (Test-Path -LiteralPath $output) {
        throw '新報告已存在，禁止覆寫'
    }

    $args2021 = @(
        '--archive-2021', "$HOME\TwStockPrivate\archives",
        '--key-vault', "$env:LOCALAPPDATA\tw-stock-private\history.twsekey",
        '--prior-union', $prior,
        '--out', $output
    )
    & python -m scripts.twse_2021_552_aes_neon_ohlcv_overlap_readonly @args2021
    if ($LASTEXITCODE -ne 0) { throw '原始 AES / Neon 552 筆價量唯讀核查失敗' }
    if (!(Test-Path -LiteralPath $output -PathType Leaf)) {
        throw '沒有產生逐筆經濟價量驗收報告'
    }

    $r = Get-Content -LiteralPath $output -Raw | ConvertFrom-Json
    if ($r.exact_source_key_overlap -ne 552 -or
        $r.safe_to_write_production_history -ne $false -or
        $r.model_release -ne 'BLOCKED' -or
        $r.neon_writes -ne 0) {
        throw '來源基準或安全欄位與既有驗收不符'
    }
    Write-Host "共同股票日期來源鍵：$($r.exact_source_key_overlap)"
    Write-Host "核心 OHLCV 相符：$($r.critical_ohlcv_field_matches)"
    Write-Host "核心 OHLCV 不同或無法驗證：$($r.critical_ohlcv_mismatch_or_unverifiable_rows)"
    Write-Host "全部擴充欄位相符：$($r.complete_economic_field_matches)"
    Write-Host "來源價量允許正式回補：$($r.safe_to_write_production_history)"
    $r.per_field_different_or_unverifiable_counts | Format-List
}
~~~

成功執行會輸出 TWSE_2021_552_AES_NEON_OHLCV_OVERLAP_READONLY_PASS。這只表示對帳**正常完成**，不是全部一致。若出現不同欄位，需獨立研究其來源與單位，不得修改資料使其硬性相等。

## 尚未完成

- 本機 AES 對帳與私人例外報告需要擁有者實際執行；GitHub Actions 不接觸資料庫或真實 AES 原檔。
- 2021 AES-only 25,568 個日期鍵還不是經核准的可插入行情；歷史 PIT、事件調整、逐筆 2022 資料對帳及 Neon 容量限制仍待解決。
- 舊 Ridge 模型保留期失敗，不能用這項資料品質測試替代真正未知時期的獨立績效證據。
