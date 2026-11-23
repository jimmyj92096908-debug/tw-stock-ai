# 2021–2022 年 1101／2330：公司行動缺口的私人唯讀核對

## 已有證據與不能推論的事

- 擁有者已獨立實際驗收 2330 和 1101，兩檔各 274 個 2021/11/23–2022/12/30 原始行情來源日、190 個 AES/Neon 日期重疊核心 OHLCV 完全一致，正式 Neon 寫入 0。
- 2026-11-23 Neon **唯讀** SQL 檢查顯示兩檔在上述期間 corporate_actions 均 0 筆。零筆資料庫紀錄**不代表**零筆真實歷史事件。
- 台積電發行人回溯股利列表顯示 2021/12/16、2022/03/16、2022/06/16、2022/09/15、2022/12/15 五次除息；來源 https://investor.tsmc.com/chinese/dividends
- 台泥的 **第三方回溯表**列出 2022/07/21 同日除息與除權，暫列需原始公告補強的候選事件；來源 https://goodinfo.tw/tw/StockDividendSchedule.asp?STOCK_ID=1101
- Neon 唯讀查詢在上述六個股票+事件日各見到 **1 筆有效原始行情**。這不驗證公告原始發布時點、每股精確調整數值或歷史完整性。

## 實作範圍

scripts.twse_2021_22_owner_two_stock_action_gap_readonly 會：

1. 驗證先前 2330／1101 **兩份**私人成功報告的 schema、274 日、190 重疊、原始價量一致性聲明、零越界及模型 BLOCKED。它**不會重播 AES 本體**，因此不能稱為全新的 AES 密碼學認證。
2. 單一 Neon REPEATABLE READ READ ONLY 快照，查原本合格上市 1092 檔名單，排除 1589，兩檔各自 28+246 日及六個日期存在性；只對這兩檔讀取最多 100 筆原本 corporate_actions，從不讀取或印出股價。
3. 把六個不同證據強度的回溯日期與已存事件比對；缺少記為 NO_ACTION_RECORD_ON_CANDIDATE_DATE，有事件則記為 RECORDED_ACTION_EXISTS_UNRECONCILED。沒有事件不證明歷史沒發生；有事件也不證明經濟調整準確。
4. 僅在 owner-private JSON 獨佔新建小型「公開來源候選日期、既有公司行動記錄數、缺口狀態」報告。禁止寫入 Neon、LINE、交易服務，零額外付費。

報告一律維持 real_future_return_labels_approved=false、
known_event_candidates_prove_complete_action_universe=false、
stock_dividend_adjustments_verified=false、
retrospective_event_date_is_original_publication_vintage=false、
model_release=BLOCKED。**本階段絕不產生或宣稱還原總報酬。**

## Windows PowerShell 5.1 本機驗收

不需要再輸入 AES vault 密碼，因為只引用先前已完成真實驗收的私人 JSON，並使用已設定的 Neon 唯讀連線。不要把 JSON、密碼或資料庫連線字串貼上 GitHub 或聊天。

