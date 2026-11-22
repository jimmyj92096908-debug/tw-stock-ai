# 2022 年 2327／2603：兩項已核實現金事件的 SMA240 價格尺度（僅研究）

前置證據均已由擁有者電腦實際執行驗收：原始 TWSE 2022 AES + Neon 唯讀固定 20 檔、2021+2022 兩檔各 267 筆真實交易日暖機、兩檔 2022 現金減資理論參考價、單次減資尺度 SMA240、Neon 在上述 240 日範圍內公司行動各 0 筆、兩筆現金股利缺口、2022 兩次精確股利與除息參考價。

## 事件發生順序及精確公布值

| 股票 | 現金除息日 | 股利／每舊股 | 現金減資舊股最後交易日 | 新股恢復交易日 | 減資退現金／每舊股 | 新股／舊股 |
|---|---|---:|---|---|---:|---:|
| 2327 | 2022-07-04 | 10.10281345 元 | 2022-10-19 | 2022-10-31 | 2.0407502943 元 | 0.79592497057 |
| 2603 | 2022-06-29 | 17.99999637 元 | 2022-09-06 | 2022-09-19 | 6 元 | 0.4 |

現金股利證據：臺灣期交所 https://www.taifex.com.tw/file/taifex/CHINESE/11/attach/2327_20220704.pdf；長榮 2022-05-31 重大訊息公告轉載 https://news.cnyes.com/news/id/4882348。現金減資比率與資料見 `docs/twse-2022-cash-reduction-reference-parity.md`；除息參考價見 `docs/twse-2022-two-stock-precise-exdiv-refs.md`。

## 算式：現金除息和後續現金減資按照事件時序轉換

限定 as-of 2022-12-30，假設只處理上述 **兩項已核實**事件。採用 240 個真的有成交且重新認證的個股交易日序列，不偽造停牌日 K 線；依不同時間點的原始股價 P 計算：

```text
2022 除息日前：            (P - 2022 該次每股現金股利 - 2022 該次減資退還現金) / 每舊股換新股比率
除息當日至減資舊股末日：   (P - 2022 該次減資退還現金) / 每舊股換新股比率
減資復牌新股第一交易日後： P
```

最後 240 筆尺度轉換後的 `Decimal` 收盤價在電腦**記憶體**中求算術平均，驗證相對於之前僅計算單次減資 SMA 的數值差恰等於 `(除息前真實交易日數 × 當次每股股利 ÷ 減資換股比例) ÷ 240`。不輸出個股原始行情、尺度調整價格、SMA 數字或進出場訊號。

**這不是完整經濟報酬率！**

以上僅為「兩個已知事件的現金扣除、以新股為單位的價格尺度」，不等於股東實際取得現金時間及可再投入金額，不等於真實持有或再投入股利的 total-return 指數；完整歷史配息、股票股利、其他公司行動、PIT 上市母體、每筆原始公告時間、五年覆蓋、Walk-forward 及正式交易依然未驗收。不可把 `research PASS` 視為「完整調整後 SMA240 已完成」。

## 本機 PowerShell 唯讀驗收

請用已有的 2021 與 2022 私有 AES、六份先前驗證 JSON，以及本機已**安全輪替過**的 Neon `DATABASE_URL`。不可上傳私人金鑰或完整連線字串。

```powershell
cd "$HOME\tw-stock-ai"
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw '更新程式失敗' }
$env:PYTHONPATH = "$PWD;$PWD\src"
$env:TWSE_KEY_GUI_PROMPT = '1'
if ($env:DATABASE_URL -notmatch '^postgres(ql)?://') { throw 'Neon 連線未設定' }
$base = "$HOME\TwStockPrivate"
$inputs = @{
    source = Join-Path $base 'aes-neon-240-stock-gaps-20261123.json'
    warmup = Join-Path $base 'aes-neon-2021-22-real-traded240-20261123.json'
    reduction = Join-Path $base 'aes-neon-2022-reduction-reference-20261123.json'
    single = Join-Path $base 'aes-neon-2022-event-only-sma240-20261123.json'
    gap = Join-Path $base 'aes-neon-2022-known-dividend-gaps-20261123.json'
    dividend = Join-Path $base 'aes-neon-2022-two-stock-exdiv-reference-20261123.json'
}
$out = Join-Path $base 'aes-neon-2022-known-two-cash-events-sma240-20261123.json'
foreach ($path in $inputs.Values) { if (!(Test-Path $path)) { throw '缺少先前私有報告' } }
if (Test-Path $out) { throw '新報告已存在，不允許覆寫' }
python -m scripts.twse_2022_known_cash_events_sma240_readonly `
    --archive-2021 "$HOME\TwStockPrivate\archives" `
    --archive-2022 "$env:LOCALAPPDATA\tw-stock-private\prices" `
    --key-vault "$env:LOCALAPPDATA\tw-stock-private\history.twsekey" `
    --source-report "$($inputs.source)" `
    --warmup-report "$($inputs.warmup)" `
    --reduction-reference-report "$($inputs.reduction)" `
    --reduction-sma-report "$($inputs.single)" `
    --dividend-gap-report "$($inputs.gap)" `
    --dividend-reference-report "$($inputs.dividend)" `
    --out "$out"
if ($LASTEXITCODE -ne 0) { throw '兩個已知現金事件 SMA240 唯讀研究驗收失敗' }
$r = Get-Content $out -Raw | ConvertFrom-Json
$r.per_stock_two_known_event_research_proofs |
    Select-Object stock_id,genuine_source_stock_trading_days,pre_ex_dividend_old_share_stock_days_transformed,between_dividend_and_capital_reduction_stock_days_transformed,exact_decimal_sma240_in_ram |
    Format-Table -AutoSize
```

此工具不修改 Neon 資料、不修改 LINE、不發訊息、不付費、不納入下市股票及 1589，不建立假股價，也不發布正式投資模型。`BLOCKED` 持續保留。