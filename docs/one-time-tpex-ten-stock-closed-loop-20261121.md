# 上櫃下一階段：免費額度內一次性擴充最多 10 檔正式行情，接續完成評分

2026-11-21 資料庫現況：Neon Free、約 228 MB；`stock_master=1991`，有有效收盤的 1,982 檔、具 60 個有效交易日的 1,111 檔、近期非研究排除且可計算的 1,109 檔；目前 `1,109/1,109` 有同股同最後有效日的技術＋SMC＋綜合評分。還有 871 檔雖有行情但不滿 60 日，9 檔完全沒有有效收盤價。

## 現有流程維持原狀

每週二至週六臺灣時間 02:10 的上櫃官方資料匯入仍是最多 10 檔 × 五個月份，03:10 的指標補算仍是每市場最多 20 檔，隨後由原有正式計分流程計算綜合評分。沒有新增任何新的週期性 GitHub Action、付費 API 或 Neon 升級。

## 本次擴充只跑一次

本次在 `.github/workflows/tpex-official-insert-only-history.yml` 增加一個**專用、僅在新增標記檔時才觸發**的受控批次：

- 標記 `.github/tpex-official-history-authorized-batch10-v2-20261121.txt` 只允許在主分支建立一次；既有兩檔 canary 檔不再重用。
- GitHub push 事件的 `head_commit.added` 可能未提供需要的變動清單，故**不得**依賴這個欄位。工作流透過 `actions/checkout` 的 `fetch-depth: 2`，執行 `git diff --name-only --diff-filter=A HEAD^ HEAD`，並以完全符合標記路徑的結果設定 `steps.batch.outputs.extended=true`，才允許**一次性 push**批次擴大至最多 10 檔。其他手動啟動仍維持兩檔，日常排程本就最多 10 檔。
- 使用既有 `tpex_official_history_insert_only.py`，每檔最多五個官方月份，最多 50 次來源要求，來源不合理就回滾、不得假造價格。
- 僅對 `daily_prices` 做 `ON CONFLICT DO NOTHING`，不修改已存在的 `(market,stock_id,trade_date)` 原始行情；免費 800 MB 儲存警戒線仍有效。
- 工作在 `twstock-indicator-catchup` 同一互斥鎖中，官方匯入結束後接續用既有 `new_eligible_score_followon.py` **兩輪各最多五檔**補指標、SMC 以及只新增缺漏的綜合評分；不重算其他約千檔完整評分。
- 最後以 `eligible_100_catchup.snapshot` **唯讀**核實所有目前合格股的同股同日技術＋SMC＋有效評分交集，未全部齊全就標記為失敗，不冒稱 100%。
- 一次性 workflow artifact 保留官方來源摘要與兩輪補算報告；不寫入模型績效資料表、不動 LINE，也不啟動交易。

如果部分官方股票近期沒有真實交易、官方歷史不足或來源出錯，必須保留原來的缺口和執行記錄；即使工作成功，也只能宣稱**當時合格的股票池**完整，不能把 1,991 檔全市場或 AI 獲利模型宣稱為 100%。

## 第一次授權標記的實際結果與修正

第一次標記 `.github/tpex-official-history-authorized-batch10-20261121.txt`
觸發 GitHub run `44867514110`，由於 Actions event 的
`head_commit.added` 判斷為 false，**實際只補了兩檔官方歷史，
不是 10 檔**，且後續增量評分步驟被跳過。
新補資料股票：上櫃 **4305 世坤（62 日）及 4584 君帆（84 日）**，
來源驗證無失敗，原始歷史價格主鍵沒有被覆寫。
後續已使用獨立的合法一次性受控評分工作 `44867648953`
完成兩檔同日指標與綜合評分，正式 Neon 唯讀驗證
**1,111/1,111 檔合格研究池完整**。

為避免重用舊標記造成重複寫入，本次採用全新一次性 v2
授權標記，只有**最新 commit 實際新增該檔**才會開啟 10 檔模式；
未符合就只能執行正常受限的小批次。
所有結果以 GitHub 逐步 log 及當下 Neon 查核為準，不把
工作流程 `success` 當成「10 檔已完成」。

## 測試與驗收

```bash
PYTHONPATH=src python -m unittest \
  tests.test_tpex_official_history_insert_only \
  tests.test_new_eligible_score_followon \
  tests.test_tpex_market_data -v
```

這項新一次性授權是先前已驗證兩檔來源後的保守擴充：**零額外付費、只新增有官方證據的缺漏行情、分批計算、驗收失敗即停止**。若正式 GitHub 執行失敗，應以實際任務記錄及唯讀 Neon 核對為準，不主動無限制重試。
