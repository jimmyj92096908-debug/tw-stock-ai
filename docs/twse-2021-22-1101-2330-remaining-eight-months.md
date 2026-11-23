# 1101、2330：補查剩餘八個月份的 TWSE 公司行動公開回應（2026-11-23）

## 前一階段真實成功證據

PR #261 已經在擁有者 Windows 電腦**真實執行成功**。2021-12、2022-03、06、07、09、12 六個月份共 12 次免費官方 TWSE 歷史除權息／減資來源 HTTP 查詢；六組發行人回溯已知除權息股票日期均在證交所的歷史公開 TWT49U 回應中找到，少 0 組、該六個月份同兩股額外除權息候選 0 組；未驗證原始 MOPS 初次公告時間與總報酬。該時點 Neon 寫入 0、LINE 訊息 0，模型 BLOCKED。

PR #260 的發行人回溯股利（2330 五次各現金 2.75 元，1101 2022/07/21 現金 0.99928258 元＋**面額**股票股利 0.99928258 元）亦已在擁有者本機以既有私人驗收報告 PASS；PR #259 真實 Neon 唯讀事件缺口報告與兩檔各 274 個原始來源日 AES/Neon 交叉驗證也已 PASS。**上述是分層不同的證據，尚未建立調整後總報酬。**

## 本次只查前次未查的八個月份

同樣只使用官方 TWSE 免費歷史 TWT49U 與 TWTAUU 兩種事件公開來源，不操作 Neon、不讀取 AES、個股原始價格或私有金鑰、不改 LINE、不新增付費。每個月查一次除權息及一次減資，共 **8 × 2 = 16 個新 HTTPS GET**。

| 月份 | 官網查詢日期範圍 |
| --- | --- |
| 2021-11 | 2021/11/23–2021/11/30 |
| 2022-01 | 整個 2022/01 |
| 2022-02 | 整個 2022/02 |
| 2022-04 | 整個 2022/04 |
| 2022-05 | 整個 2022/05 |
| 2022-08 | 整個 2022/08 |
| 2022-10 | 整個 2022/10 |
| 2022-11 | 整個 2022/11 |

結合前次真實成功私人 12 筆官方月別來源憑證，會產生 2021/11/23 至 2022/12/30 **14 個日曆月份 × 2 種官方來源＝28 份回應**的衍生唯讀研究憑證。2021/11/01–11/22 不在目前已通過的行情研究區間；本工具不聲稱涵蓋該段或完整五年。

必須先驗證原有 12 筆官網回應來源 URL、雜湊、月份範圍、六組事件日期及總報酬安全欄位，才能查剩餘月份。新 HTTP 回應一律保留抓取當下的 2026 時間、完整事件日期、類別及 SHA256 雜湊，但不輸出原始股價或參考價金額。結果會分開標示新發現的 1101、2330 除權息日期與減資日期，作為**待查證線索**，不自行計算新股股數與價格調整因子。

請特別注意：即使新查的八個月份都沒有發現新的事件，**「回應沒有事件」不證明該段歷史沒有真實公司行動**；免費歷史 API 可能有資料缺口、版本更改或缺乏某些事件類型。證交所歷史行情事件表同樣不是原始 MOPS 初次公告與所有修正版本。只以今日網頁資料補回 2021/22 並不能保證 PIT 模型不會洩漏未來。

## Windows PowerShell 5.1 本機操作

需在 GitHub PR 專屬 CI、全專案 Python Tests，及合併後 main CI 均 PASS 後執行。**不需要 DATABASE_URL、不需要 AES 密碼**，只有 16 次有上限的免費官方 TWSE HTTPS 讀取。原 PR261 的成功私人報告不會被修改；新報告只允許獨佔建立，若已存在請停止並保護檔案。

