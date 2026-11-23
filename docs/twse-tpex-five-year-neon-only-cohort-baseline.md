# 台股 AI：TWSE＋TPEx 滾動五年行情完整度「Neon 既有資料」唯讀基線

## 為什麼需要這項稽核

截至 2026-11-23，國巨和長榮各 240 筆真實交易日、2022 年已知除息與減資的研究價格尺度已通過所有人本機驗收；PR #228 官方公司行動逐月查核亦通過（13 個月、26 次回應、四個已知事件全部匹配）。但這**絕不代表全上市櫃五年行情覆蓋率已完成**。

為避免把兩檔局部成果誤當成所有股票成果，`scripts.twse_tpex_five_year_neon_only_cohort_readonly` 用**同一個 Neon `REPEATABLE READ, READ ONLY` 快照**，分別測量 TWSE 和 TPEx 當前仍正式上市／上櫃、排除 1589 與 `model_stock_exclusions` 的股票，已有多少真實、來源標籤受控的 `daily_prices`。

以台灣時間今日凌晨為界，統計 [5 年前同日, 今日) 的既存 Neon 來源，不把今天未收盤的日 K 線算成完整交易日。每一個市場輸出：

- 官方現在仍上市股票分母、真實有效來源日數的六個成熟度分布桶：0、1–59、60–239、240–479、480–999、至少 1000 天
- 至少 240 日及至少 1000 日股票數量
- 分年份（通常橫跨六個曆年）實際有源股票交易的日期數、每日有 500 檔以上有效現在上市股票行情的日期數，以及來源有效個股日 K 總筆數
- Neon 實際資料庫大小與 800 MB 專案內部寫入停止門檻（**本工具本身永遠唯讀**）

這只是資料庫**既有來源**的真實盤點，沒有推算缺少的官方交易日。最重要的是：2021／2022 AES 私有封存未上傳 Neon，因此**不會**把已驗證的 2022 AES 162 日、2021 AES 28 日當成 Neon 有資料，也不能用 Neon 較少的年份資料推論本機根本沒有歷史行情。不同年份仍缺的個股也可能是尚未上市、真實停牌或非共同股，需要後續來源核對。

技術風險明示：當前上市母體含存活者偏差；本工具只有 `close > 0` 和 `volume >= 0` 加來源白名單的基本驗證，不能代替完整 OHLCV 一致性、官方原始來源重驗、原始公告時間追溯、除權息後 total return、五年樣本外 walk-forward。1000 日不是五年每一天完整。報告永遠標示 `five_year_history_completed=false` 及 `model_release=BLOCKED`。

## Windows PowerShell 本機唯讀執行

只需要本機安全設定好的 Neon `DATABASE_URL`，不需要 AES 金鑰，不新增官方 HTTP 請求。不得將 Neon URI 或 PowerShell 環境變數的密碼上傳聊天或 GitHub。

```powershell
cd "$HOME\tw-stock-ai"
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw 'GitHub 更新失敗' }
if ($env:DATABASE_URL -notmatch '^postgres(ql)?://') { throw 'Neon 唯讀查詢所需的本機 URI 未設定' }

$out = "$HOME\TwStockPrivate\aes-neon-five-year-current-listed-cohort-20261123.json"
if (Test-Path $out) { throw '前次稽核報告已存在，禁止覆寫' }
python -m scripts.twse_tpex_five_year_neon_only_cohort_readonly --out "$out"
if ($LASTEXITCODE -ne 0) { throw '五年 Neon 唯讀股票成熟度稽核失敗' }

$r = Get-Content $out -Raw | ConvertFrom-Json
@('twse','tpex') | ForEach-Object {
    $m = $r.market.$_
    [PSCustomObject]@{
        市場 = $_
        今日仍上市櫃 = $m.official_current_listed_stocks_excluding_1589
        至少240天 = $m.with_at_least_240_valid_stored_days
        至少1000天 = $m.with_at_least_1000_valid_stored_days
    }
} | Format-Table -AutoSize

$r.market.twse.yearly_neon_source_observations | Format-Table -AutoSize
$r.market.tpex.yearly_neon_source_observations | Format-Table -AutoSize
```

**嚴格承諾：** 若官方上市母體快照過期或有缺漏、有效交易日計數矛盾、Neon 交易逾時等，驗收直接失敗；不能用目前的 `stock_master` 或用「日期接近五年」把結果補零、補假行情或冒充完成。避免反覆高頻執行；一個成功快照足夠作為下一階段本機 AES＋Neon 合併覆蓋率的基線。

維持零額外付費、Neon 不寫入、LINE 不修改／不新增訊息、排除下市股票及 1589、模型發佈 `BLOCKED`。