# 台股 2330：2021–2022 年 AES＋Neon 虛擬行情前綴（僅研究）

新程式：scripts.twse_2021_22_owner_virtual_2330_prefix_readonly

## 目的與證據

這是 **只處理 2330 的原始行情唯讀原型**，不是完整五年股市或模型驗收。

現有實際擁有者驗收：2021 年 AES 28 個來源日，26,120 個來源股票日期鍵（552 筆 Neon 核心 OHLCV 精確重疊，25,568 個 AES 獨有來源鍵的價量品質合理）；2022 年 AES 162 日＋Neon 官方大批次 84 日，總計 246 個來源日。原始資料中的當期存活上市名單不等於歷史 PIT 交易資格。

新程式首先核實上述兩份擁有者私人報告、完整認證 2021 和 2022 的 AES-GCM 封存，再於單一 Neon REPEATABLE READ READ ONLY 快照讀取 **2330** 在 2021-11-23 到 2022-12-30 的官方原始行情與 2022 的 84 個官方批次來源日期。重複股票日期的開高低收、成交量必須 Decimal 數值精確一致；額外經濟欄位差異單獨記錄，不補值或合成價格。

使用最多 274 個真正來源交易日，僅以 2022-12-29 或 2022-12-30 **當時以前**的來源資料計算原始收盤價 SMA240。這是未調整除權息／減資的算術研究值，不是獲利或買賣訊號，也沒有接入正式交易、LINE 或模型發布。只在私人 JSON 保留研究值，終端不顯示任何價格或連線資訊。

## Windows PowerShell 5.1 擁有者真實驗收

以下要求本機私有加密封存與 Neon DATABASE_URL 已安全設定。新的結果必須寫到 Git checkout 以外的既有私人目錄，若檔案存在則禁止覆寫。一次完整貼上以下區塊：

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
    $q21 = Join-Path $base 'aes-neon-2021-25568-aes-exclusive-source-quality-20261123.json'
    $d22 = Join-Path $base 'aes-neon-2022-current-listed-source-density-20261123.json'
    $out = Join-Path $base 'aes-neon-2021-22-2330-virtual-prefix-20261123.json'

    foreach ($file in @($q21, $d22)) {
        if (!(Test-Path -LiteralPath $file -PathType Leaf)) {
            throw '缺少 2021 來源品質或 2022 原始來源密度驗收報告'
        }
    }
    if (Test-Path -LiteralPath $out) {
        throw '新報告已存在，禁止覆寫'
    }

    $params = @(
        '--archive-2021', "$HOME\TwStockPrivate\archives",
        '--archive-2022', "$env:LOCALAPPDATA\tw-stock-private\prices",
        '--key-vault', "$env:LOCALAPPDATA\tw-stock-private\history.twsekey",
        '--prior-2021-quality', $q21,
        '--prior-2022-density', $d22,
        '--as-of', '2022-12-30',
        '--out', $out
    )
    & python -m scripts.twse_2021_22_owner_virtual_2330_prefix_readonly @params
    if ($LASTEXITCODE -ne 0) { throw '單股虛擬行情原始來源未通過' }

    $r = Get-Content -LiteralPath $out -Raw | ConvertFrom-Json
    if ($r.scope -ne 'OWNER_2021_22_AES_NEON_2330_VIRTUAL_RAW_PREFIX_READONLY' -or
        $r.virtual_2021_22_combined_source_days -ne 274 -or
        $r.virtual_2022_source_calendar_days -ne 246 -or
        $r.source_rows_after_asof_used_in_computation -ne 0 -or
        $r.production_backfill_approved -ne $false -or
        $r.model_release -ne 'BLOCKED' -or
        $r.neon_writes -ne 0) {
        throw '原始來源／安全門檻未通過'
    }
    Write-Host "虛擬來源日：$($r.virtual_2021_22_combined_source_days)"
    Write-Host "截至日期：$($r.as_of)"
    Write-Host "截至日以前的來源筆數：$($r.as_of_raw_prefix_source_days)"
    Write-Host "重複核心價量一致：$($r.neon_AES_overlap_OHLCV_exact)"
    Write-Host "Neon 寫入：$($r.neon_writes)"
    Write-Host "模型發布：$($r.model_release)"
}
~~~

預期狀態：OWNER_2021_22_2330_VIRTUAL_AES_NEON_RAW_PREFIX_READONLY_PASS。只有擁有者完成真實本機執行後，才可稱這個原型在真實資料上驗收通過。GitHub CI 只測合成資料與未來資料洩漏防護。

## 明確的封鎖條件

- 不宣稱公司行動調整、真實歷史上市資格、未來資料標籤隔離全部完成。
- 不宣稱已經做出五年行情或有正的模型預測報酬；原始 SMA240 不可成為交易訊號。
- 不新增 Neon 價量資料、不移除索引、原始行情、因子或正式備份；不改 LINE、不發訊息、不升級付費。
- 若要保護容量，先完成實體獨立加密備份及真實還原驗收，並取得具體資料處理的明確授權。始終維持 model_release=BLOCKED。
