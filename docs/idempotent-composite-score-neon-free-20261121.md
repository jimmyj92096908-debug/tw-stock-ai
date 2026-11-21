# 下一階段：綜合評分重算具備「無變化不寫入」能力

2026-11-21 Neon Free 正式資料庫：`stock_master=1991`，`1982` 檔有正收盤價，`1122` 檔至少 60 日，`1120` 檔符合現行近期研究條件且**同股、同最後有效行情日**有技術、SMC 與有效評分（合格池 100%，全清單約 56.3%）。資料庫約 229 MB。

原本 `src/composite_score.py` 每逢成功的正式日行情與技術補算後，會重算已有技術資料的股票並執行 `ON CONFLICT ... DO UPDATE`，即使每一個分數、覆蓋權重與來源狀態內容相同，仍會產生新的 PostgreSQL 資料列版本和 WAL 寫入。

新程式**維持同一套技術、SMC、籌碼及三週期模型公式**，只是使更新操作具備資料內容相等的判斷：

```sql
ON CONFLICT (market,stock_id,as_of_date)
DO UPDATE SET
  -- 原本 12 個研究欄位與 calculated_at 的更新賦值不變
WHERE (
  daily_composite_scores.total_score,
  ...,
  daily_composite_scores.component_status
) IS DISTINCT FROM (
  EXCLUDED.total_score,
  ...,
  EXCLUDED.component_status
)
```

以 PostgreSQL `IS DISTINCT FROM` 的**包含 NULL 的比較**，逐一核對 `total_score`、`coverage_weight`、技術／SMC／籌碼子分數、短／中／長週期分數及覆蓋率、`component_status` JSONB。

- **資料未改變**：保留舊 `calculated_at`，不執行 `UPDATE`，不產生無意義的新資料列版本。
- **新股票或新日期**：照原本主鍵新增合法有效評分。
- **最新籌碼數據或來源覆蓋權重變更**：即使最新股價日相同，仍能比較並更新受影響的綜合評分，`calculated_at` 會改變。
- **來源 metadata／缺漏狀態有變**：JSONB 不相等就更新，不能只比較總分而忽略可信度。
- **missing_only=True**：原先限定最多 10 檔的 `ON CONFLICT DO NOTHING` 保護完全維持，舊分數仍不可覆寫。
- **原研究 AI 模型不重新訓練或啟用交易**。先前樣本外研究負超額結果與歷史成熟標籤不足的限制均未改變。

## 回歸驗證

`tests/test_composite_score_idempotent.py` 具備一般純測試，以及只使用
`STOCK_CI_POSTGRES_URL=postgresql://stock_ci_test:...@127.0.0.1:5432/stock_ci_test`
的**隔離 PostgreSQL 17** 整合測試。整合測試建立臨時評分表，逐一確認：

1. 第一次插入實際新增 1 筆；
2. 完全相同的再計分 `rowcount=0`，原 `calculated_at` 與 `ctid` 不變；
3. 新籌碼分數／覆蓋權重改變後確實更新；
4. 僅來源 JSONB 狀態改變也確實更新；
5. 限定股票只新增評分仍不能覆寫既有主鍵。

此整合測試已列入既有 `Stock Database Diagnostics (Isolated CI)`，而且**必須先通過完整 Python CI 與實際 PostgreSQL CI 才能合併**。不新增付費資源、外部來源呼叫或資料表欄位，也不在正式 Neon 執行用來測試的寫入。

注意：這只減少「更新值完全相同」的 PostgreSQL 寫入，**不保證所有每日評分計算 SQL 查詢數或執行時間都降低**。實際節省的磁碟/WAL/運算量必須在後續真實排程的執行紀錄評估，不能假造百分比。
