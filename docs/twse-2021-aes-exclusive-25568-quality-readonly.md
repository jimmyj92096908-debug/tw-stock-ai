# 2021 原始 AES 25,568 個獨有來源鍵：完整價量品質、無寫入預檢

## 已由擁有者在 2026-11-23 實際完成的驗收

執行 PR #248 工具後，擁有者提供原始 Windows PowerShell 輸出：
- TWSE_2021_552_AES_NEON_OHLCV_OVERLAP_READONLY_PASS
- 2021 AES 26,120 個來源股票日期鍵與 Neon 552 鍵完全重疊；**552/552 核心 open/high/low/close/volume 完全一致，0 筆不同或無法驗證**。
- 545/552 的所有八項擴充經濟欄位完全一致；另 7 筆 Neon price_change 為 NULL，屬「無法驗證」，不是已證實的價差。
- 剩下 AES 獨有 25,568 鍵此前只經來源日期／主鍵驗證，**未證明全部 OHLCV 可安全入庫**。

這份新工具重新執行上述 552 筆比對、先前官方 AES-GCM 原始檔完整認證與來源日驗證，進而計算 25,568 筆 AES 獨有來源的**開高低收、成交量必填欄位的合理性**、每月與每日來源鍵數量、可選成交資訊缺值數。若原始 2021 資料或 Neon 的 552 筆已變動、前次真實驗收報告被更改，工具會停止而不覆寫。

本工具僅驗證**原始來源欄位品質**；它不能代替個股逐筆上市／下市的 historical point-in-time 交易資格、除權息／減資價調整、未見樣本模型驗證或 Neon 完整備份。程式永遠回傳 production_backfill_approved=false、model_release=BLOCKED。無新資料庫寫入、付費、LINE 變更或交易動作。不得把 25,568 視為已核准可 INSERT 的價格筆數。

## Windows PowerShell 5.1 真實本機核對

前置條件：擁有者本機已有未洩露的 Neon DATABASE_URL、私有 AES vault、PR #243 的去重 JSON 與**剛完成真實驗收**的 PR #248 552 筆對帳 JSON。**不得上傳原始私有 JSON、金鑰或資料庫 URI 至 GitHub、聊天或 CI**。本工具不要求重新產生既有報告，任何新檔禁止覆寫。

~~~powershell
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
    $union = Join-Path $base 'aes-neon-2021-28day-aes-neon-deduplicated-stockdates-20261123.json'
    $parity = Join-Path $base 'aes-neon-2021-552-overlap-ohlcv-parity-20261123.json'
    $output = Join-Path $base 'aes-neon-2021-25568-aes-exclusive-source-quality-20261123.json'

    foreach ($file in @($union, $parity)) {
        if (!(Test-Path -LiteralPath $file -PathType Leaf)) {
            throw '缺少已核實的前置 AES 與 Neon 驗收 JSON'
        }
    }
    if (Test-Path -LiteralPath $output) {
        throw '安全禁止覆寫新報告'
    }

    $params = @(
        '--archive-2021', "$HOME\TwStockPrivate\archives",
        '--key-vault', "$env:LOCALAPPDATA\tw-stock-private\history.twsekey",
        '--prior-union', $union,
        '--prior-552-parity', $parity,
        '--out', $output
    )
    & python -m scripts.twse_2021_aes_exclusive_quality_readonly @params
    if ($LASTEXITCODE -ne 0) { throw '2021 AES 獨有來源價量品質驗收失敗' }
    if (!(Test-Path -LiteralPath $output -PathType Leaf)) {
        throw '沒有產出驗收報告'
    }
    $r = Get-Content -LiteralPath $output -Raw | ConvertFrom-Json
    if ($r.aes_exclusive_stockdate_source_keys -ne 25568 -or
        $r.original_552_overlap_critical_ohlcv_parity_revalidated -ne $true -or
        $r.production_backfill_approved -ne $false -or
        $r.model_release -ne 'BLOCKED' -or
        $r.neon_writes -ne 0) {
        throw '來源清點未通過安全條件'
    }

    Write-Host "2021 AES 獨有來源鍵：$($r.aes_exclusive_stockdate_source_keys)"
    Write-Host "獨有來源鍵核心價量合理：$($r.aes_exclusive_source_keys_with_sane_core_ohlcv)"
    Write-Host "不同股票檔數：$($r.aes_exclusive_distinct_current_survivor_issuers)"
    Write-Host "Neon 552 筆重新核對：$($r.original_552_overlap_critical_ohlcv_parity_revalidated)"
    Write-Host "正式回補允許：$($r.production_backfill_approved)"
    $r.aes_exclusive_missing_optional_economic_field_counts | Format-List
    $r.aes_exclusive_source_keys_per_month | Format-List
}
~~~

成功狀態：OWNER_2021_AES_ONLY_25568_SOURCE_KEY_OHLCV_QUALITY_PASS。這是「來源品質清點成功」，絕不是「Neon 已成功回補 25,568 筆」。未見成功狀態或跨來源比對條件不符時，保留私人原檔與舊報告，不要調整正式資料。

## 後續仍需滿足

1. 批次寫入前先解決免費容量保護門檻，對 Neon 官方價量只 INSERT 已證實缺少的主鍵並核對行為與唯一鍵，不能觸碰既有記錄。
2. 確認每一實際欲入庫來源交易日的歷史交易資格、資料時效與企業行動調整；停牌、轉板不能自動產生價格。
3. 執行私人完整封存的獨立可還原演練，任何資料刪除另需具體授權；模型仍需全新樣本外驗證。
