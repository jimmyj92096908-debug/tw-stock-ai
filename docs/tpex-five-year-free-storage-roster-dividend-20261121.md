# 五年上櫃研究模型：免費儲存壓力、歷史股票母體、除權息標籤三項驗收

日期：2026/11/21。這三項均為 **Neon PostgreSQL `default_transaction_read_only=on` + `REPEATABLE READ READ ONLY`**，只寫本次 GitHub Artifact 報告，不新增或更動原始價格、歷史因子、公司行動、LINE 或交易紀錄。

## 1｜免費 Neon 容量壓力

`scripts/tpex_free_storage_stress.py` 以資料庫真實 `pg_database_size` 和每日價格、調整價、技術、SMC 四表的 `COUNT(*)`、含索引的 `pg_total_relation_size` 估計實體新增列成本。新增源資料每列使用 **1.5 倍現有物理／索引成本**作情境，分別對餘下已獨立錨定日期假設**每日 700、850、900** 檔新行情（僅為壓力情境，不是實際掛牌名單）。先估原始行情，再估後續所有三類逐日衍生資料加上目前已存在的衍生筆數淨缺額**下限**。內部容量停止線 800 MB、另外保留 50 MB 維護餘裕；低於此餘裕回報 `CRITICAL` 並拒絕衍生資料批次。估算非實際磁碟上限保證、也不能修改正式行情報表的硬停止線。

此模型不把 `COUNT(*)` 淨缺額誤認為精確逐檔主鍵缺漏；其它股票多出的衍生列可能抵銷不同股票的實際缺漏，因此僅是**缺漏下限**。只有安全線內的原始來源行情報價可持續按現有批次守則增長；全五年永久衍生列可能超出安全容量，應使用已開發的按需計算。

## 2｜歷史 IPO、下市、停復牌母體

`scripts/tpex_historical_roster_audit.py` 唯讀核對當前 `stock_master` 898 檔與 `daily_prices` 實際至少一根正收盤、非負成交量的上櫃價格檔，列出沒有今日主檔的來源股票樣本，以及「第一筆現存原始行情出現在最近三年」的**待查檔數**。

**絕不**將第一根儲存 K 線視為真實首次上市日。今天 `stock_master` 目前僅有 `market/stock_id/stock_name/industry/updated_at`，沒有原始官方 `listing_effective_date`、`delisting_effective_date`。因此即使今天主檔全部有行情、且沒有任何非主檔交易列，也**不能證明** 2021–2025 年不曾有下市股票。只有之後取得官方歷史掛牌、變更市場、下市有效日期、停復牌及當時可投資名單證據，才有可能解除 `historical_survivorship_free_investible_roster_approved=false`。

## 3｜除權、除息與報酬標籤

`scripts/audit_total_return_label_provenance.py` 唯讀檢查 `corporate_actions` 每筆價量係數合法、原始 `created_at`、已核實／未核實、同日經濟事件重複來源列、明確現金股利額、每市場真實有公司行動的股票數。針對同一公司行動不同 `source_event_id` 的重複來源行，採相同經濟事件因子分組；必要時遵循現有 `adjust_bars` 的去重邏輯，不得把同一股利重複調整。原始行情進／出場日期跨過已核實除權息，必須標示其價格比例偏差風險，但**未記錄事件不等於公司沒發放股利**。

現有企業行動匯入 `TARGETS` 僅四檔（上市 6213、4919、7827；上櫃 8937）；Neon 資料目前 24 事件列、上櫃 2 個事件，`cash_amount` 明確股利欄位均未補齊。 `price_factor` 是參考價比例，**不是**經核實的現金股利總報酬；`created_at` 僅是入庫時點，不能冒充原始發行公司公告時間。因此原始價進出場的 `raw_unadjusted_gross_return` 不能直接當成「含息總報酬」標籤。

所有三項稽核可完成**檢查、報告、拒絕錯誤宣告**，不代表原始官方五年 IPO 清單或股息歷史已補齊。資料不足必須明確列為 `false`；AI 模型尚不能因本次檢查完成而宣告可靠超額報酬。

## 自動化

獨立一次性標記 `.github/tpex-free-safety-evidence-20261121.txt` 併入 main 後自動跑第一次 GitHub 正式只讀查核；以後現有五年全市場歷史行情批次完成（不論成功或安全失敗）都會重新執行相同稽核。也能人工執行 read-only。新工作**沒有 schedule cron，也沒有資料庫寫入旗標**，不干擾現有全市場行情報價寫入的 GitHub 互斥鎖，使用既有免費依賴、Artifacts 保留 14 日。
