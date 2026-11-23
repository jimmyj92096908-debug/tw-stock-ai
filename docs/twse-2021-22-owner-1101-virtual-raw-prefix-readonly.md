# 1101 台泥：2021/22 AES＋Neon 虛擬行情來源驗收

## 來源證據與界線

2026-11-23 擁有者已在 Windows PowerShell 5.1 實際完成 2330 單股來源驗收：2021/11/23–2022/12/30 共 274 個歷史來源日、190 個 AES/Neon 重疊股票日期、核心 OHLCV 一致、Neon 寫入 0。此成果**只適用 2330**。

同日 Neon 只讀 SQL 證實，另一檔現有官方上市合資格股票 **1101 台泥**在 2021/11/23–12/30 有 28 個個股價量日，2022/01/03–12/30 有 246 日（合計 274），來源標籤 TWSE_STOCK_DAY；其中 2022 市場 BULK 日期為 84 日。這不是本機 AES 原始檔和 Neon 已通過價量對帳的證明。

1301、2317、2454、2882 的 2022 年 Neon 各只有 84 日、2021 年 0 日；**不可**把它們假稱已經有 274 個 Neon 個股日期。這次僅新增 1101，仍排除下市與 1589。

## 新驗收方式

既有 Python 模組 scripts.twse_2021_22_owner_virtual_2330_prefix_readonly 加入可選參數 --stock-id 1101。預設仍是 2330，原本已成功的 2330 報告 scope、欄位與驗收結果仍維持。

驗收在擁有者電腦上：

1. 完整驗證 2021 品質報告、2022 來源密度報告與原始 AES-GCM 來源（包括完整驗證後才能略過的非 2022 年封存檔）。
2. 正式 Neon 用強制 READ ONLY 交易、參數化 stock_id 查詢，當前上市名單必須有 1092 檔，並排除 1589。
3. 1101 本機 AES 必須有 2021 的 28 個來源日、2022 的 162 個來源日，Neon 官方批次市場來源 84 日，2022 合計 246 日，跨年合計 274 日。
4. 1101 在 Neon 同期間必須有 274 筆日期來源，其中 AES/Neon 重疊 190 個股票日期的 OHLCV 須逐筆以精確 Decimal 相等，不能自行選擇來源或補缺漏。
5. 1101 的私人報告使用獨立 scope：OWNER_2021_22_AES_NEON_1101_VIRTUAL_RAW_PREFIX_READONLY，重疊欄位名稱為 neon_AES_overlapping_stockdate_keys，避免把 1101 誤標為 2330。
6. 截止日期之前才可計算未調整 SMA240，計算及摘要 SHA 只寫入原本機的**新私人 JSON**，不公開價格、密碼、金鑰、原始檔或資料庫 URI。SMA240 不是交易訊號。

## Windows PowerShell 5.1：1101 唯讀本機驗收

此指令只建立全新私人 JSON。**不可覆寫**原有 2330 或其他 AES 報告。先確認環境 DATABASE_URL 已在原本安全的 PowerShell 工作階段設定，且金鑰庫模式不應同時存在另一份 STOCK_ARCHIVE_KEY_HEX。

~~~powershell
& {
    $ErrorActionPreference = 'Stop'
    cd "$HOME\tw-stock-ai"

    git pull --ff-only origin main
    if ($LASTEXITCODE -ne 0) { throw 'Git 更新失敗' }

    if ($env:DATABASE_URL -notmatch '^postgres(ql)?://') {
        throw 'Neon 連線尚未設定'
    }
    if ($env:STOCK_ARCHIVE_KEY_HEX) {
        Write-Host '警告：Vault 模式與目前環境金鑰衝突；不會自動清除'
    }

    $env:TWSE_KEY_GUI_PROMPT = '1'
    $base = "$HOME\TwStockPrivate"
    $q21 = Join-Path $base 'aes-neon-2021-25568-aes-exclusive-source-quality-20261123.json'
    $d22 = Join-Path $base 'aes-neon-2022-current-listed-source-density-20261123.json'
    $out = Join-Path $base 'aes-neon-2021-22-1101-virtual-prefix-20261123.json'

    foreach ($f in @($q21, $d22)) {
        if (!(Test-Path -LiteralPath $f -PathType Leaf)) {
            throw '缺少必要私人來源報告'
        }
    }
    if (Test-Path -LiteralPath $out) {
        throw '1101 私人報告已存在：禁止覆寫'
    }

    $params = @(
        '--stock-id', '1101',
        '--archive-2021', "$HOME\TwStockPrivate\archives",
        '--archive-2022', "$env:LOCALAPPDATA\tw-stock-private\prices",
        '--key-vault', "$env:LOCALAPPDATA\tw-stock-private\history.twsekey",
        '--prior-2021-quality', $q21,
        '--prior-2022-density', $d22,
        '--as-of', '2022-12-30',
        '--out', $out
    )
    & python -m scripts.twse_2021_22_owner_virtual_2330_prefix_readonly @params
    if ($LASTEXITCODE -ne 0) {
        throw '1101 真實來源驗收未通過；只回報上方 diagnostic_stage'
    }

    $r = Get-Content -LiteralPath $out -Raw | ConvertFrom-Json
    if ($r.stock_id -ne '1101' -or
        $r.scope -ne 'OWNER_2021_22_AES_NEON_1101_VIRTUAL_RAW_PREFIX_READONLY' -or
        $r.virtual_2021_22_combined_source_days -ne 274 -or
        $r.virtual_2022_source_calendar_days -ne 246 -or
        $r.neon_AES_overlapping_stockdate_keys -ne 190 -or
        $r.neon_2022_market_bulk_calendar_days_with_stock_bar -ne 84 -or
        $r.neon_AES_overlap_OHLCV_exact -ne $true -or
        $r.as_of_raw_prefix_source_days -ne 274 -or
        $r.as_of_last_240_observed_source_days -ne 240 -or
        $r.source_rows_after_asof_used_in_computation -ne 0 -or
        $r.raw_unadjusted_sma240_is_tradable_signal -ne $false -or
        $r.production_backfill_approved -ne $false -or
        $r.neon_writes -ne 0 -or
        $r.line_messages_sent -ne 0 -or
        $r.model_release -ne 'BLOCKED') {
        throw '1101 來源或安全驗收未通過'
    }

    Write-Host '1101 原始行情來源驗收通過'
    Write-Host "來源日：$($r.virtual_2021_22_combined_source_days)"
    Write-Host "重疊日：$($r.neon_AES_overlapping_stockdate_keys)"
    Write-Host "核心 OHLCV 一致：$($r.neon_AES_overlap_OHLCV_exact)"
    Write-Host "Neon 寫入：$($r.neon_writes)"
    Write-Host "模型狀態：$($r.model_release)"
}
~~~

若失敗，只提供匿名 diagnostic_stage，不能因此把 1101 改成其他股票來源、跳過缺日或補造行情。若 PASS，才可把 1101 真實資料通過紀錄加入 GitHub issue #176。私人 JSON 包含研究 SMA240 與指紋，不可上傳公開 GitHub。

## 仍封鎖

這不是五年原始市場資料完整、2021 年 11 月以前資料完整、歷史 PIT 上市名單、全市場公司行動調整、前瞻獲利驗證或可交易模型的證明。Neon 不增量寫入，LINE 不修改，零付費服務，model_release=BLOCKED。
