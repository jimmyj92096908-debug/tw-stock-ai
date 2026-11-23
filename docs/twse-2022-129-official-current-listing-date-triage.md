# 2022 年無行情 129 檔：TWSE 官方上市日期核對（只讀、不是歷史 PIT）

## 已通過本機的來源時間線

擁有者於 2026-11-23 已成功驗收 PR #233：當前仍上市的 1,092 檔研究股票排除 1589 後，有 129 檔在 2022 年已認證 AES＋Neon 來源日完全沒有紀錄。這 129 檔於 Neon 2023–2026 最早有效來源紀錄分布為 **2023 年 28、2024 年 36、2025 年 35、2026 年 30、截至基線窗口都沒紀錄 0**。這些是資料庫的*首次儲存有效行情*，不是 IPO 日期。

## 官方來源核對

TWSE 公開免費 OpenAPI `https://openapi.twse.com.tw/v1/opendata/t187ap03_L`（上市公司基本資料），其欄位包括 `公司代號`、`上市日期`（西元 YYYYMMDD）、`出表日期`（民國 YYYMMDD）。本工具一樣使用已本機驗收過的 2022 AES 封存及現有 Neon **同一個 READ ONLY snapshot** 的當前上市股票與個股日期鍵來找出這 129 檔；另外只做 **一次**免費官方公用 HTTPS 請求，比對官方現在公布的上市日期。

安全防護：HTTPS TWSE 網域（拒絕轉址）、限制單筆回傳不超過 8MB、限制官方 750–2000 筆有效公司清單、來源 `出表日期` 14 日內且來源各筆版本一致、同股票代號重複拒絕、原本 2022 129 檔不一致拒絕、Neon 第一筆來源日早於当前上市日標示資料來源矛盾（不當作沒問題）。新輸出**只包含聚合公司檔數、來源回應 SHA256、官方出表日**，不包含個股代號、姓名、地址、電話、原始股價、Neon URI 或 AES 金鑰。

在 129 檔中以官方**目前的**上市日期分為：

- 記載 2023、2024、2025、2026 年上市：可取得官方當前掛牌日期證據，但**不推定是首次公開發行 IPO**，因為可能上櫃轉上市、重新上市或證券歷史變動
- 官方當前上市日期為 **2022-12-31 或以前**：2022 年完全沒行情，列為需要優先研究的來源時間線矛盾／疑點；尚不能認定必定漏抓資料
- 官方資料缺少、無法解析或無匹配股票：保留待人工查核，不可補假價格

這不等於完整 2022 或五年上市股票歷史 PIT，也不等於已核實停牌、股本變動、除權息或 total-return 模型可發布。

## Windows PowerShell 私有本機執行

使用已設定的 `DATABASE_URL`（只在本機 PowerShell 工作階段，**不可將 URI 貼在聊天或上傳 GitHub**）和 AES vault。報告另存新檔；舊 PR #233 驗收不覆寫。

```powershell
& {
  $ErrorActionPreference = 'Stop'
  cd "$HOME\tw-stock-ai"
  git pull --ff-only origin main
  if ($LASTEXITCODE -ne 0) { throw 'GitHub 更新失敗' }
  if ($env:DATABASE_URL -notmatch '^postgres(ql)?://') {
      throw '請先於目前 PowerShell 視窗安全設定 Neon 連線'
  }
  $env:TWSE_KEY_GUI_PROMPT = '1'
  $private = "$HOME\TwStockPrivate"
  $panel = Join-Path $private 'aes-neon-240-stock-gaps-20261123.json'
  $five = Join-Path $private 'aes-neon-five-year-current-listed-cohort-20261123.json'
  $overlay = Join-Path $private 'aes-neon-2022-five-year-source-overlay-20261123.json'
  $out = Join-Path $private 'aes-neon-2022-129-official-current-listing-date-20261123.json'
  foreach ($f in @($panel,$five,$overlay)) {
      if (!(Test-Path $f)) { throw '找不到既有的前置驗收證據' }
  }
  if (Test-Path $out) { throw '目標檔案已存在，禁止覆寫' }

  python -m scripts.twse_2022_aes_neon_eligible_density_readonly `
      --archive-2022 "$env:LOCALAPPDATA\tw-stock-private\prices" `
      --key-vault "$env:LOCALAPPDATA\tw-stock-private\history.twsekey" `
      --source-panel-report "$panel" `
      --five-year-neon-report "$five" `
      --prior-overlay-report "$overlay" `
      --post2022-firstseen `
      --official-current-listing-audit `
      --out "$out"
  if ($LASTEXITCODE -ne 0) { throw '129 檔官方上市日期核對未通過' }
  if (!(Test-Path $out)) { throw '沒有成功的私人報告' }

  $r = Get-Content $out -Raw | ConvertFrom-Json
  $x = $r.owner_129_no2022_current_twse_official_listing_date_triage
  [PSCustomObject]@{
      無2022來源檔數 = $x.owner_2022_no_valid_source_stock_count
      官網記載2023以後上市 = $x.current_twse_listing_after_2022_count
      官網記載2022以前已上市 = $x.current_twse_listing_on_or_before_2022_count
      官方日期缺漏或格式不正確 = $x.current_twse_listing_missing_or_invalid_count
      官方來源出表日 = $x.source_metadata_observed_at
  } | Format-List
  $x.source_listing_date_bucket_counts | Format-List
}
```

成功訊息為 `TWSE_2022_NO_SOURCE_OFFICIAL_LISTING_DATE_TRIAGE_READONLY_PASS`。若官方介面無法取得、與現有 Neon 官方在市母體不一致或來源版本過期，應留待查核，**不得自行推論／造假 2022 來源 K 線**。

維持不花費、Neon 唯讀、LINE 不修改且不發送、排除下市股票及 1589、不給出交易指示、模型 `BLOCKED`。