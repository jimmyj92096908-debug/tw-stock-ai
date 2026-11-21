# 上櫃官方歷史回補下一階段：補齊手動來源→完整評分閉環

目前正式 Neon：1991 股票主檔、其中 1982 有真實正收盤、1141 檔至少 60 個有效收盤；1139/1139 檔符合近期交易日研究門檻且有同股同最後有效收盤日技術＋SMC＋非 NULL 綜合評分，全主檔約 57.2%。841 檔有股價但未滿 60 日，其中 830 檔上櫃只有 1–9 日。

## 既有流程缺口與修改

原本 `.github/workflows/tpex-official-insert-only-history.yml` 的手動 `workflow_dispatch apply:true` 會下載最多 2 檔**官方行情**，卻因兩個後續步驟只在 schedule／一次性標記跑，可能讓新跨過 60 日門檻的股票暫時缺最新技術、SMC 與綜合評分。因此「行情匯入成功」不能代表「研究池驗收完成」。

現在手動經 GitHub 授權 `apply:true` 也會在**同一個已存在的 GitHub Action**中：
1. 依實際 Source DB 挑選最多 **10 檔** `tpex`，每檔最多 **5 個官方月份**，總來源請求最多 50、每次間隔既有 2 秒；
2. 所有真實有效 `daily_prices` **只新增不存在的主鍵**，現有主鍵 `ON CONFLICT DO NOTHING`，不更新價格；
3. 在同一個 `twstock-indicator-catchup` mutex 內接續**兩輪各最多 5 檔** newly-eligible 技術／SMC／綜合評分缺漏；
4. 用 `eligible_100_catchup.snapshot` 再核對**同股票／同最後真實有效收盤日的指標與評分**，任一缺漏則 GitHub Action 失敗；
5. `apply:false` 則不寫正式資料庫。原排程時段、來源上限、FREE 方案 800 MB 保守寫入停止線不變，未新增任何 GitHub cron／付費供應商／LINE 訊息／交易。

本輪另使用一次性精確的 Git 新增檔案
`.github/tpex-official-history-authorized-batch10-v5-20261121.txt` 讓已授權的官方行情回補**額外執行一次**。既有舊 v1~v4 marker 僅保留 Git 歷史，不能再誤觸發擴充模式。

此改進只補更多**官方真實存在**的歷史，不回填停牌、上市前、沒有交易的假 K 棒；也不能由合格池的 100% 推論全部 1991 檔都完整。

## 測試／驗收

```bash
python -m unittest tests.test_tpex_official_history_insert_only tests.test_tpex_market_data tests.test_new_eligible_score_followon -v
```

Python CI 必須先通過、PR 合併後才能新增唯一 marker。實際正式資料庫的新增筆數、跨過 60 日的數量及最新研究池比率必須用該工作證據和 Neon 唯讀 SQL 重新查，不用預期新增 10 檔冒充已經完成。

另外已查核 TWSE／TPEx 官方 OpenAPI 清單；目前未驗證到可直接取得**具有明確可靠會計口徑的全部一般產業現金流量表**兩市免費端點。現金流、FCF、ROE 完整市場驗收仍不能以其他財務項目假造或提前上線。
