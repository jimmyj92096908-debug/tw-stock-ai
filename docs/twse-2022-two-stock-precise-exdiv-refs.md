# 2022 國巨、長榮：有公告日期的現金股利與真實除息行情對帳（Neon READ ONLY）

## 本次來源分級

PR #225 在本人電腦已通過 `TWO_STOCK_2022_KNOWN_DIVIDEND_GAP_OFFLINE_PASS`；證明 2327 在 2022-07-04、2603 在 2022-06-29 各有歷史現金股利事件，但先前 Neon 2021-12-30～2022-12-30 的 `corporate_actions` 計數均為 **0**。本 PR 直接核對同期發行公告中更加精確的金額、除息日期，以及本機重新認證的 2022 TWSE 原始股價；不修改既存資料庫、不發布模型。

| 股票 | 最後含息交易日 | 除息日 | 2022 年具日期公告每股現金（NTD） | 同期公告日期 | 預定發放日 | 歷史報導含息收盤價 | 除息參考價（呈現值） |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2327 國巨 | 2022-07-01 | 2022-07-04 | **10.10281345** | 2022-06-17 | 2022-07-22 | 282 | 271.89 |
| 2603 長榮 | 2022-06-28 | 2022-06-29 | **17.99999637** | 2022-05-31 | 2022-07-28 | 108.5 | 90.50 |

重要資料出處：

- **國巨精確數字**：臺灣期貨交易所 2022-06-24 正式公文（台期交字第1110201186號）明確確認國巨 2022-06-17 公告每股 **10.10281345** 元及期貨 2022-07-04 調整，見 https://www.taifex.com.tw/file/taifex/CHINESE/11/attach/2327_20220704.pdf
- 國巨當年除息與參考價 271.89 元，可由歷史除息紀錄及 2022 年 7 月 4 日新聞交叉比對：https://superpy.kgieworld.com.tw/kgipythonapi/stockInfo/finance/exDividend?stockCode=2327 及 https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=13b96ec7-a471-46d2-8dcd-485c49d09a78
- **長榮精確數字**：2022-05-31 公司重大訊息公告轉載，含 17.99999637 元、除息日 2022-06-29、預定發放日 2022-07-28，見 https://news.cnyes.com/news/id/4882348；另見同期中央社 https://www.cna.com.tw/news/afe/202205310431.aspx
- 長榮 2022-06-29 除息參考價 90.5 元及前收盤 108.5 元歷史紀錄：https://superpy.kgieworld.com.tw/kgipythonapi/stockInfo/finance/exDividend?stockCode=2603

注意：國巨早先股東會（2022-06-08）報導僅寫**約 10 元**；後來 2022-06-17 的確切公告是 **10.10281345**。長榮原擬 18 元，因可轉債轉換造成股數變動而調整為 **17.99999637**。不應取四捨五入的新聞金額代替正式宣布的精確計算值。

## 價格公式、來源核對與限制

程式用 `Decimal` 核對 **未取交易價格跳動單位**的除息理論價 = 除息前最後實際收盤價 − 公司公布每股現金股利。國巨理論 271.89718655 元，比對歷史公布呈現的 271.89 元；長榮理論 90.50000363 元，比對 90.50 元。准許公佈價格因最小跳動單位、顯示小數位等差異產生 **嚴格小於 0.01 元**的偏差，不反推出未知整數股數或虛構成交。兩個除息日的**實際交易行情**都必須存在，且原始 2022 AES、Neon READ ONLY 來源面板與前次私有報告不得漂移。

通過僅代表這 **兩個已知歷史除息事件**的公告、原始含息收盤價與顯示參考價對帳成立；不代表 `corporate_actions` 已補齊、不代表 2021-2022 沒有其他股利或股票分割、不代表現金在除息日已可使用、不代表回測已避開所有 PIT 洩漏，也不代表減資前後經濟總報酬或 **完整版 SMA240** 完成。

## 本人 Windows PowerShell 執行方式

請在有安全輪替後 `DATABASE_URL` 的本機 PowerShell 執行（不需提供憑證給他人）：

```powershell
cd "$HOME\tw-stock-ai"
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw 'git 更新失敗' }
$env:PYTHONPATH = "$PWD;$PWD\src"
$env:TWSE_KEY_GUI_PROMPT = '1'
if ($env:DATABASE_URL -notmatch '^postgres(ql)?://') { throw 'Neon URI 未正確設定' }
$old = "$HOME\TwStockPrivate\aes-neon-240-stock-gaps-20261123.json"
$gap = "$HOME\TwStockPrivate\aes-neon-2022-known-dividend-gaps-20261123.json"
$out = "$HOME\TwStockPrivate\aes-neon-2022-two-stock-exdiv-reference-20261123.json"
if (!(Test-Path $old) -or !(Test-Path $gap) -or (Test-Path $out)) { throw '私有報告不存在或輸出已存在' }
python -m scripts.twse_2022_dividend_exref_readonly `
    --archive-2022 "$env:LOCALAPPDATA\tw-stock-private\prices" `
    --key-vault "$env:LOCALAPPDATA\tw-stock-private\history.twsekey" `
    --source-report "$old" `
    --gap-report "$gap" `
    --out "$out"
if ($LASTEXITCODE -ne 0) { throw '兩檔 2022 除息參考價證據驗收失敗' }
$r = Get-Content $out -Raw | ConvertFrom-Json
$r.dated_two_dividend_event_research_witnesses |
    Select-Object stock_id,cash_ex_dividend_date,contemporaneous_declared_cash_per_share_ntd,ex_reference_formula_parity_within_0_01_ntd |
    Format-Table -AutoSize
```

報告只在本人私有資料夾中新增，不覆寫、不輸出原始行情價格。程式不進行任何上傳、資料庫寫入、LINE 發送或自動交易；零額外付費，維持不納入下市股票及 1589，模型發布 **BLOCKED**。