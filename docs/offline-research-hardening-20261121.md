# 不付費期間的量化研究強化與安全界線（2026-11-21）

本次增量只涉及**離線 Python 模組、合成資料單元測試與本地研究報告**。
沒有新增 GitHub Actions 排程、沒有修改資料庫 schema、沒有從正式
Neon 讀取個股明細、沒有改動原本 50% 覆蓋率回補腳本、沒有重訓舊 AI
模型、沒有更動 LINE Webhook 或呼叫券商 API。不要在回補中重跑第二份補算。

## 1. 比對同一股票、同一最後有效收盤日的 50% 覆蓋率

`src/research_coverage_acceptance.py`：接受兩份由既有
`scripts/coverage_50_catchup.py` 產生的已驗證快照，其中至少含：

`universe`, `priced`, `price_rows`, `latest_price_date`,
`technical_current`, `smc_current`, `both_current`, `scored_current`。

**重要：** 只有 `both_current >= 996` 與
`scored_current >= 996`，不代表這是同樣的 996 檔。此模組
必須額外收到 `scored_and_both_current`（同一股票、同一最後有效
收盤日的三者交集）才會標示
`RESEARCH_COVERAGE_THRESHOLD_VERIFIED`。沒有交集證據即
`COHORT_INTERSECTION_NOT_VERIFIED`，不會虛構成功。

程式中提供選用的純 `SELECT` 查詢常數
`INTERSECTION_SQL` 供**回補完成後**從受保護的唯讀連線手動核對，
不能擅自新增持續性查詢，也不直接查詢 LINE 資料。

`diagnose_missing` 接受明確記錄的每檔資料完整度旗標，分類：
最新有效收盤缺失、歷史有效交易日不足、技術缺漏、SMC 缺漏和
當日綜合評分缺漏。沒有經過查核的旗標**不會臆測為成功**。

## 2. 交易成本及流動性壓力測試

`src/research_execution_costs.py` 提供 `scenario` 和
`stress_test`。使用者**必須明確輸入**適用的買賣手續費、
賣出證交稅、雙向滑價的 basis points（bps），避免忽略股票、
ETF、當沖等稅率可能不同；此模組不會擅自套入某個固定台股稅率。
輸入報酬是十進位小數（`0.05` 表示 5%，不是 5）。
指定實際已核對的新台幣下單金額與成交金額，才進行成交參與率
檢查。未提供成交金額的流動性狀態是 `UNKNOWN`，不是 `PASS`。
此壓測不模擬漲跌停不可成交、真實深度、券商最低手續費或實際
成交概率，因此不證明策略可執行。

## 3. 基本面「當時已知」時間序列資料結構

`src/research_fundamental_pit.py` 可保留月營收年增、
滾動 EPS、ROE、營業現金流、負債股東權益比、P/E 等觀察值：

```json
{
  "market": "twse",
  "stock_id": "2330",
  "metric": "revenue_yoy_pct",
  "period_end": "2026-09-30",
  "published_at": "2026-10-10T17:00:00+08:00",
  "recorded_at": "2026-10-10T17:01:00+08:00",
  "value": 20.5,
  "source": "已核對的財報或月營收來源"
}
```

研究訊號必須明確指定台北時間 `13:30` 的收盤截止：
`as_of_close="2026-11-20T13:30:00+08:00"`。
報告只採用**公布與登錄皆早於收盤**的觀察；未來公布的財報或晚來
的修訂不准回填成舊訊號已知資訊。
這是**欄位及 as-of 驗證功能**，不含官方財報下載、財務比例計算、
財報真偽保證或新的訓練權重。來源標記必須另行驗證，不能把
這個工具當成已完成的基本面獲利模型。

## 4. 同樣本評分異常診斷

`src/research_anomaly_monitor.py` 比較兩份離線股票評分快照，
只統計**同一股票**的評分變動。共同樣本不足（預設至少 30 檔）
時回傳 `INSUFFICIENT_MATCHED_COHORT`，避免不同股票池造成
虛假的變動訊號。大幅變動顯示 `SCORE_SHIFT_REVIEW`，
這是**資料或行情檢查提示**，不是模型已失效或可交易的證明。

## 5. 一鍵產生離線研究驗收報告

準備兩份上述已核實的 `before.json`、`after.json`
（既有腳本可儲存已觀察快照），即可執行：

```bash
python scripts/offline_research_readiness.py \
  --before before.json --after after.json \
  --evaluation models/tw-factor-ridge-1-evaluation.json \
  --output-json readiness.json \
  --output-md readiness.md
```

只有已經從**同一受保護快照**核實的
`scored_and_both_current`，才可追加到 `after.json`。
支援 `--cost-inputs` 傳入 `gross_return`、`fee_bps`、
`sell_tax_bps` 等 JSON；`--fundamentals` 傳入基本面陣列並
須同時指定 `--as-of-close`；`--score-before` /
`--score-after` 同時傳入兩份評分快照。
未提供就顯示未知、不冒稱可用。

輸出包含有效覆蓋率與**舊樣本外負面結果仍未通過驗證**的聲明，
不能因回補已到 50% 就自動開啟推薦、LINE 或交易。

## 6. 本地與 GitHub 測試

```bash
PYTHONPATH=src python -m unittest \
  tests.test_offline_research_hardening \
  tests.test_research_dataset_factor_diagnostics \
  tests.test_investment_model_bundle -v
```

新測試僅使用合成資料和 mock，且不含 DB 憑證；若既有 CI
告警或失敗，必須修正後再合併，不得忽略紅燈強行發布。

## 保留的限制與待完成條件

- **新額外付費 NT$0**：不升級 Neon、不啟動收費 API、雲端付費工作或額外訂閱；受服務原免費額度限制。
- 無新 GitHub Actions 排程，避免與正式回補競爭運算資源。
- 使用者雖授權本輪程式維護及合併，**正式補算仍只用原先授權的受控流程**；不因授權語句而開啟未審查的大範圍寫入。
- 已保存的訓練模型真實 holdout 淨超額研究值約 -2.11 個百分點，且不是全新獨立 holdout；不自行宣稱獲利。
- 真正的歷史樣本外績效、完整基本面資料、可靠成交模擬和即時個股研究報告仍依賴**新資料與獨立驗證**，不能靠離線程式自動完成。
