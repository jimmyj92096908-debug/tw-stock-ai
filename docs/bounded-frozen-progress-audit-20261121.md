# 前瞻 AI 研究：多日已封存訊號、實際成熟結果與獨立時間窗稽核

現在 `tw-factor-ridge-1` 固定權重模型已於 2026-11-21 首次真正封存 2026-11-20 的全研究池 1,139 檔，並已由 `src/research_forward_outcome.py` 提供 t+1 進場、t+6 出場的真實官方行情研究驗收。但舊腳本預設只查**最新一個**封存日；若之後每日新增，最新日期幾乎永遠未成熟，無法看見舊封存日逐步完成的結果。

本階段新增 `scripts/audit_recent_frozen_cohorts.py`，在**單一 PostgreSQL `REPEATABLE READ READ ONLY` 一致性快照**下：
- 只查指定模型、實際最新有效交易日以前的**最多 12 個**真正保存於 `research_forward_frozen_cohorts` 的日期。不存在的未來日期、非允許模型及不存在的股票池不得推造。
- 每一天都**直接重用已驗證的完整研究股票池 t+1／t+6 判斷**，包括所有原本的 50–2,500 檔真實固定成分、公司行動調整價、同日可比及真實封存時戳檢查。
- 輸出 `AWAIT_ENTRY`、`AWAIT_SIX_TRADING_SESSIONS`、`INCOMPLETE_OFFICIAL_ADJUSTED_LABELS`、`UNALIGNED_ACTUAL_ENTRY_EXIT_DATES` 與 `FULL_COHORT_MATURE_RESEARCH_ONLY` 的各日數量。
- 若部分成分缺行情，**絕不**只保留有資料或獲利股票去計算部分平均報酬；目前只等待，等未來真實交易日自然成熟。
- 對已完整成熟且持有日期一致的研究日，採用**最早出場優先 interval scheduling**，只有下一研究窗真正進場日 **嚴格晚於**上一研究窗出場日，才算另一個獨立期間。這可避免以數個重疊 t+6 研究結果，錯誤堆成多個獨立樣本。
- 未達 **10 個無重疊成熟研究窗**，不顯示平均研究淨超額；即使達標，也只標示**探索性**平均，絕不改變目前 Ridge 已驗證失敗的 `BLOCKED` 模型上線狀態。公司行動當時版本、存活偏差、流動性、實際交易成本、全新獨立樣本驗證尚未完成。
- 保留每個封存日的 model SHA256／roster SHA256 以確認**沒有混用不同模型係數**，報告僅含研究日期、摘要與計數，沒有個股建議、LINE 或交易。
- 實際資料庫連線強制 readonly、每個 SQL 25 秒 timeout、最多 12 個已封存日期，Neon Free 無任何新增資料庫表或寫入成本。
- 在原有 `.github/workflows/composite-after-market-refresh.yml` 的 **星期一**官方日行情成功後，同一個既有 GitHub Action 啟動此唯讀進度稽核，並保留 14 日彙總 artifact；沒有新增任何每日 cron 或額外付費服務。其他交易日仍依既有來源／評分／事前封存流程運作。

## 執行與測試

```bash
python -m unittest tests.test_frozen_cohort_progress tests.test_frozen_cohort_progress_postgres -v
DATABASE_URL='<existing-protected-Neon-url>' python scripts/audit_recent_frozen_cohorts.py --limit 6 --out prospective-frozen-progress-evidence.json
```

- Python 純單元測試會拒絕重複／未來訊號日、不同 model SHA、缺少完整成熟結果卻出現報酬、被手動開啟的實際交易／LINE 權限；另外證明 3 個重疊完整期間只能算成 2 個獨立窗口，即便 10 個互不重疊窗口都在，也不能自行開啟交易。
- 隔離 PostgreSQL17 測試真正建立臨時封存日資料表，驗證選擇日期有 SQL `LIMIT`、依真實市場日截止、只查核固定模型；全部事務 rollback，不寫入 Neon 假資料。
- 正式 Neon 本日最後有效市場收盤日仍為 **2026-11-20**，資料庫目前只有首個 **2026-11-20** 實際封存股票池；其真實 t+1／t+6 尚未發生。初次驗收應正確回傳 `AWAIT_ENTRY`，不是假造的獲利。

**此工程完成的是研究驗證的持續可追溯性，不代表 1,991 檔歷史行情全部齊全、可取得真實歷史現金流或 AI 能穩定獲利。**
