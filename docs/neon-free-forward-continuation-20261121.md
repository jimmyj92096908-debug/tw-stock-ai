# 免費額度與前瞻研究預測自動封存：第二階段

## Neon Free 容量／傳輸不能混為一談

2026-11-21 Neon API 正式 project `royal-scene-68859981` 已有使用量欄位 `data_transfer_bytes` 與 `compute_time_seconds`；Postgres 的 `pg_database_size` 只是已儲存表與索引，不是網路流量，也不可直接換算 CU 小時。專案頁顯示每項目每月 5 GB Network transfer。新增 `scripts/neon_free_meter_guard.py` 將三種證據明確分開：

- 真實 PostgreSQL 庫存超過 650MB：發出警告，禁止新增前瞻保存寫入；800MB 是既有原始行情的獨立硬停止線。
- 真正 Neon project API 所報網路流量 3.5GB 警告、4.5GB 停止新非必要高網路工作（以 5.0GB 為此專案安全規劃假設，非宣稱無限額度）。
- **GitHub 未配置 `NEON_API_KEY` 時，網路狀態必須報 `UNAVAILABLE`，不會印出 key、也不會冒稱零流量或綠燈。** `--require-network` 在沒有可驗證 API 用量時即拒絕新的大量回補；已存在的長批次仍使用自己先前的強制 800MB 容量及官方來源控制。
- GitHub 的 `NEON_API_KEY` 是額外的非必要讀取用 secret，不會將 API key 寫入源碼、報告或日誌。未配置時，仍可執行庫存容量監測及最多 1.8MB 的單次*封存新交易日*研究快照；此時不能宣稱網路安全，只能說額外大批次不能因未知用量而獲批准。

## 真正未來市場的模型研究封存

現有 `research_forward_frozen_cohorts` 已有 2026-11-20、1139 檔真實群組，交易市場正式源的最新調整、模型已訓練完成日、風險及來源當日真實截止時間都在 `scripts/freeze_prospective_research.py` 裡嚴格檢查。其資料庫觸發器對既有快照 `UPDATE/DELETE` 立即拒絕，`ON CONFLICT DO NOTHING` 且檢核原始 SHA 不許覆寫。

新的 `.github/workflows/prospective-free-safe-daily.yml` 不新增一個新的高頻排程，只在**已啟用的官方每日市場快照排程成功結束**後觸發，使用已存在的 `composite-score-after-market-refresh` 互斥群組，封存一個**在下一交易日前**、有真實來源當日收盤的完整研究群組。若當日未更新、模型或日期有問題、重試來不及、超過 650MB，仍 fail closed；不能補造、回填或覆寫前一天模型預測。手動執行預設 `apply=false`，只預覽不寫入。若來源封存不新鮮或現在為非交易日，工作可能拒絕封存，**這是正確的錯誤證據，不是完成新未來樣本**。

`scripts/prospective_forward_maturity_readonly.py` 使用真正較早、至少十個日曆日前已封存的群組，且僅在有真實後續價格資料時，接上現有 `audit_frozen_forward_outcomes.py`，只核對當時整批 1139 檔或後續實際封存的股票，不允許只選贏家；標籤未成熟則保留 `NO_OLDER_PRECOMMITTED_COHORT_AVAILABLE` 等待，不可用訓練回測推定通過。沒有全面股息與歷史公司行動公告版本，也不宣稱研究模型淨超額有效。

## 邊界

這個工作不是股票預測成績提升保證，不會改寫原始股價、不會重新訓練現有正式 Ridge、沒有 LINE 交易訊號或真實下單，也沒有 Neon 付費升級。歷史市場母體與股息資料仍需獨立證據。
