# 2022 年 30 段長缺口：證交所官方 STOCK_DAY 日期來源驗收（唯讀）

## 先前已正式通過的資料

2026-11-23 擁有者本機 PR #238 正式成功狀態 `TWSE_2022_ALL_30_LONG_SOURCE_ABSENCE_OFFICIAL_QUEUE_READONLY_PASS`，目前仍上市 1,092 檔 TWSE 股票（排除下市、1589）中有 116 檔的 2022 年 **804 個未觀測到來源的股票日期組合**，分成 526 段，其中 30 段至少 6 個已觀測官方來源日。最長一段已核對：1472 的 2022-03-10 至 2022-03-22，共 9 個來源日。此**不是應補 804 筆行情的證據**。

## 這次新增官方原始行情「有沒有日期列」查核

證交所的免費「個股日成交資訊」提供歷史資料，可按股票代號及月份查詢：<https://www.twse.com.tw/zh/trading/historical/stock-day.html>。工具只查公開官方 `https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY` 的 2022 月份資料，不使用任何付費資料源。

新增 `scripts.twse_2022_30_gap_official_stock_day_monthly_readonly`，先從你原本成功且**不可覆寫**的 PR #238 私有 JSON 讀取 30 段各自的股票代號與起迄來源日期。對其落入的股票／月份鍵去重；每月僅提出一次 HTTPS 官方查詢，限制不超過 90 次、單回應 2 MB，拒絕重新導向、日期跨月、股票代號或月份被替換、重複日期、錯誤欄位與非官方主機。

這項工具查找官方原始月資料中「確實有來源日期且收盤價大於 0、成交股數 >= 0」的紀錄，**只輸出日期和 SHA256 證據，絕不輸出開高低收與成交量數值**。分類：

- 官方缺口時間範圍內存在至少一個有效行情來源日期：證明有日期線索，**尚須逐日核對原本 AES＋Neon 欠缺的個別日期鍵**才能確定要不要回補
- 官方查到日期列但收盤價無法驗證：保留待查
- 官方回應正常但該日期區間無列：不代表已確認官方停牌
- 官方該月回傳「查無資料」或其他非 OK 訊息：來源不足，分類為待查；也不表示停牌

因 PR #238 的長缺口清單只存起迄日期與缺口來源日數（不是全部逐日來源日期鍵），即使官方在相同時間區間有成交列，也**不能僅靠此工具準確確認 804 個來源日中哪天真正缺了 K 線**。正式補價必須另做逐筆行情證據核對、歷史上市資格及交易所暫停／恢復交易查詢。

## Windows PowerShell 5.1：零成本、免 Neon 帳密、免 AES 金鑰

完整程序一次性處理全部 30 段，官方來源若拒絕或回傳格式改變則**拒絕報告成功**。新結果僅寫你電腦上的 `TwStockPrivate`，所有先前驗收報告不覆寫。

```powershell
& {
  $ErrorActionPreference = 'Stop'
  cd "$HOME\tw-stock-ai"
  git pull --ff-only origin main
  if ($LASTEXITCODE -ne 0) { throw 'GitHub 更新失敗' }
  $base = "$HOME\TwStockPrivate"
  $prior = Join-Path $base 'aes-neon-2022-30-long-source-gaps-for-official-halt-check-20261123.json'
  $out = Join-Path $base 'aes-neon-2022-30-gaps-official-stockday-months-20261123.json'
  if (!(Test-Path $prior)) { throw '缺少 PR238 已通過的 30 段原始私有報告' }
  if (Test-Path $out) { throw '輸出報告已存在，禁止覆寫' }

  python -m scripts.twse_2022_30_gap_official_stock_day_monthly_readonly `
      --prior-238-report "$prior" `
      --out "$out"
  if ($LASTEXITCODE -ne 0) { throw '30 段官方原始月行情日期對帳失敗，禁止推定漏價或停牌' }
  $r = Get-Content $out -Raw | ConvertFrom-Json
  Write-Host "官方股票／月份查詢數：$($r.official_unique_issuer_month_requests)"
  $r.classification_counts | Format-List
  $r.owner_private_official_monthly_date_check_results |
      Select-Object -First 10 stock_id,first_unobserved_source_day,
          last_unobserved_source_day,observation_classification |
      Format-Table -AutoSize
}
```

預期成功狀態 `TWSE_2022_30_GAPS_OFFICIAL_STOCK_DAY_MONTHLY_OBSERVATION_PASS`。該字串僅代表**已完成官方月份來源的日期存在性查詢**，不是股價或停牌全部完成核驗。若某月回傳非 OK，報告也會列出官方資料未能判定的數量。

Neon 寫入 0、LINE 訊息 0、零額外付費、不含下市股票與 1589、過去驗收報告保持原樣。正式模型 `BLOCKED`，除權息與歷史 point-in-time 上市資格仍需額外證據。