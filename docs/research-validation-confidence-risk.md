# 離線樣本外驗證、資料可信度與風險分析（研究用途）

2026-11-21：本功能**不會**連接正式 Neon、寫入資料庫、送 LINE、修改既有補算排程或開啟交易。

## 目前事實與目標

已保存的 `tw-factor-ridge-1` 有 57 個開發日期、21 個曾經檢視的驗證日期；
後者平均淨超額報酬約 -2.11 個百分點（保存的研究指標，不是實際帳戶績效）。
先前驗證資料並非全新未碰觸的 holdout。這次開發的 walk-forward
**不能讓舊驗證變成全新未碰觸的樣本**，所有輸出一律標示
`pristine_future_holdout_proven=false`、`orders_enabled=false`。

## 實作功能

1. `src/research_walkforward.py`：對使用者提供、已驗證的歷史資料滾動重訓。
   每個折的訓練資料必須在第一個測試訊號日前**連同未來報酬標籤一起成熟**；
   跨折及折內的測試持有期間不能重疊。報告固定的 30 bps 假設往返成本、
   同一有效樣本內的等權股票母體、原始固定評分策略，並可使用**外部提供且
   期間相同**的指數基準報酬。樣本母體等權收益**不是**加權指數收益。
2. `src/research_confidence.py`：把評分日、技術日、SMC 日與最新有效收盤日
   核對；必須具備至少 60 日有效行情及可信的最新綜合評分因子涵蓋率。
   輸出資料品質指數 `data_quality_index`，**不是上漲機率、勝率或交易信心**。
   缺少關鍵日期/歷史/因子涵蓋，分數直接 `null`。
   獨立籌碼來源**不可往回補上舊綜合評分**。
3. `src/research_risk.py`：不重疊持有期的假設研究報酬路徑，包括複利
   報酬、最大回撤、單次觀察波動及最差收益；有經核對的持股比例，才會
   另外計算持股集中度。市場環境分類需自行提供經核對的官方市場指數收盤
   序列，使用截至當時已出現的資料，判斷趨勢/盤整；不以個股充當指數。
4. `scripts/offline_research_diagnostics.py`：單一指令執行以上離線研究，
   沒有 SQL、憑證、下單或 LINE 路徑。使用 `--index-prices` 時須同時提供
   `--as-of-date`，未提供指數不生成虛構的市場環境。
5. `src/investment_model_bundle.py`：既有統一研究報告增加 `data_quality`
   內容，所有欄位由已存在的**唯讀** PostgreSQL 查詢取得；修正技術指標
   最新日期判定，避免把 NULL 股價尾日當成有效交易日。

## 離線使用（不執行正式 Neon 查詢）

歷史資料需是經過查證的 JSON 陣列，每筆包含：
`market`, `stock_id`, `as_of_date`, `total_score`,
`technical_score`, `smc_score`, `short_term_score`, `swing_score`,
`long_term_score`, `coverage_weight`, `adjusted_close`,
`entry_close`, `exit_close`, `exit_date`。
信號使用交易日當日已知因子；未來調整收盤資料只作**歷史標籤**。
使用者自行提供這份核實的 JSON；目前 repo 中的彙總評估 JSON
**不包含每日期、每檔完整標籤，不能假裝可以直接重跑回測**。

```bash
python scripts/offline_research_diagnostics.py \
  --rows verified-research-rows.json \
  --first-test-date 2026-10-01 \
  --fold-signals 3 \
  --max-folds 12 \
  --output walk-forward-research.json
```

可選 `--benchmark verified-index-horizon-returns.json`，
格式是 `{"YYYY-MM-DD": 0.01}`；每個鍵值是**對應研究持有期間**
的已驗證基準淨報酬，不是任意一日指數漲跌幅。缺少任一訊號日期即標示
基準不完整，不宣稱勝過大盤。

可選 `--index-prices official-index-closes.json --as-of-date YYYY-MM-DD`，
其中每筆為 `{"date":"YYYY-MM-DD","close":12345.67}` 且按日期升冪。
如果不是官方或可核實的指數資料，不能作真實市場分類解讀。

可選 `--holdings normalized-holdings.json`，包含
`{"market":"twse","stock_id":"2330","weight":0.4}` 等，權重總和
必須為 1。未知持倉不推測。

## 驗證與防護

```bash
PYTHONPATH=src python -m unittest \
  tests.test_research_validation_confidence_risk \
  tests.test_investment_model_bundle \
  tests.test_trained_factor_model -v
```

現有 GitHub Python Tests 也會載入離線測試。這個改動不更動現有
50% Neon 資料回補流程，且不會自動重訓正式模型。已保存的原本
-2.11% 研究結果仍然屬於未通過驗收的結果；不應改寫為正報酬。