~~~powershell
& {
    $ErrorActionPreference = 'Stop'
    cd "$HOME\tw-stock-ai"
    git pull --ff-only origin main
    if ($LASTEXITCODE -ne 0) { throw 'Git main 更新失敗' }

    $base = "$HOME\TwStockPrivate"
    $prior = Join-Path $base 'aes-neon-2021-22-1101-2330-twse-six-event-months-20261123.json'
    $out = Join-Path $base 'aes-neon-2021-22-1101-2330-twse-remaining-eight-months-20261123.json'

    if (!(Test-Path -LiteralPath $prior -PathType Leaf)) {
        throw '找不到 PR261 已通過的私人 12 次官方回應報告'
    }
    if (Test-Path -LiteralPath $out) {
        throw '新私人報告已存在，禁止覆寫'
    }

    $params = @('--prior-six-month-source', $prior, '--out', $out)
    & python -m scripts.twse_2021_22_owner_remaining_action_months_readonly @params
    if ($LASTEXITCODE -ne 0) {
        throw '請只回報上方安全的 diagnostic_stage'
    }
    $r = Get-Content -LiteralPath $out -Raw | ConvertFrom-Json

    if ($r.scope -ne 'OWNER_1101_2330_TWSE_REMAINING_EIGHT_HISTORIC_MONTH_RESPONSES_BLOCKED' -or
        $r.full_calendar_months_with_response_receipts.Count -ne 14 -or
        $r.new_calendar_months_queried.Count -ne 8 -or
        $r.new_official_twse_http_requests -ne 16 -or
        $r.all_official_twse_http_response_receipts_count -ne 28 -or
        $r.prior_six_issuer_date_matches_preserved -ne $true -or
        $r.original_six_known_issuer_ex_dividend_pairs -ne 6 -or
        $r.no_data_response_proves_zero_historic_company_actions -ne $false -or
        $r.response_source_historic_action_coverage_independently_proven_exhaustive -ne $false -or
        $r.issuer_original_mops_first_announcement_publication_verified -ne $false -or
        $r.new_share_entitlement_and_cash_distribution_verified -ne $false -or
        $r.historical_pit_listing_universe_verified -ne $false -or
        $r.full_five_year_dividends_or_prices_complete -ne $false -or
        $r.adjusted_total_return_labels_approved -ne $false -or
        $r.production_neon_backfill_approved -ne $false -or
        $r.neon_writes -ne 0 -or
        $r.line_messages_sent -ne 0 -or
        $r.model_release -ne 'BLOCKED') {
        throw '官方資料來源／風險安全門檻不符'
    }

    Write-Host 'TWSE 14 個月份公司行動來源回應盤點完成'
    Write-Host "前次官方查詢：12"
    Write-Host "本次官方查詢：$($r.new_official_twse_http_requests)"
    Write-Host "合計有憑證月份：$($r.full_calendar_months_with_response_receipts.Count)"
    Write-Host "新除權息事件候選：$($r.additional_issuer_ex_right_dates_observed_in_new_eight_months.Count)"
    Write-Host "新減資事件候選：$($r.additional_issuer_reduction_dates_observed_in_new_eight_months.Count)"
    Write-Host "Neon寫入：$($r.neon_writes)"
    Write-Host "模型狀態：$($r.model_release)"
}
~~~

只分享最後安全統計與狀態，**不要**將私人 JSON、完整 TWSE 來源 response、AES 原始價量、Vault 密碼、Neon 連線 URI、私人檔案路徑放到 GitHub 或聊天室。如發生問題，只回報匿名 diagnostic_stage 以便隔離修正。

## 模型仍保持 BLOCKED

28 份官方回應只代表「對應月份的歷史 HTTP 回應已取得」，**不是**能推論所有公司行動完整、2021/22 當時的原始 MOPS 首發時點、股利入帳與股票配發、資本減縮／分割可交易調整因子。完整五年行情與歷史股票 PIT 母體、冷復原、樣本外模型仍缺。研究目前排除下市及 1589，但「只選今天還上市股票」本身會有存續者偏差，不可宣稱已處理歷史完整存續情形。

正式 Neon DML／DDL 仍不核准、LINE 不改、不付費、不下單。
