# 免費容量優化與基本面歷史可得性：自動唯讀驗證

2026-11-21 五年行情輸入批次在已確認寫入約 347,598 筆上櫃原始價量後，因三個來源日期失敗（包含 TPEx HTTPS read timeout）受控停止，Neon 實際約 370.4MB；歷史全日因子因此可能過期。原始行情不刪改，另行修復來源失敗，絕不跳過 >=10 筆獨立同日收盤與 98% 比對。

## ① 按需計算，不永久儲存新的衍生列

`scripts/tpex_on_demand_research.py` 使用 `READ ONLY REPEATABLE READ` 連線，只針對 **1 檔上櫃**、最多 1600 個真實歷史 K 線，依同一個截止日期讀取已存在的 `daily_prices` 和已核實 `corporate_actions`，沿用 `normalize_source_units`、`adjust_bars`、`compute_indicators`、`compute_smc` **相同程式路徑**，在記憶體計算而不做任何 `daily_adjusted_prices`、`daily_technicals`、`daily_smc` 資料庫寫入。輸出最多 20 個近期日期供研究檢視，實際正式工作只展示最後 2 日，無預設大表儲存、無新價格寫入、無定期大量因子 UPSERT。

**重要**：公司行動 `ex_date` 不等於當時公司公告首次可得時間；此研究面板只有**經核實公司行動目前調整後**的資料，不宣稱每一歷史日期都具備當時可得的調整係數，因此沒有正式歷史樣本外回測授權。要做因子回測仍需要獨立可驗證的公司行動公告 vintage。

## ② 財報 PIT 時間完整性自動測試

`scripts/official_fundamental_temporal_witness.py` 從 Neon 取官方 EPS、資產負債表與營收實際最早的 `first_observed_at`，從已觀察行情中挑選**早於第一次觀測日**的真實市場交易日，使用臺灣 13:30 收盤時間，**同一已實測的來源可得性 SQL** 對兩個市場驗證：任何在來源觀測前的季報／負債／營收值都不得出現在當時的策略特徵。不接受財報的 fiscal period 或 table date 充當公告時間、不倒填來源觀測時間；未證實的原始公告時間及 ROE／現金流仍不能用於投資回測。

## ③ 免費與自動化設置

`.github/workflows/tpex-five-year-free-research-audits.yml` 由本次首次新增的一次性標記觸發今天正式兩項唯讀驗證，往後也會在**原有每月官方收入/季報來源工作成功完成後自動再次稽核**。不新增每分鐘／每日定期爬蟲、不新增任何 Neon 寫入、不影響現有 LINE、真實交易和成本。若任何來源缺漏或時間門檻錯誤，工作保留失敗證據，不能視為已完成模型驗收。

## 一次性正式執行的連線故障與安全修復

原定的首次唯讀自動工作 [#44912438098](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/runs/44912438098) 的全部 Python 測試已成功，但正式 Neon 在第一個 `SET TRANSACTION ... READ ONLY` 出現 `psycopg.OperationalError: SSL connection has been closed unexpectedly`，因而阻止後續財報時序證據輸出；此情況**不代表**原始行情或因子損毀。重試版本僅為兩項**完全唯讀操作**提供至多 **3 次**（每次 5 秒間隔），仍必須通過完整來源與期限驗證，失敗後保留 workflow failure，不發 LINE、不改交易、不啟動原始行情回補。使用單一全新來源稽核標記 `.github/tpex-free-on-demand-pit-audit-v2-20261121.txt` 重新觸發。
