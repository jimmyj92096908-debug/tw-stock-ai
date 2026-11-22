# 2327／2603：2022 年減資換股的「單一事件價格尺度」SMA240 研究驗收

本工作建立在三個**已由本人本機實際驗收**的獨立私有證據之上：2022 固定20檔 AES×Neon 唯讀來源報告、2021+2022 每檔 267 筆真實個股交易日暖機報告、2022 年兩檔的原始收盤價×同期現金減資復牌理論參考價比對報告。新的工具會再次完整驗證 2021/2022 AES、重新從 Neon 唯讀查核 2022 原始行情，並比對三份私有 JSON 的內容，任何飄移都拒絕。

## 僅限 2022 年底 as-of 的研究計算

對每檔保留最新 **240 筆真實有成交行情**，不以市場日期補入停牌的 14 筆假價格。僅針對本次已驗證的現金減資事件，將事件前**每股舊股收盤價**換成與復牌後新股可比較的**現金扣除、每新股價格尺度**：

    單次減資事件前價格尺度 = (舊股實際收盤價 − 每舊股退還現金) / 每舊股可換得新股數

對復牌後的真實交易日保留原始**新股**收盤價，按 240 筆算術平均，以 `Decimal` 避免二進位浮點誤差。事件當年的復牌理論參考價必須與公告數值相符。要求分析日期**晚於新股復牌及退還現金發放日**，不能將此工具套用在事件公布前的模擬歷史訊號，也不得視為能於停牌日交易。

**此非正式「完整調整後 SMA240」。** 尚未驗收其他除權、除息、股票分割、原始行情是否反映全部事件、現金入帳可用日、交易成本、稅負與 total-return 標籤。對價格系列直接作單次事件調整，不等於經濟總報酬指數，也不能代替 PIT 歷史股票母體、五年歷史完整驗收、Walk-forward 或模型發布。正式交易、預測和 LINE 發送一律 BLOCKED。

## 本機 Windows PowerShell（請整段執行）

使用原本已有的 2021/22 加密檔案，不新增歷史行情、不寫入 Neon，不修改 LINE，輸出一個不含原始股價、調整價或實際 SMA 數字的私人 JSON。請在本機已正確設定**安全輪替過**的 `DATABASE_URL`，不要提供 URI、密語、JSON 或 AES 檔案。

```powershell
cd "$HOME\tw-stock-ai"
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw 'Git 更新失敗' }
$env:TWSE_KEY_GUI_PROMPT = '1'
$env:PYTHONPATH = "$PWD;$PWD\src"
if ($env:DATABASE_URL -notmatch '^postgres(ql)?://') { throw 'Neon URI 尚未設定' }
$base = "$HOME\TwStockPrivate"
$source = Join-Path $base 'aes-neon-240-stock-gaps-20261123.json'
$warmup = Join-Path $base 'aes-neon-2021-22-real-traded240-20261123.json'
$reference = Join-Path $base 'aes-neon-2022-reduction-reference-20261123.json'
$output = Join-Path $base 'aes-neon-2022-event-only-sma240-20261123.json'
foreach ($p in @($source, $warmup, $reference)) { if (!(Test-Path $p)) { throw '缺少必要的先前私有報告' } }
if (Test-Path $output) { throw '輸出報告已存在，禁止覆寫' }
python -m scripts.twse_2022_reduction_only_240_sma_readonly `
    --archive-2021 "$HOME\TwStockPrivate\archives" `
    --archive-2022 "$env:LOCALAPPDATA\tw-stock-private\prices" `
    --key-vault "$env:LOCALAPPDATA\tw-stock-private\history.twsekey" `
    --source-report "$source" `
    --warmup-report "$warmup" `
    --reference-report "$reference" `
    --out "$output"
if ($LASTEXITCODE -ne 0) { throw '單一減資事件 SMA240 研究驗收失敗' }
$report = Get-Content $output -Raw | ConvertFrom-Json
$report.stock_capital_reduction_only_research_witnesses | Select-Object stock_id,asof_market_session,last240_real_traded_days,2022_cash_reduction_only_decimal_sma240_computed_in_ram,fully_adjusted_sma240_release_approved | Format-Table -AutoSize
```

若回報 `CASH_REDUCTION_ONLY_2022_REAL_TRADED_240_SMA_RESEARCH_PASS` 且兩檔都有 240 筆真實行情，僅代表**單次減資事件的價格尺度 SMA240 在記憶體算術上驗收通過**；原先固定20檔市場日 SMA 完整率仍為 18/20。不得將它當作全部歷史資料修正成功、已完成模型或投資訊號。

**限制持續維持：** 不付費、不納入下市股票或 1589、不修改 LINE、不寫入 Neon 正式資料、不發布模型。