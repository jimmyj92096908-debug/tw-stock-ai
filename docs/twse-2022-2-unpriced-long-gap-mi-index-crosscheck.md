# 2022 年兩段官方有日期、但收盤價無法驗證：MI_INDEX 第二來源唯讀核對

## 已通過的 PR #239 真實結果

擁有者 2026-11-23 已於本機成功執行 `TWSE_2022_30_GAPS_OFFICIAL_STOCK_DAY_MONTHLY_OBSERVATION_PASS`，查詢免費證交所 40 個不同股票／月份，取得 30 段各至少 6 個已觀測來源日缺口的結論：**0 段**找到正常有效的月行情收盤日期、**2 段**有官方 `STOCK_DAY` 日期列但收盤價沒有正價或成交股數無法驗證、**28 段**在相應來源區間完全查不到官方日期列、**0 段**官方月資料無回應。這仍不構成 28 段「正式停牌」或 2 段「應補 K 棒」的證明。

## 第二個免費官方來源交叉核對

只針對那 2 段 `official_rows_but_unverified_close_in_gap_window` 中 PR #239 私有報告已記載的**確切日期**，透過證交所 `https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX` 的官方每日 `ALLBUT0999` 多股票行情資料，按**交易日去重**各查一次。最多查 30 個 2022 年平日，不查完整市場或重爬所有 2022 日。一次 HTTP 來源回應不超過 12MB，限定官方網址主機／端點／查詢日與資料型態，禁止自動重新導向，要求含 `證券代號`、`成交股數`、`收盤價` 的表格。

交叉結果只保留原股票代號、日期、官方來源 SHA256 和四種分類：

- `VALID_POSITIVE_CLOSE`：官方每日全市場資料含該檔正收盤價且成交股數 >= 0；仍需逐筆 OHLCV 與原 AES+Neon 日期鍵核對，**不可自動補價**
- `LISTED_BUT_UNPRICED_OR_UNVERIFIABLE`：官方每日來源有該股票列，但仍沒有可驗證的正價；不等於正式停牌
- `MI_INDEX_NO_STOCK_ROW_NOT_PROOF_OF_HALT`：官方每日來源找不到股票列；不等於已查證停牌、退市或交易故障
- `MI_INDEX_DAY_RESPONSE_NOT_VERIFIABLE`：官方日期回應無法使用；保留待查

本方法比 PR #239 多交叉**同一交易所的另一組公開日資料**，但它不是法律意義上的完全獨立第三方佐證，也不是 TWTAWU 正式停牌公告查詢。

原本 PR #239 私有 JSON 與已成功的 PR #238、#237 等資料全部不覆寫；只在新私有報告中留下有限的資料日期與來源雜湊，不保存實際 OHLCV、成交量數值、Neon URI 或 AES 金鑰。使用 GitHub 合成資料 CI；真實結果須在你的 Windows 電腦上通過。

## Windows PowerShell 5.1 本機操作

這次免 Neon 連線、免 AES 解密，只需要前一份 PR #239 成功報告。官方來源最多 30 次免費請求。

```powershell
& {
  $ErrorActionPreference = 'Stop'
  cd "$HOME\tw-stock-ai"
  git pull --ff-only origin main
  if ($LASTEXITCODE -ne 0) { throw 'GitHub 更新失敗' }

  $base = "$HOME\TwStockPrivate"
  $prior = Join-Path $base 'aes-neon-2022-30-gaps-official-stockday-months-20261123.json'
  $out = Join-Path $base 'aes-neon-2022-2-unpriced-long-gap-mi-index-20261123.json'
  if (!(Test-Path $prior)) { throw '缺少已通過的 PR239 官方月行情日期報告' }
  if (Test-Path $out) { throw '新報告已存在，禁止覆寫' }

  python -m scripts.twse_2022_2_unpriced_gap_daily_mi_index_readonly `
      --prior-239-month-report "$prior" `
      --out "$out"
  if ($LASTEXITCODE -ne 0) { throw '兩段不明收盤價與每日官方資料比對未通過' }
  if (!(Test-Path $out)) { throw '沒有產出新的私有報告' }

  $r = Get-Content $out -Raw | ConvertFrom-Json
  [PSCustomObject]@{
    需查核的股票日期 = $r.individual_unpriced_official_stock_day_dates_to_crosscheck
    官方每日查詢次數 = $r.independent_official_market_daily_requests
    模型發布狀態 = $r.model_release
  } | Format-List
  $r.source_date_observation_classes | Format-List
  $r.owner_private_second_source_daily_date_checks |
      Select-Object stock_id,original_monthly_stock_day_unverified_close_date,
          independent_daily_all_stock_observation | Format-Table -AutoSize
}
```

預期成功狀態：`TWSE_2022_TWO_UNPRICED_LONG_GAPS_SECOND_SOURCE_DAY_CHECK_PASS`。

此狀態只認證「依舊版私有報告中的 2 段、對照官方每日行情日期來源已完成核查」。**正式停牌與總報酬沒有通過驗收**，不會自動刪除或補寫價格。其餘 28 段仍需要 TWSE 官方停復牌、歷史板別／停止買賣等公告交叉核對。Neon 0 讀／0 寫、LINE 0 次、零付費、排除下市股票與 1589，正式模型 `BLOCKED`。