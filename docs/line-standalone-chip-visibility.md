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
