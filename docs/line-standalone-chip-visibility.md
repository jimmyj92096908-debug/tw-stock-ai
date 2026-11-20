# LINE 獨立籌碼評分（日期分離、預設關閉）

## 動機及已查證事實（2026-11-21）

- 2330 已有可用籌碼原始資料與 `daily_chip_scores` **2026-11-20** 籌碼分數 **40.65**、來源覆蓋率 **65%**（法人 29.05、融資 59.21）。
- `daily_technicals` 最新有效日期仍為 2026-11-19，`daily_composite_scores` 最近 2330 綜合分數亦為 **2026-11-19**，籌碼因子當時未納入；既有模型的日期限制 `daily_chip_scores.as_of_date <= technical_trade_date` 必須保留。
- `line_stock_reader` 目前有 `daily_composite_scores` SELECT，但 **沒有** `public.daily_chip_scores` SELECT 權限。不能把程式碼完工視為資料庫權限已調整或 LINE 新資料已上線。

## 本 PR 程式改動

- 新增獨立且僅 SELECT 的 `STANDALONE_CHIP_SQL`，精確約束市場、股票、資料日不得晚於收盤日，並沿用候選閘道的 SQL 完整字串 allowlist。
- 依股票代碼查詢後，在**明確啟用**情況下才額外讀取最新籌碼評分，並在 LINE 格式化時顯示「獨立籌碼評分｜資料日」「來源覆蓋率」「法人／融資」。若籌碼日期晚於綜合評分日期，標示**尚未納入舊綜合評分**，避免誤報。
- 資料不足或查詢權限不足時，原有股票分析仍照常回覆，不洩漏資料庫錯誤訊息。未啟用時仍只執行原有股票 SQL。
- 只新增候選版環境開關 `LINE_CHIP_SCORE_DETAILS_ENABLED`，預設 **false**。本 PR 不修改 Neon Functions 的環境變數，不部署新版閘道，不更換官方 Webhook。

## 啟用前必要條件（**均尚未獲得使用者授權執行**）

1. 取得對專用讀取角色 `line_stock_reader` 的最小、明確權限核准後，才可授予該查詢所需的欄位讀取權限（`market`、`stock_id`、`as_of_date`、`total_score`、`coverage_weight`、`institutional_score`、`margin_score`）。不得授予原始 LINE 訊息、帳號資料或整張資料庫讀取權限。
2. 確認候選 `line-stock-analysis` 使用獨立 `line_stock_reader` 資料庫角色，以唯讀 SQL 驗證可查最新籌碼分數且查不到個人訊息。
3. 另外明確核准部署候選版及切換 LINE 入口時，才可設定 `LINE_CHIP_SCORE_DETAILS_ENABLED=true`，需完成 LINE 實測、去重、普通訊息轉送及回復機制。
4. `daily_composite_scores` 的正式重算是不同的資料庫寫入動作，**不在此 PR 範圍**。

本文件是進入正式驗收前的程式準備規格，不是正式切換或擴權授權。


## 新增：權限前置檢查與隔離 PostgreSQL 整合測試（2026-11-21）

這一階段只增加可檢驗的程式，不更動任何 Neon 授權。

1. `scripts/line_chip_readiness.py` 以 **伺服器強制唯讀交易**（`default_transaction_read_only=on`）檢查 `twstock` 角色和欄位授權、私人 `line_messages` 是否意外可讀，以及 2330 行情／技術指標／綜合分數／獨立籌碼分數的各自日期。只輸出固定股票 `twse/2330` 的公開研究評分與權限布林值；不查詢個人 LINE 訊息、憑證或 Token。
2. `tests/test_line_chip_readiness.py` 驗證未授權時不誤報可上線、私訊任何讀取權限都會阻擋、未來資料日不能被當成舊收盤日資料，以及程式只使用唯讀資料庫連線。
3. `line-stock-analysis/tests/zzzzz-chip-postgres.integration.test.mjs` 使用 GitHub Actions 內建一次性 PostgreSQL 17 容器，對臨時角色**僅授權七個籌碼資料欄位**，實際執行新版 SQL，驗證 2330 的 40.65／65%、日期限制、股票代碼綁定；`SELECT *`、未授權欄位、私人訊息及 INSERT 都必須回傳 SQLSTATE `42501`。
4. 上述測試執行於開發分支，與正式 Neon 分離；整合測試的所有股票值與私人訊息字串均為合成測試資料。

