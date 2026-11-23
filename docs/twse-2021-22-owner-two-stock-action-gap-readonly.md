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


## 2026-11-23 PR258：六組候選事件日 SQL 配對修正

擁有者更新 main c67803b（PR #257）後，真實 1101+2330 公司行動缺口盤點回報 OFFICIAL_EVENT_GAP_RECONCILIATION。先前兩份私人行情驗收 PASS 仍有效；新的公司行動缺口盤點尚未通過。

根因由 Neon 正式庫獨立 READ ONLY SQL 直接確認：舊查詢以「兩個 stock_id 各自 ANY」與「六個 trade_date 各自 ANY」同時過濾，回傳 12 個不同的正常股票日期組合；但六個公開候選事件只包含其中六個股票／日期組合。其餘六個是該兩檔在其他候選日期的正常原始價量，不可以刪除或當成錯誤價量。原驗收器因此拒絕，安全機制正確，SQL 範圍過寬才是程式缺陷。

修正將兩個獨立 ANY 篩選改成用 unnest(%s::varchar[], %s::date[]) 按陣列位置精確配對六組「股票＋日期」，只以 READ ONLY SQL 查這六組的官方來源日。再以 LEFT JOIN 查每組有效來源筆數，即使真的缺少來源日也會回傳 n=0 而失敗；如果重複來源 n>1 仍失敗。不能在 Python 忽略未知股票日期來繞過安全防線。

2026-11-23 Neon 正式庫唯讀執行配對查詢時，得到六組、每組 n=1；但這只是即時 Neon 查詢，不是擁有者本機完整缺口報告 PASS。需要更新 PR #258 合併後版本、重新執行前文 PowerShell；確實產出新私人 JSON 後才能確認。若輸出檔名已存在，必須安全使用另一個沒有被使用過的私人名稱，不得覆寫既有報告。

不變更任何 AES 加密檔、私人 JSON、公司行動資料、調整後股價、Neon DML/DDL、LINE、交易或付費流程。六個事件只有回溯歷史日期候選證據，不能據此認證原始公告發布時間、經濟配股與現金權利、完整總報酬或可交易模型。模型必須維持 BLOCKED。
