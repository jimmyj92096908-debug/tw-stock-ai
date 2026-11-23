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


## 2026-11-23 真實 Windows 首次執行失敗與來源標籤修正

第一次擁有者執行原型（main 版本 09b61e4）回報 FAILED safely，**沒有產生本機成功驗收報告**。不能宣稱原型已在真實來源完成價量對帳。

Neon 唯讀查詢證明：2330 在 2021 年有 28 個有效 TWSE_STOCK_DAY 行情日、2022 年有 246 個同標籤有效行情日，合計 274 日。2022 年另有 **84 個全市場** TWSE_MI_INDEX_ALLBUT0999 來源日，但 2330 在這 84 日的實際行情以 **個股 TWSE_STOCK_DAY** 標籤存儲，而非 TWSE_MI_INDEX_ALLBUT0999。

原始程式錯誤要求 2330 在全部 84 個市場批次日必須帶有批次來源標籤，造成 fail-closed。修正後：

- 84 日市場批次日依然由 Neon 大盤官方來源日查詢確證；不能根據 2330 一筆個股來源自行增加市場來源日。
- 2330 在這 84 日可以由任一已允許的官方價量來源（TWSE_STOCK_DAY 或 TWSE_MI_INDEX_ALLBUT0999）支持，但每一日都要有有效 2330 價量。
- 本機 AES 日期與現有 Neon 同日期 2330 的核心 OHLCV 必須精確一致。衝突、來源日期超出、來源標籤不明、來源缺失、重複交易日仍需安全拒絕，不得自行修復。
- 合成 CI 新增 Neon 274 日均使用 TWSE_STOCK_DAY 的實際來源標籤情境，以及錯誤輸入拒絕測試。

原始失敗如未建立輸出 JSON，仍可使用相同的私人 --out 路徑重跑，但必須先確認檔案不存在。若已存在，禁止覆寫，改用另一個尚未使用的私人檔名。只回報匿名驗收狀態，不貼 Neon 連線 URI、AES 金鑰或原始價量。

此修正不是豁免 AES/Neon 價量驗證，也不解除 Neon 寫入封鎖、研究模型發布封鎖或公司行動／歷史 PIT 證據缺口。


## 2026-11-23 修正版再次安全失敗：非敏感階段碼

擁有者已在 Windows PowerShell 5.1 更新至 main e18ec14，並重新執行 2021–2022 年 2330 AES＋Neon 虛擬來源驗收；結果仍為 FAILED safely。這**不是成功驗收**。原錯誤處理為避免洩漏 AES 金鑰／資料庫 URI／原始價格，把所有例外均轉成同一句話，無法從此訊息判斷真正失敗的步驟。

本次只加入固定、允許清單內的非敏感診斷階段碼，並完全保留每個原始資料驗證、型別、來源日期、來源標籤與價量一致性保護。失敗時終端僅顯示 diagnostic_stage=安全代碼，不印出原始錯誤、價格、路徑、連線 URI、AES 金鑰、原始記錄或日期明細。程式仍只能執行 Neon READ ONLY 查詢；失敗不建立任何成功的研究報告。

階段碼可以縮小調查範圍，但**不代表已發現或修正底層資料問題**：

- PREVIOUS_REPORT_GUARD：先前 2021 AES 品質或 2022 來源密度報告不符合固定驗收證據
- ARCHIVE_PATHS、PRIVATE_RECEIPTS、AES_KEY_VAULT：私人來源資料夾、前置證據檔案路徑或解密金鑰驗證失敗
- AES_2021_AUTHENTICATION、AES_2022_AUTHENTICATION：AES 原始封存驗證失敗
- NEON_READONLY_SNAPSHOT：Neon 唯讀快照或 2330／全市場來源日基線不符
- AES_2021_2330_REPLAY、AES_2022_2330_REPLAY：該年度封存中 2330 來源資料逐筆驗證未通過
- SOURCE_2022_CALENDAR：162 日 AES 與 84 日 Neon 官方市場來源日期集合或個股有效來源日不相符
- AES_NEON_2330_CORE_OHLCV：AES 和 Neon 在某個已重疊 2330 股票日期鍵的核心開高低收或量不相符。需要另行核實來源差異，不得選擇有利數值、補值或忽略差異
- VIRTUAL_PREFIX_EVALUATION：原始來源整合仍未通過其他保守規則
- ARCHIVE_IMMUTABILITY、CIPHERTEXT_HASH、PRIVATE_RECEIPT_WRITE、UNCLASSIFIED：原始檔變更、私人報告輸出或其他無法安全分類的失敗

