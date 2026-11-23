# 1101／2330：六個月份證交所除權息與減資公開回應核對

## 真實驗收前置條件

2026-11-23 使用者已在本機確認兩檔 2021/11/23–2022/12/30 各 274 個原始行情來源日與 190 個精確 AES/Neon OHLCV 共同日期鍵，PR #259 的六組公司行動缺口報告及 PR #260 的六組發行人回溯股利研究報告均已本機 PASS。本次驗證沿用 PR260 的**私人** JSON，不重播 AES、不連 Neon、不更動經濟數值。

## 第二個獨立公開來源：TWSE

證交所免費公開歷史查詢：

- https://www.twse.com.tw/rwd/zh/exRight/TWT49U ：除權除息計算結果表。
- TWSE TWTAUU 公開減資恢復交易來源，參見本專案既有 src/corporate_actions_data.py 中 TWSE_REDUCTION_URL。

依照既有已測試的歷史官方 JSON 解析器，只針對股票 1101、2330、六個事件所在的月份執行**最多 12 個 HTTPS GET**（六個月份 × 除權息與減資兩類）。兩檔以外的股票事件不保存在報告中。每次記錄公開資料來源網址、回應 SHA256、目前擷取時間、月區間、回應筆數及符合條件的兩股事件日期／類別；不記錄個股股價或參考價數字。

| 月份 | 已知股利事件 | 重要邊界 |
| --- | --- | --- |
| 2021-12 | 2330 2021/12/16 | 必須從 12/01 起查，不能沿用另一個 frozen2 研究從 12/30 開始的界線 |
| 2022-03 | 2330 2022/03/16 | 僅 03 月 |
| 2022-06 | 2330 2022/06/16 | 僅 06 月 |
| 2022-07 | 1101 2022/07/21 | 除權與除息可能同日 |
| 2022-09 | 2330 2022/09/15 | 僅 09 月 |
| 2022-12 | 2330 2022/12/15 | 12 月只查到 12/30 |

此工具會分開呈現：
- 實際完成官方 TWSE 回應擷取（總數必須 12 次）。
- 六組原本有發行人回溯證據的事件，在官方 TWT49U 中實際觀察到幾個相同股票＋除權息日，以及還缺幾個。
- 同六個月發現的其他 1101／2330 事件日期候選。

**查詢成功不等於六組日期都 match**。空回應或歷史資料不可得**不等於零公司行動**。即使全部六組日期都有證交所記錄，也不能取代原始 MOPS 首次發布 bytes／時間戳、歷史時點資訊可得性、現金股利入帳及股票股利面額對新股數、所有減資／分割的完整證據、或正式的 adjusted total-return labels。

本次為歷史官方公共回應的 2026 年**重新擷取**，不是 2021/22 當時已存在且被加密保存的原始公告。因此不能將今天的下載時間誤說成 2022 年資訊首次可被交易模型使用的時間。

## Windows PowerShell 5.1 本機驗收

合併到 main 且所有 GitHub CI PASS 後，在既有私人報告的 Windows 環境執行。**不需要 DATABASE_URL 或 AES 解密密碼，只有 12 個官方 HTTPS 公開查詢。** 輸出以獨佔建立，不得覆寫其他私人成功報告。

~~~powershell
& {
    $ErrorActionPreference = 'Stop'
    cd "$HOME\tw-stock-ai"
    git pull --ff-only origin main
    if ($LASTEXITCODE -ne 0) { throw 'Git 更新失敗' }

    $base = "$HOME\TwStockPrivate"
    $prior = Join-Path $base 'aes-neon-2021-22-1101-2330-issuer-dividends-20261123.json'
    $out = Join-Path $base 'aes-neon-2021-22-1101-2330-twse-six-event-months-20261123.json'

    if (!(Test-Path -LiteralPath $prior -PathType Leaf)) {
        throw '缺少前次 PR260 已通過的私人股利報告'
    }
    if (Test-Path -LiteralPath $out) {
        throw '私人輸出已存在，禁止覆寫'
    }

    $params = @('--prior-issuer-research', $prior, '--out', $out)
    & python -m scripts.twse_2021_22_owner_twse_six_event_months_readonly @params
    if ($LASTEXITCODE -ne 0) {
        throw '歷史官方來源未通過；回報上方 diagnostic_stage'
    }

    $r = Get-Content -LiteralPath $out -Raw | ConvertFrom-Json
    if ($r.scope -ne 'OWNER_1101_2330_TWSE_SIX_HISTORIC_DIVIDEND_MONTH_RESPONSES_BLOCKED' -or
        $r.official_twse_http_requests -ne 12 -or
        $r.source_months_queried.Count -ne 6 -or
        $r.official_response_receipts.Count -ne 12 -or
        $r.expected_issuer_retrospective_event_date_count -ne 6 -or
        $r.expected_events_found_in_official_twse_ex_feed -lt 0 -or
        $r.expected_events_found_in_official_twse_ex_feed -gt 6 -or
        $r.official_data_retrieved_as_of_original_2021_22_publication -ne $false -or
        $r.original_mops_issuer_announcement_timestamps_verified -ne $false -or
        $r.full_2021_22_corporate_action_universe_verified -ne $false -or
        $r.verified_adjusted_total_return_labels -ne $false -or
        $r.production_neon_backfill_approved -ne $false -or
        $r.neon_writes -ne 0 -or
        $r.line_messages_sent -ne 0 -or
        $r.model_release -ne 'BLOCKED') {
        throw '官方回應或安全驗收不符'
    }

    Write-Host '證交所六月份來源唯讀擷取完成'
    Write-Host "官方請求：$($r.official_twse_http_requests)"
    Write-Host "六組已知日期找到：$($r.expected_events_found_in_official_twse_ex_feed)"
    Write-Host "六組已知日期未找到：$($r.expected_event_date_pairs_not_observed.Count)"
    Write-Host "同月額外事件候選：$($r.additional_twse_ex_date_pairs_in_same_six_months.Count)"
    Write-Host "原始MOPS時間戳認證：$($r.original_mops_issuer_announcement_timestamps_verified)"
    Write-Host "Neon寫入：$($r.neon_writes)"
    Write-Host "模型狀態：$($r.model_release)"
}
~~~

只回傳最後七行匿名統計與狀態，不公開私人 JSON、股票價格、AES 原始資料、金鑰、Neon URI 或私人資料夾詳細路徑。無模型發布或下單授權。

## 研究仍未解除的門檻

目前只查了六個月，不是 2021/22 全年度歷史公司行動完整性證明，也不是五年全市場資料完備。仍須證明原始 MOPS 公告首次與修訂版的時點、台泥股利面額對實際新股數的正確股本規格、所有公司行動、歷史 PIT 股票母體、全五年來源覆蓋、調整後總報酬、獨立冷復原、嚴格樣本外模型 alpha。仍排除下市及 1589，但現存上市母體固有存續偏差不可消失。零 Neon 正式資料寫入、LINE 不修改、零額外付費，模型維持 BLOCKED。
