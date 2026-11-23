# 2327／2603：2021/12/30～2022/12/30 證交所官方除權息、減資歷史查詢稽核

此階段承接已在擁有者 Windows 真正執行通過的 PR #227：兩檔各 240 個真實個股交易日、2022 年一筆已公告現金除息＋其後一筆現金減資，以精確 `Decimal` 計算**兩項已知現金事件的價格尺度**。資料庫 `corporate_actions` 在該研究日期窗口內兩檔均為 0 筆，因此**不能**證明全部歷史公司行動已補齊。

## 官方來源、查詢限制與已知事件交叉核對

使用原專案現有免費 TWSE 公開網頁 JSON 端點：

- `https://www.twse.com.tw/rwd/zh/exRight/TWT49U`：除權息計算結果
- `https://www.twse.com.tw/exchangeReport/TWTAUU`：減資恢復買賣參考價

逐月對 **2021-12-30 至 2022-12-30** 最多 13 個月、每個月 2 個端點發出 1 次請求（最多 26 次），嚴格限制查詢日期，並核對每筆四位數證券的實際日期是否落在請求月份。若歷史 API 忽略所指定日期、回傳不同來源網域、資料格式無法辨識、來源數量超過上限、證券事件同日同種類重複或原始擷取證據不一致，則拒絕驗收，不會把最近日期資料當成 2022 年歷史結果。

先前獨立來源已驗證四項事件，用於**交叉檢查**而非假定所有歷史事件只有四項：

| 代號 | 事件 | 事件日 |
|---|---|---|
| 2327 國巨 | 現金除息 | 2022-07-04 |
| 2603 長榮 | 現金除息 | 2022-06-29 |
| 2327 國巨 | 現金減資恢復買賣 | 2022-10-31 |
| 2603 長榮 | 現金減資恢復買賣 | 2022-09-19 |

若指定查詢月份內某一已知事件未出現在官方網站結果，報告會顯示 `all_known_previous_events_matched = false`，且列出 `known_previous_event_mismatches`；**不可把它當作無配息或資料完整**。即使全部 26 次請求和已知四項都核對成功，證交所這兩個介面仍不保證涵蓋所有公司行動、2021–22 完整股利權益、股東會資料原始發布時點、拆併股及資本變動，也不能直接當成總報酬資料。

工具只輸出官方每月回傳**筆數、SHA256、兩檔事件日期與類型**，不下載歷史股價、不記錄公司行動的未審核現金或調整係數、不寫入 Neon、不修改任何私有舊報告、不修改 LINE。`observed_at_utc` 是**現在查到該來源的時間**，不代表 2022 當年公告時間；原始 MOPS 發布時間要另行補驗。

## Windows PowerShell 本機執行

本工具使用**前一階段已驗收的私人 PR #227 報告**，不需要資料庫連線、AES 金鑰，也不會使用額外付費 API。

```powershell
cd "$HOME\tw-stock-ai"
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw 'GitHub 更新失敗' }
$source = "$HOME\TwStockPrivate\aes-neon-2022-known-two-cash-events-sma240-20261123.json"
$output = "$HOME\TwStockPrivate\aes-neon-2021-22-frozen2-official-action-monthly-20261123.json"
if (!(Test-Path $source) -or (Test-Path $output)) { throw '前置報告不存在或輸出已存在' }
python -m scripts.twse_2021_22_frozen2_official_action_monthly_audit `
    --month-start '2021-12' `
    --month-end '2022-12' `
    --prior-report "$source" `
    --out "$output"
if ($LASTEXITCODE -ne 0) { throw '官方歷史公司行動查詢驗收未通過' }
$r = Get-Content $output -Raw | ConvertFrom-Json
Write-Host "月份: $($r.requested_month_count)；官方查詢回應: $($r.requested_official_http_source_calls)"
Write-Host "已知事件找到: $($r.known_previous_events_found_matching_source) / $($r.known_previous_events_expected_in_window)"
$r.known_previous_event_mismatches | Format-Table -AutoSize
$r.official_two_stock_events_observed | Select-Object stock_id,event_date,reported_event_category | Format-Table -AutoSize
```

如官方介面遇到拒絕、無法查詢或月份資料缺漏，**不要用空資料補上、不反覆狂發重試，也不要重新跑已成功的舊階段**；保留原始報告並檢查是否有其他可公開驗證的官方資料管道。若本次有事件未匹配，也要將它列為未解決來源覆蓋缺口。這是資料來源能力稽核，並非真正所有公司行動驗收。

**持續保留：** 官方列示目前上市股票範圍、排除下市股票與 1589、零付費、無 Neon 寫入、無 LINE、未重算正式模型、未獲得 PIT 與完整 total-return 認證，`model_release = BLOCKED`。