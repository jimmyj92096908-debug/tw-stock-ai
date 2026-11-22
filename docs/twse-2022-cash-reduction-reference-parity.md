# 2022 現金減資換股：原始行情與復牌參考價雙重查核（唯讀）

**範圍**：只驗證 2327 國巨與 2603 長榮 2022 現金減資的原始股價來源、2022 年當時已公告的換股比例及復牌理論參考價。先前的 2021+2022 個股實際交易日 240 筆暖機報告已在本人電腦驗收，本工具不重新宣稱或覆寫該結果。

## 當年已公布的事件資料

| 代碼 | 舊股最後成交日 | 現金返還／舊股 | 新股／舊股 | 復牌日 | 理論參考價 | 退還現金發放日 |
|---|---|---|---|---|---|---|
| 2327 | 2022-10-19 | NTD 2.0407502943 | 0.79592497057 | 2022-10-31 | NTD 334.15 | 2022-11-03 |
| 2603 | 2022-09-06 | NTD 6 | 0.4 | 2022-09-19 | NTD 187 | 2022-09-29 |

- 公告（含停牌日、減資比例與現金返還）轉載：https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=85c1b885-37e6-4918-81a4-5f1919977754 （國巨，2022-10-07）
- 公告轉載：https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=0b187777-3784-4e7d-aeed-60e3a85b216f （長榮，2022-08-24）
- 歷史股價佐證：https://tw.stock.yahoo.com/news/%E5%9C%8B%E5%B7%A831%E6%97%A5%E6%81%A2%E5%BE%A9%E4%BA%A4%E6%98%93-%E5%8F%83%E8%80%83%E5%83%B9334-15%E5%85%83-201000402.html 及 https://www.cna.com.tw/news/afe/202209060152.aspx
- 復牌參考價佐證：https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=d7bb005a-ee91-478f-98a3-de9151b0defc 及 https://www.cna.com.tw/news/afe/202209190033.aspx
- TWSE 計算規則：https://investoredu.twse.com.tw/pages/TWSE_InvestmentQA.aspx?ID=1

## 核對公式與限制

現金減資復牌的理論參考價 = (舊股最後一日收盤價 − 每股退還現金) / 每舊股換發新股數。國巨當年收盤 268，未取交易跳動單位的理論值約 334.15116（對照公布 334.15）；長榮當年收盤 80.8，理論值 187。交易所開盤競價基準的升降單位和公布理論參考價不是同一件事。

同一舊股在復牌後的**毛權益經濟價值**為「新股數 × 復牌日真實收盤價 + 有權領取之減資現金」。它不代表現金當天已經入帳、可立即再投資，也不是扣除稅費、股利及交易成本的完整總報酬。不能直接把復牌股價／舊股股價當成模型報酬，不能用公式結果偽造停牌期間每日成交價。

程式將驗證 2022 AES-GCM 完整性，對既有 Neon 固定20檔做 READ ONLY + ROLLBACK 查詢，與早前獨立的 2022 研究報告逐欄比對，從官方來源股價定位兩檔的停牌前最後交易日和復牌日，對照上述同期出版數字；若報告漂移、少一根真實成交 K 線、停牌日出現偽造資料、復牌資料不合法，全部拒絕。只在本人電腦私有目錄新建聚合證據 JSON，不公開股價。

## PowerShell：由本人本機執行

以下程式碼須一次整段貼入同一 PowerShell 工作階段（不要貼出 Neon URI 或 AES 密語）：

    cd "$HOME\tw-stock-ai"
    git pull --ff-only origin main
    if ($LASTEXITCODE -ne 0) { throw "Git 更新失敗" }
    $env:PYTHONPATH = "$PWD;$PWD\src"
    $env:TWSE_KEY_GUI_PROMPT = "1"
    if ($env:DATABASE_URL -notmatch '^postgres(ql)?://') { throw "Neon URI 未設定" }
    $source = "$HOME\TwStockPrivate\aes-neon-240-stock-gaps-20261123.json"
    $out = "$HOME\TwStockPrivate\aes-neon-2022-reduction-reference-20261123.json"
    if (!(Test-Path $source) -or (Test-Path $out)) { throw "來源不存在或輸出已存在" }
    python -m scripts.twse_2022_cash_reduction_reference_readonly `
        --archive-2022 "$env:LOCALAPPDATA\tw-stock-private\prices" `
        --key-vault "$env:LOCALAPPDATA\tw-stock-private\history.twsekey" `
        --source-report "$source" `
        --out "$out"
    if ($LASTEXITCODE -ne 0) { throw "減資參考價驗收失敗" }

正式模型仍 BLOCKED；股票範圍仍是現行上市且排除 1589 與下市股票；不更新 Neon，不發送或修改 LINE，不新增付費資源。下個階段才是基於正確價格尺度及事件分割的 SMA240、法人除權息總報酬、as-of 時序與 Walk-forward 防洩漏驗證。