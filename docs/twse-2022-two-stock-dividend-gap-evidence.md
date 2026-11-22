# 2022 年 2327、2603 已有當年除息報導，但 Neon 公司行動盤點為零

## 真實已確認狀態與不可推論部分

使用者於 Windows PowerShell 執行 PR #224 本機 `2022_TWO_STOCK_RECORDED_ACTION_COVERAGE_READONLY_AUDIT_PASS`：2021-12-30～2022-12-30 兩檔 `corporate_actions` 各 0 筆。此結果只表示 **Neon 既有表尚無該區間的公司行動紀錄**，並不是沒有除息或減資。

當年公開歷史資料提供至少兩筆事件存在的獨立佐證：

| 股票 | 已發生的 2022 年除息日期 | 同期證據 |
|---|---|---|
| 2327 國巨 | 2022-07-04 | 2022-07-04 中央社除息當日報導 https://www.cna.com.tw/news/afe/202207040027.aspx；2022-06-08 股東會通過現金股利報導 https://www.cna.com.tw/news/afe/202206080024.aspx |
| 2603 長榮 | 2022-06-29 | 2022-05-31 除息日、付款日決定報導 https://www.cna.com.tw/news/afe/202205310431.aspx；2022-06-29 除息當日報導 https://www.cna.com.tw/news/afe/202206290418.aspx |

**精確現金股利每股數值暫不核定。** 國巨的新聞常用 10 元，但亦有券商報導寫 10.1028 元；長榮有約 18 元的新聞數字及因股本變動公告調整的 17.99999637 元。不能挑一個數字直接寫入資料庫、重算公司行動價格尺度或推算總報酬；須另對照官方原始發放決議、除息參考價與支付日期、股本調整時序。

新離線工具 `scripts.twse_2022_known_dividend_gap_offline` 僅讀取**已驗收的本人私有 PR #224 JSON**。如果某股整個日期區間內已記錄的現金股利為 0，則這個有日期佐證的歷史除息事件確實沒有出現在該盤點中；如已有現金股利 1 筆以上，因 PR #224 僅提供統計總數、沒有逐筆除息日期，仍只能標示為「具體除息日是否對應仍未證明」，不能誤報完成。

## 本機離線執行（不需要 DATABASE_URL 或金鑰）

```powershell
cd "$HOME\tw-stock-ai"
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw 'GitHub 更新失敗' }
$source = "$HOME\TwStockPrivate\aes-neon-2022-two-stock-action-coverage-20261123.json"
$output = "$HOME\TwStockPrivate\aes-neon-2022-known-dividend-gaps-20261123.json"
if (!(Test-Path $source) -or (Test-Path $output)) { throw '來源不存在或輸出已存在，禁止覆寫' }
python -m scripts.twse_2022_known_dividend_gap_offline `
    --prior-action-report "$source" `
    --out "$output"
if ($LASTEXITCODE -ne 0) { throw '獨立除息事件比對未通過' }
$r = Get-Content $output -Raw | ConvertFrom-Json
$r.per_stock_known_dividend_event_gaps |
    Select-Object stock_id,known_historical_cash_dividend_ex_date,prior_neon_stored_cash_dividend_rows_in_entire_window,dated_event_vs_prior_neon_status |
    Format-Table -AutoSize
```

工具只寫本人私有路徑下的新 JSON，不改寫原報告。CLI 不使用 Neon、AES、LINE、付費服務或外部網路，不輸出私有密碼；2022 一年 246 個來源觀測日與 18/20 原始 240 市場日研究基準保持不變，PR #223 單次減資 240 實際交易日研究結果亦保留。

## 下一道未通過的驗收

取得有原始發布／生效日期可追溯的 TWSE 或公司公開資訊觀測站公告，再依來源明細核對最終每股現金、實際除息日期、事件前收盤價、減資換股與股利的先後關係。完整官方來源範圍、歷史股票母體 PIT、除權息後 total-return 標籤和 Walk-forward 均需另外驗收。**不得因兩個有新聞佐證的事件就聲稱 2022 全年公司行動完整，或直接寫入 Neon。正式模型仍 BLOCKED。**