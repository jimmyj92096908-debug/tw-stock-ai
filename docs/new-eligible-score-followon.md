# 上櫃新增合格股票：小批量最新評分回補（不掃完整市場）

2026-11-21，`eligible-100` 一次性回補成功後，當時原有的
1,107 檔至少 60 個有效交易日、近期有真實行情、非研究排除
`1808` 的股票已完成最新技術／SMC／可發表綜合評分。

後續 TPEx 官方歷史行情兩檔 canary 成功：`3523` 有 90 日、
`3632` 有 82 日有效收盤資料，因此**合格分母動態擴至 1,109 檔**，
但這兩檔尚未補指標與評分，不能把原先的 100% 當作現在 100%。

`src/composite_score.py` 維持現有 `calculate_all(url)` 呼叫方式
和原本完整模型計算公式**不變**，新增明確限定股票的
`calculate_all(url,stocks=[(market,stock_id),...],missing_only=True)`：

- 對最多 10 檔經核實的股票**只新增缺漏的**
  `daily_composite_scores` 主鍵（`ON CONFLICT ... DO NOTHING`），
  既有評分保持原值，不因補兩檔就重新寫入其他約千檔歷史評分。
- 對明確指定的最新有效價格日計算，保留技術、SMC、
  籌碼可用性與評分信任度規則。
- `scripts/new_eligible_score_followon.py` 從現有至少 60 日
  有效交易、日期近期、缺當日指標或綜合評分的股票選
  最多 2 檔；需要時只對這些股票重算調整行情、技術、SMC。
  必須通過同股同日價格、技術、SMC、綜合評分再回報成功。
- 不寫入 `daily_prices`、不啟動交易或 LINE；原始行情
  總筆數或全市場最新有效價格日在執行前後發生變化時停止驗收。
- 與先前 50%／100% 合格池和每天 03:10 指標補算
  使用同一 `twstock-indicator-catchup` 排他鎖。
  `new-eligible-score-once.yml` 的專用標記檔只建立一次，
  平常沒有新增一條每天重跑的 CI 排程。

## 零額外付費及限制

所有運算沿用既有開源 Python、GitHub CI 與受控 Neon。
設定在資料庫接近 800 MB 前停止；不啟用付費方案。
加入新股票只代表**有資料可研究**，不代表模型已通過
全新不重疊樣本回測或可自動買賣。

全市場仍有大量上櫃歷史不足 60 日的股票以及 9 檔完全沒有
有效價格；正式官方歷史取得可用性、停牌及上市日需逐檔核對，
不能對這些股票合成日期以提升表面覆蓋率。

## 測試
```bash
PYTHONPATH=src python -m unittest \
  tests.test_new_eligible_score_followon \
  tests.test_composite_score \
  tests.test_score_after_refresh -v
```
