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
