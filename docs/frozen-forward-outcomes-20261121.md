# AI 前瞻研究第二階段：凍結當日股票池 → 真實 t+1 / t+6 報酬驗收

2026-11-21 首次固定模型 `tw-factor-ridge-1` 已在台灣時間 13:59
封存訊號日 `2026-11-20` 共 **1,139 檔**完整研究股票池、
排名 Top20%=**228 檔**、正式模型與來源內容 SHA256；完整受
PostgreSQL 禁止 UPDATE/DELETE 觸發器保護。該日的
**未來 t+1 至 t+6 交易日尚未發生**，不能在 2026-11-21
生成正／負樣本外模型報酬。

這次新增 `src/research_forward_outcome.py` 與
`scripts/audit_frozen_forward_outcomes.py`，在**一個唯讀、REPEATABLE READ**
Neon 交易中驗證：
- 只讀已真正預先封存的完整 `roster`，
  **不能依事後是否有價格重新篩選股票名單**。
- 依每一檔股票的**真實有效原始行情交易序列**
  找到訊號日後第 **1** 個交易日（示意進場價）
  及第 **6** 個交易日（示意出場價）；不以日曆天、
  稀疏調整價格行數或股票報酬篩選結果決定第幾日。
- 真實調整後進／出場收盤價必須都正值，
  進場／出場日期皆在已知 label cutoff 以內；並再次
  核對 DB `frozen_at` 早於進場日台灣時間 13:30。
- 一律要求**整個凍結研究池**的全部公司都已成熟，且
  真實進場日和真實出場日分別完全一致；
  少一個公司、調整價格缺漏、停牌、進出場不同日，
  都回傳等待／異常原因，不輸出片面平均報酬。
- 所有公司都成熟且持有日期一致時，才根據**已凍結的**
  model_rank、baseline_rank，計算 Top20%
  以及當日全部股票的平均調整報酬；模型與原分數基準
  僅以研究假設的**來回 30bps**成本扣除，並計算相對
  全研究池的淨超額。
- 即使完整標籤已成熟，這也只是一個
  `FULL_COHORT_MATURE_RESEARCH_ONLY` 研究觀察窗。
  公司行動調整價的當時歷史版本未獨立驗證、存活偏差
  也尚未稽核；單窗報酬不代表 AI 具有投資 alpha，
  不會觸發 LINE 或券商下單。
- SQL 每次只查**指定一個已凍結訊號日**，
  每檔僅取截止日之前最多六個真實行情交易日，
  30 秒查詢逾時。沒有額外每週排程、
  沒有價位、持股名單或預測值的外送。
- 報告只保留日期、封存模型與完整股票池 hash、
  總股票／已成熟數、真實進出場日期是否一致、
  完整時才有研究用報酬；沒有資料庫寫入權限。

## 正式第一次實際可驗收狀態

目前 2026-11-20 的完整股票池已經封存：
`model_version=tw-factor-ridge-1`、
`universe_count=1139`、
`selected_count=228`。

用本日 2026-11-20 已知最後交易日執行真正 Neon
唯讀聚合：`actual_members=1139`、
`seen_entries=0`、`seen_exits=0`、
`matured=0`。
這是**正確的`AWAIT_ENTRY`狀態**：
2026-11-21 是星期六，不能聲稱已經獲得 11/23
以後才可能出現的交易結果。

之後運行：

```bash
DATABASE_URL='<existing-protected-Neon-url>' PYTHONPATH=src \
python scripts/audit_frozen_forward_outcomes.py \
  --signal-date 2026-11-20 --out frozen-research-forward-outcome.json
```

不填 `--signal-date` 會讀**最新實際凍結日**。
`--cutoff` 可指定較早已知交易截止日以複查，
絕不可超過當前資料庫最新真實有效行情日或今天。

## 測試

- Python unit tests：0 已知未來日期不可有績效、
  50 檔全部成熟前不得只看 49 檔結果、
  真正不同進出場日期禁止比較、
  50 檔相同日完整時 30bps 成本正確扣除、
  已凍結股票池與選股數不得遭竄改。
- PostgreSQL 17 隔離測試：真的建立 50 檔 × 6 日
  **僅測試用**的下一交易日價，驗證資料尚未到期、
  完全到期、部分調整價格缺漏，以及停牌造成
  持有日期不同時均拒絕宣稱策略績效；
  測試 schema 完成後 rollback，**完全不寫入 Neon 假價**。

真正的長期模型研究需事前定義策略與基準、
等待至少 10 個互不重疊的成熟觀察窗並涵蓋足夠日期、
獨立核對來源與流動性，在此之前
`src/model_release_acceptance.py` 的判定仍為
`BLOCKED`，`live_trading_approved=false`。
