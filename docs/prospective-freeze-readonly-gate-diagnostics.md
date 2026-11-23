# 2026-11-24 前瞻研究封存：免費容量與評分日期的唯讀預檢

## 三個真正觀測到的工作流程狀況

截至 2026-11-24，主分支 937f5de 的 GitHub Actions 紀錄：

| 工作流程 | Run | 實際錯誤／根因 | 本 PR 的界線 |
| --- | --- | --- | --- |
| Composite Scores After Verified Official Snapshot | 45210088106 | 綜合評分階段後，執行 freeze_prospective_research.py 讀取 LATEST_MODEL_SQL 超過 30 秒的 statement_timeout | 先做唯讀、低成本 HEAD 預檢；任何容量／網路額度或日曆不同步即安全跳過高成本封存，不把逾時改成高配額 |
| Safe Prospective Research Precommit and Free Budget Proof | 45210088014 | build_frozen_universe 拒絕「global latest true market close and score day differ」 | 保留這個嚴格拒絕；預檢明示 ABSTAIN_MARKET_SCORE_DAY_MISMATCH，不拿舊的評分日期當新日期 |
| Official Current Issuer and Whole-Market Dividend Evidence | 45194080486 | 原本 650,000,000 bytes 保守限額擋下資料來源存證工作 | 此限額是正常免費安全保護，本 PR **不擅自提高**、不重試 DML，也不宣稱該流程修好 |

2026-11-24 另有對正式 Neon 的**唯讀 SQL**尺寸確認：pg_database_size(current_database()) = 753,147,904 bytes，超過 650,000,000 bytes 保守警戒，未超過程式設定的 800,000,000 bytes 嚴格停止線。但 DB 大小不是 Neon API 的當期實際計費，不能以它代替網路傳輸與 CU 額度；當時 GitHub 工作流程中 NEON_API_KEY 為空，未獲 Neon API 認證的網路用量也**不能假設是安全**。來源行情日期與綜合評分最大日期在這次 READ ONLY 查詢都為 2026-11-23；之前不同日的 CI 失敗可能與兩個流程同時觸發有關，這是可能原因，不是已獨立證明的唯一原因。

## 安全修正：免費額度與日期 gate

新增 scripts/prospective_freeze_preflight_readonly.py，特性：

1. 只透過 server-enforced default_transaction_read_only=on，REPEATABLE READ READ ONLY，SET LOCAL statement_timeout 8000ms 使用單次短 SQL 讀取 pg_database_size。**不執行大型 LATEST_MODEL_SQL**。
2. 如資料庫大小已達 650,000,000 bytes，直接輸出 ABSTAIN_STORAGE_WARN，不再查完整分數 cohort、不額外呼叫 Neon 付費或 API，不進行研究封存。
3. 僅在容量低於警戒時，才讀取 HEAD_SQL 的最新有效行情日期、最新有分數日期與資料庫時鐘；日期不等明確記錄 ABSTAIN_MARKET_SCORE_DAY_MISMATCH。仍使用原 eligible_freeze_time 的前瞻時間截止條件，不回補前次逾期 cohort。
4. 額外要求 Neon API 計畫身分相符且當期實際網路用量可驗證，不能在 NEON_API_KEY 遺失、錯誤或高於保守傳輸警戒時允許封存。預檢永遠不批准 LINE、下單、付費升級、模型 release。
5. 任一 Neon 連線錯誤、查詢逾時、格式錯誤、API 例外都只回報不帶私人資料的 ABSTAIN_READONLY_PREFLIGHT_UNAVAILABLE；絕不在 log 印帳密、URL 或任何股價。
6. 保留原來正式封存程式內的交易一致性、日期、全股票名單與 once-per-date append-only 驗證；預檢 true 並**不等於**原封存直接成功，也不是允許越權寫入。所有被擋的條件都有安全、僅含整體狀態的 JSON。

工作流程變動僅限於原有兩個研究封存位置：

- composite-after-market-refresh.yml：**保留原有綜合評分計算不動**，在排程封存前先讀取低成本 preflight。只有 safe_to_freeze=true 才執行原有的封存寫入。跳過時保留新預檢 JSON artifact，不會創建或更新 cohort；綜合評分是否最新仍另需審核。
- prospective-free-safe-daily.yml：預檢在原本 Neon budget check 之後，同時作為高成本 full-roster read-only preview 與新 cohort 寫入的前置條件。不要把 ABSTAIN 說成完成。

**重點：** GitHub CI 結果顯示 success 若只是安全預檢輸出 ABSTAIN，那只代表「安全停止機制成功」，不表示前瞻研究樣本已凍結、不表示當天資料完整。原有「日期相同」與「原始資料時間確實早於下個交易日」的檢查不能取消。

## 當前實際阻礙與下一步

目前 753 MB 的資料庫大小**已超過 650 MB**。因此這個修正會故意暫停新的 prospective freeze；完整大 SQL 的原始逾時未宣稱根因已完全修復，將在經過可驗證的安全額度確認、縮減資料庫安全方案或純離線模擬後，再做不擴增費用／不新增索引的 SQL 效能優化。

原始 MOPS 公告及全部公司行動、五年來源覆蓋、歷史股票母體 PIT、除權息配股／總報酬及嚴格 holdout alpha 仍未通過。11 月台泥候選配股比率 0.099928258 股每舊股**只有回溯研究算式 PASS**，不能拿來算正式前瞻報酬。

本次無資料庫 DML/DDL、無額外付費、無 LINE 變更或訊息、無交易、下市股票及 1589 不納入目前研究母體。project issue #176 保持 OPEN；model_release=BLOCKED。
