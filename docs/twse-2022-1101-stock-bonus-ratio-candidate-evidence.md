# 台泥 1101／2022-07-21 配股數值候選，尚未核准還原報酬

## 原始來源級別，不得混用

2026-11-23 人工核對：

1. **台泥發行人自己公布的回溯股利表**：https://www.tccgroupholdings.com/dividend 。2022/07/21 同日除權與除息；每舊股現金 NT$0.99928258、股票股利面額 NT$0.99928258、現金支付日 2022/08/22。這是現在能看到的發行人回溯資訊，不是 2022 年首次公告原文。
2. **2022/07/06 18:49:23 調整配股配息率公告的第三方轉載**：https://goodinfo.tw/tw/StockAnnounceDetail.asp?CLAIM_TIME=2022%2F07%2F06+18%3A49%3A23&STOCK_ID=1101 。聲稱因 4,669,600 股尚未轉讓的庫藏股，每舊股配股配息率均調至 NT$0.99928258。
3. **2022 年 7 月盈餘轉增資新股配發公告的第三方轉載**：https://m.moneydj.com/f1a.aspx?a=be14d588-be68-4e19-9bb7-d5255eb7633e 。聲稱發行普通股 611,617,340 股；新股面額 NT$10；股本增資 NT$6,116,173,400；每千舊股配 99.928258 股；現金股利總額 NT$6,116,173,402。

**重要：後兩份目前只驗證到第三方轉載，不是原始公開資訊觀測站 MOPS 首次公告 bytes 與發表時間。** 說法一致不能取代公司註冊資本、股務登記及畸零股配發明細。

## 可安全檢查的十進位算式

- 611,617,340 新股 × NT$10 面額 = NT$6,116,173,400 名目增資。
- 每原股股票股利**面額** NT$0.99928258 ÷ NT$10／新股 = **候選每原股配發 0.099928258 新股**。
- 0.099928258 股 × 每 1,000 舊股 = **每千股配發 99.928258 股**。
- NT$6,116,173,402 的現金總額與 NT$6,116,173,400 名目股票股利總額屬不同經濟帳務，不能混用。
- 千萬不能把股票股利面額 NT$0.99928258 誤當成每舊股獲配 0.99928258 股。

這是**候選數學一致性**，不是獲准的股票股數調整、總報酬或者可以拿去下單的價格訊號。

## 對既有 PR262 真實來源驗收的依賴

使用者 Windows 已真實 PASS：兩檔 1101 與 2330 原始 AES+Neon 價量各 274 來源日與 190 OHLCV 重疊鍵，PR259 6 組 Neon 企業行動缺口、PR260 6 組發行人回溯股利、PR261 12 個官方月別 TWSE 回應及 6/6 除權息事件日期、PR262 新 16 次免費 TWSE 月別回應並合計 14 個月份、28 份來源回應憑證、零新候選事件。

本次新增的獨立 **scripts.twse_2022_owner_1101_bonus_share_evidence_offline**：

- 只讀取 PR262 的 owner-private 14 個月／28 份官方回應 JSON，嚴格核對完整月份清單、TWSE 官方來源網址、日期、SHA256、兩股先前六組除權息事件及各月事件數。缺月、重複、外部股票 1589、價格因子已被誤核准或來源異常時必須安全失敗。
- 比對預置的 2026-11-23 人工研究候選股利與股本數字，採 Decimal 精確計算。**本次並不重新擷取當年的 MOPS 來源、發行人網站、Neon、AES 或行情。**
- 將結果以新私人 JSON 獨佔建立，不覆寫原本 28 份來源的成功報告；不把私人檔案推上 GitHub，禁止印出價格或秘密。
- 原始 MOPS 首發時點、公告原始位元組、實際受配權益、畸零股、最終公司股本登記、正式價格調整、總報酬及模型發布仍 FALSE 或 BLOCKED。
- 零 Neon 寫入、LINE 發送、付費、交易。

## Windows PowerShell 5.1，僅離線查既有報告

必須先確認 GitHub PR 專屬和全 Python Tests 在分支及 main 合併後均 PASS。此步不用資料庫 URI、解密金鑰或網路。

~~~powershell
& {
    $ErrorActionPreference = 'Stop'
    cd "$HOME\tw-stock-ai"
    git pull --ff-only origin main
    if ($LASTEXITCODE -ne 0) { throw 'Git 更新失敗' }

    $base = "$HOME\TwStockPrivate"
    $prior = Join-Path $base 'aes-neon-2021-22-1101-2330-twse-remaining-eight-months-20261123.json'
    $out = Join-Path $base 'tcc-1101-2022-bonus-share-candidate-20261123.json'

    if (!(Test-Path -LiteralPath $prior -PathType Leaf)) {
        throw '找不到之前已通過的 14 個月份私人驗收'
    }
    if (Test-Path -LiteralPath $out) {
        throw '候選研究報告已存在，禁止覆寫'
    }

    $params = @('--prior-14-month-source', $prior, '--out', $out)
    & python -m scripts.twse_2022_owner_1101_bonus_share_evidence_offline @params
    if ($LASTEXITCODE -ne 0) {
        throw '僅回報安全 diagnostic_stage'
    }

    $r = Get-Content -LiteralPath $out -Raw | ConvertFrom-Json
    if ($r.scope -ne 'OWNER_1101_2022_STOCK_BONUS_ECONOMICS_REPRINT_CANDIDATE_BLOCKED' -or
        $r.issuer_stock_id -ne '1101' -or
        $r.retrospective_ex_right_date -ne '2022-07-21' -or
        $r.candidate_new_shares_per_old_share -ne '0.099928258' -or
        $r.candidate_new_shares_per_1000_old_shares -ne '99.928258' -or
        $r.historical_arithmetic_between_separately_republished_sources_matches -ne $true -or
        $r.original_twse_14_month_28_response_receipts_guard_passed -ne $true -or
        $r.original_mops_publication_byte_archive_authenticated -ne $false -or
        $r.original_mops_first_publication_timestamp_authenticated -ne $false -or
        $r.per_old_share_bonus_factor_approved_for_price_adjustment -ne $false -or
        $r.forward_adjusted_total_return_labels_approved -ne $false -or
        $r.production_neon_backfill_approved -ne $false -or
        $r.neon_writes -ne 0 -or
        $r.line_messages_sent -ne 0 -or
        $r.model_release -ne 'BLOCKED') {
        throw '股票股利候選來源或風險門檻不符'
    }

    Write-Host '1101 股票股利候選數值核對 PASS'
    Write-Host "每千股配發候選：$($r.candidate_new_shares_per_1000_old_shares)"
    Write-Host "MOPS 原始首次公告已認證：$($r.original_mops_first_publication_timestamp_authenticated)"
    Write-Host "正式還原價量因子已核准：$($r.per_old_share_bonus_factor_approved_for_price_adjustment)"
    Write-Host "Neon 寫入：$($r.neon_writes)"
    Write-Host "模型狀態：$($r.model_release)"
}
~~~

只分享上述五行匿名安全統計，不上傳私人 JSON、AES 價量、密碼、Neon URI。本次不擴大股票母體，仍排除下市股票及 1589；現存上市股的歷史存續者偏差並未消失。

後續需取得原始 MOPS 2022/07/06 公告、所有修正版本及當時的可得時間，並核對正式股本註冊及畸零股，才可以提出經濟價量調整方案。全五年歷史、PIT、樣本外 alpha 仍是獨立阻礙。
