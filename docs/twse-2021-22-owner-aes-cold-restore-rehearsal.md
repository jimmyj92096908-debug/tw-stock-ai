# 2021／2022 AES 原始行情：私人冷備份實際解密還原演練

本步不需要 Neon DATABASE_URL，不操作 Neon、LINE、交易介面，也不刪除資料。它只在 Windows 擁有者本機，將既有的 AES-256-GCM 原始加密檔案另存至一個新的私人目錄，並從**複製後的實體檔案**逐區塊認證解密、精確還原每筆 Decimal OHLCV 與取回時間，核對 SHA256、來源交易日、股票日期與每檔列數。

## 驗收範圍

- 只接受真正已認證的 TWSE 官方來源日：2021 年 28 日、2022 年 AES 162 日。逐日期至少 500 筆有效股票行情、必須具備 2330、排除 1589；不能以檔名或未加密摘要冒充。
- 先完全驗證原始封存，再以 exclusive-create 複製；複本 AES-GCM 認證、逐列精度與總 hash 都要完全相等；最後再次確認原始檔 hash 未變。
- 複製目錄原先必須不存在；不支援覆寫既有備份或還原報告。報告留在新複製目錄內，不上傳 GitHub。
- 應由擁有者選擇**另一顆實體磁碟／離線裝置**，並保留另一份離線金鑰保管檔及通行詞。程式無法證實磁碟是否真的實體獨立，即使路徑不同也不能把實體媒體獨立認證設為通過。
- 只核實所選的 2021/2022 本機 AES 原始來源，不代表整個 Neon 資料庫有完整備份、股票歷史上市 PIT、除權息／總報酬、模型績效已通過。
- 保持禁止刪除或覆寫 Neon、禁止正式回補、model_release=BLOCKED。

## Windows PowerShell 5.1 執行（只在擁有者電腦）

先準備另一顆獨立磁碟的私人目錄，例如 E:\TwStockRecovery。此為**示例路徑**，請依實際磁碟調整；該父目錄必須已存在，當次子目錄尚不存在。勿在 Git 工作目錄內建立備份。請先確認外接磁碟已正確掛載、具有足夠可用空間。

~~~powershell
& {
    $ErrorActionPreference = 'Stop'
    cd "$HOME\tw-stock-ai"
    git pull --ff-only origin main
    if ($LASTEXITCODE -ne 0) { throw 'GitHub 更新失敗' }

    $env:TWSE_KEY_GUI_PROMPT = '1'
    $source2021 = "$HOME\TwStockPrivate\archives"
    $source2022 = "$env:LOCALAPPDATA\tw-stock-private\prices"
    $vault = "$env:LOCALAPPDATA\tw-stock-private\history.twsekey"

    # 改為真實、已存在的獨立備份裝置父目錄
    $backupParent = 'E:\TwStockRecovery'
    if (!(Test-Path -LiteralPath $backupParent -PathType Container)) {
        throw '獨立備份磁碟／父目錄不存在，沒有開始複製'
    }
    $restore = Join-Path $backupParent 'twse-2021-2022-aes-restore-20261123'
    if (Test-Path -LiteralPath $restore) {
        throw '還原演練目錄已存在，禁止覆寫；請先確認既有結果'
    }

    $params = @(
        '--archive-2021', $source2021,
        '--archive-2022', $source2022,
        '--key-vault', $vault,
        '--restore-dir', $restore
    )
    & python -m scripts.twse_owner_aes_cold_restore_rehearsal @params
    if ($LASTEXITCODE -ne 0) { throw 'AES 冷備份還原演練失敗，任何複製檔不可宣稱已完成備份' }

    $r = Get-Content -LiteralPath (Join-Path $restore 'private-aes-cold-restore-receipt.json') -Raw | ConvertFrom-Json
    if ($r.authenticated_2021_source_days -ne 28 -or
        $r.authenticated_2022_aes_source_days -ne 162 -or
        $r.original_vs_restored_canonical_OHLCV_rows_all_equal -ne $true -or
        $r.authorized_to_delete_or_rewrite_neon_data -ne $false -or
        $r.model_release -ne 'BLOCKED') {
        throw '複本與原始檔驗收不符；不可視為完成'
    }
    Write-Host "複本加密檔案數：$($r.source_archives_copied_and_authenticated)"
    Write-Host "2021 AES 已驗證來源日：$($r.authenticated_2021_source_days)"
    Write-Host "2022 AES 已驗證來源日：$($r.authenticated_2022_aes_source_days)"
    Write-Host "複本逐列 SHA256 完整相符：$($r.original_vs_restored_canonical_OHLCV_rows_all_equal)"
    Write-Host "允許刪除 Neon：$($r.authorized_to_delete_or_rewrite_neon_data)"
}
~~~

成功預期狀態：OWNER_2021_2022_AES_COPY_AND_CRYPTO_RESTORE_REHEARSAL_PASS。只需要回報上述匿名總數，不要貼出 .twseenc、.twsekey、通行詞、資料庫連線或帶逐檔私有目錄的 JSON。

## 失敗與後續

- 原檔、金鑰、來源日、磁碟空間、複製 SHA、複本解密任何一項失敗就停止。若已建立演練目錄，可能留有**未驗證的部分複本**；不得使用其作正式還原或認定已備份完成，也不要重新指定同一個既存目錄。
- 本步仍無法代表 Neon 完整備份。必須另規劃**所有即將移出正式庫之資料**的獨立可還原封存，逐筆精確比對、外接媒體保管、恢復流程實測，再對擬刪除的**具體資料與範圍**取得明確授權。
- 2021 AES+Neon 去重 26,120 來源鍵、2022 AES 162 日加 Neon 84 日、2021 零來源 153 檔分類的研究證據保持獨立；本演練不批准任何來源鍵自動寫入 Neon。
