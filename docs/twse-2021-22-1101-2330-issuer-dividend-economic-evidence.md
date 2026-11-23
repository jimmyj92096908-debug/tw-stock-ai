# 1101／2330：六組發行人回溯股利經濟條件證據（2026-11-23）

## 與先前真實驗收的關係

2026-11-23 擁有者已在 Windows 上實際驗證 1101、2330 各自 274 個 2021/11/23–2022/12/30 原始行情來源日、190 個 AES/Neon 重疊核心 OHLCV 主鍵。接著使用修復 PR #259 的官方公司行動缺口唯讀驗收工具實際獲得 PASS：六組已知候選日期的原始行情存在，但 Neon 當時尚未記錄這六組公司行動。**缺口盤點成功，不是總報酬驗證成功。**

2026-11-23 再透過兩家發行人自身的回溯股利頁面核對以下資料。回溯的 issuer source **並不等於 2021–2022 原始 MOPS 公告發布時間已驗證**，也不能證明歷史時點資訊可得性。

| 股票 | 除權息日 | 每股現金股利 NT$ | 每股股票股利面額 NT$（非新增股數） | 官網列現金支付日 |
| --- | --- | --- | --- | --- |
| 2330 | 2021-12-16 | 2.75 | 0 | 2022-01-13 |
| 2330 | 2022-03-16 | 2.75 | 0 | 2022-04-14 |
| 2330 | 2022-06-16 | 2.75 | 0 | 2022-07-14 |
| 2330 | 2022-09-15 | 2.75 | 0 | 2022-10-13 |
| 2330 | 2022-12-15 | 2.75 | 0 | 2023-01-12 |
| 1101 | 2022-07-21 | 0.99928258 | 0.99928258 | 2022-08-22 |

**發行人官網：**
- 台積電 https://investor.tsmc.com/chinese/dividends
- 台泥 https://www.tccgroupholdings.com/dividend

台積電頁還列配息基準日依序為 2021-12-22、2022-03-22、2022-06-22、2022-09-21、2022-12-21。台泥官網列 2022-05-26 股東會、2022-07-21 同日除權息，但未在該行提供精確換股比例。**台泥的股票股利面額 0.99928258 元，不能直接當成每原股新增 0.99928258 股。** 本工具不做任何股數或還原價格換算。

台泥另有當時 MOPS 重大訊息的第三方歷史轉載：2022-06-23 19:53:53 首次訂定除權息基準日、2022-07-06 18:49:23 因庫藏股而調整每股配股配息率。來源：
- https://goodinfo.tw/tw/StockAnnounceDetail.asp?CLAIM_TIME=2022%2F06%2F23+19%3A53%3A53&STOCK_ID=1101
- https://goodinfo.tw/tw/StockAnnounceDetail.asp?CLAIM_TIME=2022%2F07%2F06+18%3A49%3A23&STOCK_ID=1101

轉載不等於取得及驗證原始 MOPS bytes 與首次公告時間戳。最終每股經濟條件仍需檢查其他修正、股利受配資格、減資／分割、面額與換股比例、稅費、現金及股票入帳，才可聲稱歷史總報酬正確。

## 新增純離線研究工具的安全邊界

scripts.twse_2021_22_owner_issuer_dividend_economics_offline：

1. 讀取先前擁有者已驗收的**私人** action-gap JSON，而非重新操作 AES／Neon。必須有完整六個股票＋事件日期、六組未建檔、先前 274 日前置驗收 guard、零新增寫入及模型 BLOCKED 的紀錄，否則 fail closed。
2. 用程式內固定的 2026-11-23 人工查證 issuer retrospective manifest 對比六組金額與日期；不自動網路下載，不把人工研究聲稱為再次認證網站。
3. 在 owner-private 路徑以獨佔新建 JSON，從不覆寫或公布過去的私人驗收憑證。正式資料庫和 LINE 都不操作，無付費。
4. 所有公告 PIT、公司行動完整性、股票新股數、價格調整、前瞻總報酬或交易指令的認證欄位始終是 FALSE，model_release=BLOCKED。此工具本身只驗收**公開研究候選值與先前真實缺口報告一致**。

## Windows PowerShell 5.1 本機執行

不需要設定 DATABASE_URL，不需解密 AES，也不需連結外部網站。只需先把通過的私人公司行動缺口報告留在原位。

~~~powershell
& {
    $ErrorActionPreference = 'Stop'
    cd "$HOME\tw-stock-ai"
    git pull --ff-only origin main
    if ($LASTEXITCODE -ne 0) { throw 'Git 更新失敗' }

    $base = "$HOME\TwStockPrivate"
    $prior = Join-Path $base 'aes-neon-2021-22-1101-2330-action-gaps-20261123.json'
    $out = Join-Path $base 'aes-neon-2021-22-1101-2330-issuer-dividends-20261123.json'
    if (!(Test-Path -LiteralPath $prior -PathType Leaf)) {
        throw '缺少先前已通過的私人公司行動缺口報告'
    }
    if (Test-Path -LiteralPath $out) {
        throw '私人輸出已存在，禁止覆寫'
    }
    $params = @('--prior-action-gap', $prior, '--out', $out)
    & python -m scripts.twse_2021_22_owner_issuer_dividend_economics_offline @params
    if ($LASTEXITCODE -ne 0) { throw '請回報 diagnostic_stage' }

    $r = Get-Content -LiteralPath $out -Raw | ConvertFrom-Json
    if ($r.scope -ne 'OWNER_2021_22_1101_2330_ISSUER_RETROSPECTIVE_DIVIDEND_ECONOMICS_BLOCKED' -or
        $r.reviewed_issuer_retrospective_event_rows -ne 6 -or
        $r.original_neon_action_gaps_in_previous_owner_snapshot -ne 6 -or
        $r.research_evidence_events.Count -ne 6 -or
        $r.source_issuer_urls_checked_at_runtime -ne $false -or
        $r.mops_original_first_publication_timestamp_proven -ne $false -or
        $r.tcc_stock_dividend_new_shares_factor_verified -ne $false -or
        $r.corporate_action_universe_complete -ne $false -or
        $r.real_forward_total_return_labels_approved -ne $false -or
        $r.production_backfill_approved -ne $false -or
        $r.neon_writes -ne 0 -or
        $r.line_messages_sent -ne 0 -or
        $r.model_release -ne 'BLOCKED') {
        throw '研究證據安全驗收不符'
    }
    Write-Host '1101/2330 六組發行人回溯股利研究驗收通過'
    Write-Host "官方回溯事件：$($r.reviewed_issuer_retrospective_event_rows)"
    Write-Host "原始MOPS時間戳認證：$($r.mops_original_first_publication_timestamp_proven)"
    Write-Host "Neon寫入：$($r.neon_writes)"
    Write-Host "模型狀態：$($r.model_release)"
}
~~~

不把私人 JSON、原始行情、AES 金鑰、Neon URI、檔案路徑或完整 CLI 錯誤堆疊上傳 GitHub／聊天室；只分享匿名 diagnostic_stage 或最後的安全 PASS 摘要。

## 尚未解除的阻礙

完整五年行情、歷史上市資格 PIT 與存續偏差、原始 MOPS 公告版本／首次發布時點、全市場公司行動完整名單、股票股利配發因子與歷史帳務、除權息與減資還原報酬、交易成本／扣稅、正式樣本外預測績效。維持排除下市股票與 1589，零額外付費，零 Neon DML/DDL，LINE 不變；模型仍 BLOCKED。