現況的真實 Neon 唯讀查核：`line_stock_reader` 尚沒有七個必需的 `daily_chip_scores` SELECT 欄位權限；以該角色對真實籌碼資料執行唯讀 `EXPLAIN` 得到 `SQLSTATE 42501 permission denied`；但對 `public.line_messages` **沒有任何欄位的 SELECT 權限**。因此目前應維持 **blocked_or_inconclusive**，不能宣稱新功能已可正式啟用。

以下 SQL 僅供未來安全審核；**沒有執行且尚未取得授權**：

```sql
-- 僅在另獲核准、核對功能和角色範圍後，才可能執行。
GRANT SELECT (
  market, stock_id, as_of_date, total_score, coverage_weight,
  institutional_score, margin_score
) ON TABLE public.daily_chip_scores TO line_stock_reader;
```

上述授權不會隱含 `line_messages` 讀取權限，但仍屬正式資料庫權限變更，必須先取得使用者明確同意。且即使未來唯讀權限通過，`LINE_CHIP_SCORE_DETAILS_ENABLED` 仍須另行受控啟用，整個正式 Webhook 切換與一般訊息轉送亦須獨立核准與實測。

### 如何執行唯讀檢查（不執行 GRANT）

```powershell
# 已設定合法的唯讀／管理診斷連線環境變數 DATABASE_URL 後
python scripts/line_chip_readiness.py
```

只輸出 JSON 統計與狀態旗標，不輸出連線資訊或 LINE 使用者資料。


## 2026-11-21：有效籌碼優先、7 日時效檢查，以及真實 Neon 回覆預覽

本輪仍不授予正式資料庫權限、不部署候選閘道、不調整 LINE Webhook、不發送額外訊息。

- `STANDALONE_CHIP_SQL` 新增 `total_score IS NOT NULL` 且 `coverage_weight >= 0.50`；只從股價交易日（含）以前選擇最近一筆**達公布門檻**的獨立籌碼評分。最新紀錄若為 NULL 或覆蓋率不足，不能遮蔽仍具有效條件的前一筆。
- 在回覆端再檢查時效：獨立籌碼評分距離收盤交易日超過 **7 個日曆天**，只提示「資料已過期」，不展示為當期有效分數。距離恰好 7 日仍可呈現，未更改資料庫內評分或因子權重。若沒有可公布的來源仍維持空值／不顯示。
- 新增離線日期邊界、NULL／未達覆蓋率的 SQL 篩選、實際 PostgreSQL 排序及跨股票代碼隔離測試。兼顧權限不足時的安全退回。
- 新增 `line-stock-analysis/readonly-live-preview.mjs`：只有設定 `LINE_STOCK_READONLY_PREVIEW=yes` 才可使用，連線只指向 `twstock`，並以 PostgreSQL `BEGIN TRANSACTION READ ONLY` 執行現有經核可的 `ANALYSIS_SQL` 和 `STANDALONE_CHIP_SQL`。使用真實資料產生兩版回覆**僅在程序記憶體**，不送 LINE API、不列印私人資料，也不包含 LINE 傳送程式。
- GitHub Actions 單次唯讀預覽 [#44779389604](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/runs/44779389604) 成功：確認 2330 預設路徑只查原股票 SQL，啟用預覽時才附加籌碼 SQL；輸出籌碼日期 **2026-11-20**、分數 **40.65**、來源覆蓋 **65%**，並顯示較舊的綜合評分日期 **2026-11-19** 和「尚未納入」提示。
- 此次預覽使用受控 GitHub Secret 提供的資料庫連線，但它**不等於**以 `line_stock_reader` 執行的正式候選閘道測試。專用讀取角色仍沒有 `daily_chip_scores` 的七欄 SELECT；之前真實唯讀查詢已證實 SQLSTATE 42501。任何正式 GRANT 或部署、旗標啟用、Webhook 切換仍須另行授權。
- 執行完畢已刪除單次預覽 workflow，留存 Actions 成功日誌；`line-stock-analysis-tests.yml` 現在會對預覽腳本進行 Node 語法檢查，無需資料庫憑證。

> 預覽程式針對 2026-11-20 的已驗證 2330 快照設有固定驗收值。之後資料更新時如需重跑，須先重新驗證期待的資料日期和數值，不可把此快照測試稱為持續即時行情監控。