更新 GitHub main 後，重跑本文相同的 PowerShell 指令即可；先檢查私有報告輸出路徑不存在。若已有檔案，**不覆寫**，改用新私有檔名。回報一行匿名 diagnostic_stage 和 FAILED safely 即可，無須提供 AES 原檔、原始股價、金鑰、Neon URI 或堆疊。

模型狀態仍然 BLOCKED；沒有 Neon DDL/DML、LINE 修改或額外付費。


## 2026-11-23 第三次診斷：2022 年報告欄位名稱契約修正

擁有者在 main c2b2cfd (#252) 執行得到診斷碼 PREVIOUS_REPORT_GUARD。比對專案中**真正產生私人報告**的原始程式後，發現導入端與產生端的固定欄位名稱不一致：

- 2021 年 AES 獨有來源品質報告中，正式庫寫入計數欄位為 neon_writes，數值 0。
- 2022 年來源密度報告真正使用的是 production_neon_writes，數值 0；該報告**沒有** neon_writes 欄位。
- 2330 跨年度導入端過去卻同時要求兩份報告均含 neon_writes，導致已驗證的 2022 原始來源報告被誤判為不合規。這是**報告欄位契約錯誤**，不是已經發現 2330 OHLCV 有差異。

這次修正僅在 2022 報告核對使用真實 production_neon_writes 欄位，仍**強制等於零**，並額外核對版本、年份、1092 檔當前合資格名單、2022 年 162+84=246 個來源日、零重疊、全部 84 日官方批次密度與調整總報酬仍未批准等既有產生端證據。新增合成測試確認：

1. 使用與 2022 產生端**一致且不包含 neon_writes 別名**的報告，可通過前置驗證。
2. production_neon_writes 欄位缺漏或非零，即使補入錯誤的 neon_writes=0 別名仍會失敗。
3. 年份、來源日數量、官方市場日或經濟調整安全欄位遭更動，依然安全失敗。
4. 合成測試中的兩來源價量衝突、日期缺口與截止日後資料洩漏防護仍須全部通過。

更新 main 後，沿用本文 PowerShell 指令重跑，**不修改既有私人報告**，不得刪除或覆寫。若仍失敗，只回報新 diagnostic_stage；若成功，先人工核對真正的核心價量一致性與模型 BLOCKED 限制。

依然禁止 Neon 寫入、LINE 修改、買賣下單或任何付費升級。實際本機成功執行以前，不能把此階段標示為完成。


## 2026-11-23 第四次診斷：2022 AES 2330 重播階段

擁有者更新至 PR #253（main 6bdc06d）後，在原本私人檔案與 Neon 正式庫唯讀設定下，得到診斷階段 AES_2022_2330_REPLAY。這表示前置私人報告、2022 AES 整包認證及 Neon 唯讀來源快照階段已通過，執行於 2022 年 2330 個股逐筆回播時失敗。不能宣稱 2330 已經通過真實來源價量核對。

核對程式碼發現一項來源封存檔篩選不一致：

- 已成功使用過的 scripts.twse_2022_aes_factor_readiness._ordered_paths 對同一個私人資料夾的所有檔案核對封存年份；非 2022 年檔案仍**完整執行 AES-GCM 認證**，通過後才可略過；只有 2022 年檔案列入研究。跨越兩個年度的單一檔案、內容竄改、重複檔案或認證失敗仍被拒絕。
- 原本 2330 回播函式卻要求資料夾中每筆來源列的年份都等於 2022，因此若資料夾存在正常的其他年度來源檔案，即可能錯誤地報 AES_2022_2330_REPLAY。
- 新版沿用既有的 2022 年封存篩選器，再對篩選出的 2022 AES 檔逐筆讀取 2330，依然不能略過個股缺日、重複主鍵、OHLCV 異常或 AES/Neon 原始價量差異。

GitHub 合成測試使用真實 AES-GCM 格式的**合成資料**檔案（2022 年與 2023 年），驗證額外年度檔案通過認證後可略過，同時驗證遭竄改的額外年度檔、缺少 2330 原始來源日、跨年度的單檔仍會被拒絕。這些合成測試不涉及擁有者原始價格或解密金鑰。

本次程式碼缺陷與錯誤階段相符，但**尚未證明擁有者實際有其他年度檔案存放於同一目錄**。不移除、不搬移也不改寫任何私人加密封存。更新 main 後可以使用本文相同的 PowerShell 指令重跑；若仍失敗，只回報新的固定 diagnostic_stage。模型仍然 BLOCKED；禁止 Neon DML/DDL、LINE 修改、下單及付費升級。