~~~powershell
& {
    $ErrorActionPreference = 'Stop'
    cd "$HOME\tw-stock-ai"
    git pull --ff-only origin main
    if ($LASTEXITCODE -ne 0) { throw 'Git 更新失敗' }
    if ($env:DATABASE_URL -notmatch '^postgres(ql)?://') {
        throw 'Neon 私人連線尚未設定'
    }

    $base = "$HOME\TwStockPrivate"
    $p2330 = Join-Path $base 'aes-neon-2021-22-2330-virtual-prefix-20261123.json'
    $p1101 = Join-Path $base 'aes-neon-2021-22-1101-virtual-prefix-20261123.json'
    $out = Join-Path $base 'aes-neon-2021-22-1101-2330-action-gaps-20261123.json'

    foreach ($file in @($p2330, $p1101)) {
        if (!(Test-Path -LiteralPath $file -PathType Leaf)) {
            throw '缺少已通過的私人來源報告'
        }
    }
    if (Test-Path -LiteralPath $out) {
        throw '輸出報告已存在，禁止覆寫'
    }

    $params = @(
        '--prior-2330', $p2330,
        '--prior-1101', $p1101,
        '--out', $out
    )
    & python -m scripts.twse_2021_22_owner_two_stock_action_gap_readonly @params
    if ($LASTEXITCODE -ne 0) {
        throw '公司行動缺口核對失敗；回報 diagnostic_stage 即可'
    }

    $r = Get-Content -LiteralPath $out -Raw | ConvertFrom-Json
    if ($r.scope -ne 'OWNER_2021_22_1101_2330_DATED_ACTION_GAPS_READONLY' -or
        $r.historical_candidate_event_dates -ne 6 -or
        $r.candidate_dates_without_stored_action -lt 0 -or
        $r.candidate_dates_without_stored_action -gt 6 -or
        $r.neon_issuer_raw_source_days.'1101' -ne 274 -or
        $r.neon_issuer_raw_source_days.'2330' -ne 274 -or
        $r.private_prior_2330_and_1101_raw_source_receipts_guard_passed -ne $true -or
        $r.known_event_candidates_prove_complete_action_universe -ne $false -or
        $r.retrospective_event_date_is_original_publication_vintage -ne $false -or
        $r.real_future_return_labels_approved -ne $false -or
        $r.production_backfill_approved -ne $false -or
        $r.neon_writes -ne 0 -or
        $r.line_messages_sent -ne 0 -or
        $r.model_release -ne 'BLOCKED') {
        throw '來源日、歷史事件或總報酬安全驗收不符'
    }

    Write-Host '兩股公司行動缺口唯讀核對成功'
    Write-Host "候選事件日期：$($r.historical_candidate_event_dates)"
    Write-Host "無同日資料庫事件：$($r.candidate_dates_without_stored_action)"
    Write-Host "Neon寫入：$($r.neon_writes)"
    Write-Host "模型狀態：$($r.model_release)"
}
~~~

若只有缺口盤點 PASS，**不能**把已調整股價、股利再投資、現金派發、減資或交易回測改成 PASS；需依 TWSE/MOPS 與發行人歷史公告逐項補足原始時點與經濟條件，維持歷史 PIT、除權息與樣本外標籤封鎖。禁止下市股票與 1589，不能超額使用 Neon Free。


## 2026-11-23 真實執行診斷：股票／事件日期配對查詢

擁有者更新至 c67803b（PR #257）後，以兩份先前完成驗收的 2330 與 1101 私人來源報告執行，得到診斷碼 OFFICIAL_EVENT_GAP_RECONCILIATION。代表前置私人報告檢查與 Neon 強制唯讀資料快照皆成功，但事件日期對帳仍失敗；不能據此認定行情價格錯誤。

核對原始 SQL 找到程式缺陷：舊 EVENT_DAY_SQL 分別選取兩檔股票與六個候選日期，會找出 2 × 6 = 12 個股票日期配對。但真正的回溯候選名單只包含 1101 的 2022/07/21，以及 2330 的五個除息日期，合計 6 組主鍵。因此多出的 6 組非候選股票日期觸發嚴格的來源對帳防護。這是查詢鍵條件錯誤，不能任意把額外紀錄視作官方候選事件。

已經用正式 Neon 資料庫的**唯讀 SQL**重現：舊查詢條件有 12 個有效股票日期鍵、6 個真正候選鍵、6 個多查入的非候選鍵；沒有讀取或印出任何股價。

修正版使用 PostgreSQL 多陣列 UNNEST，將股票代號與事件日期以相同索引**精確配對**，再 JOIN 到每日行情的聯合主鍵，不能分開使用獨立 ANY 條件。程式依然會嚴格拒絕缺漏、重複、額外、越界的股票日期列，以及不合資格的股票、原始報告不符或模型放行嘗試。

合成回歸測試特別建立 12 個交叉日期，驗證查詢僅請求六組精確主鍵；額外六組仍應被拒絕，並使用模擬資料庫檢查所有 SQL 參數。原有公司行動資料、私人 AES、Neon、LINE 完全不修改。

修正版只在 GitHub 隔離分支通過專屬 CI 與全專案 Python Tests、合併至 main 後再跑一次同樣測試，才請擁有者重新執行本文原有 Windows PowerShell 區塊；先檢查輸出檔不存在，不得覆寫既有私有報告。

即使缺口報告通過，也只意味著候選事件與現有公司行動紀錄的唯讀缺口核對通過；事件完整性、原始公告發布時點、經濟金額、還原總報酬、實際回測獲利仍然未通過，模型維持 BLOCKED，Neon 寫入 0。
