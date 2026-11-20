# LINE 2330 籌碼欄位權限：授權前檢查、原子授權與回復

> 2026-11-21；**預備文件，正式 Neon 尚未執行 GRANT/REVOKE**。本 PR 的所有變更只建立 SQL、唯讀驗收及隔離 PostgreSQL 測試，不會部署 Neon Function、切換正式 LINE Webhook 或發送 LINE 訊息。

## 現況與必要性

Neon `twstock` 中，`twse/2330` 最新獨立籌碼評分已儲存（2026-11-20，**40.65 分**，來源覆蓋 **65%**），但 `line_stock_reader` 對 `public.daily_chip_scores` 所需的七個欄位均缺 SELECT；舊的綜合評分仍是 2026-11-19，不能把新籌碼值直接混到舊總分。

此項**待授權**資料庫權限變更只應准許這七個欄位：

`market, stock_id, as_of_date, total_score, coverage_weight, institutional_score, margin_score`

沒有整表 SELECT、INSERT/UPDATE/DELETE、私人 `line_messages` 權限，更不可授予管理員權限或存取憑證。現有 `line_stock_delivery` 角色不能被拿來當股票研究查詢帳號。

## 已完成之受控檔案（均不會自動於正式庫執行）

- `sql/line_chip_reader_column_grant.sql`：未來在**額外明確核准**後才由 DBA/正式資料庫維運人員手動執行。單一 `BEGIN/COMMIT` 交易先檢查 `twstock`、角色非高權限、表與七欄完整、所有七欄仍未授權、沒有額外讀寫權限；只執行欄位 SELECT GRANT，於同一交易驗證，失敗時不能部分提交。
- `sql/line_chip_reader_column_rollback.sql`：如回復需要，只撤回剛才七欄的 SELECT，並驗證沒有殘留籌碼讀取權限；若意外出現整表 SELECT，**停止**而不是假稱撤回七欄即完全安全。回復本身也須核准，不得自行執行。
- `scripts/line_chip_readiness.py`：強制 PostgreSQL 唯讀連線，檢查確實**只有**七個欄位可讀、沒有整表 SELECT 或額外欄位、沒有籌碼寫入權限、沒有私人 LINE 訊息讀寫權限，以及登入角色非高權限；獨立籌碼資料日必須在收盤日當天或之前，且相差**不超過七個日曆天**。它不查詢私人訊息內容、不執行授權或部署。
- `line-stock-analysis/tests/zzzzzz-chip-column-grant-migration.integration.test.mjs`：使用 CI 內新的本機一次性 `twstock` 資料庫與假資料，**原樣執行這兩份正式 SQL**；驗證授權前拒絕、授權後 2330 的 40.65／65% 可讀，未授權欄位／私人訊息／UPDATE 都被拒絕，回復後重新拒絕；重複授權或意外既有多餘權限也必須失敗。

## 未來正式執行操作（尚未授權，**以下指令本輪未執行**）

在操作者確認正式環境與其回復權限後：

1. 先以**唯讀**方式取得 `line_chip_readiness.py` JSON 報告，檢查缺七欄、不擁有私人訊息權限，並儲存不含憑證及個資的驗收摘要。
2. 另經使用者明確同意「僅授予 `line_stock_reader` 上述七個欄位的 SELECT」，且授權時間及變更窗口已確認後，使用受保護的正式連線，在 `twstock` 執行 `psql -X -v ON_ERROR_STOP=1 -f sql/line_chip_reader_column_grant.sql`。**不要把連線字串或密碼放在指令列、CI log 或 PR**。若預檢發現權限已有變動，停止並重新審查，而非強制套用。
3. 使用真正的 `line_stock_reader` 登入（不能只依管理員執行 `has_column_privilege`）運行 `STANDALONE_CHIP_SQL`，應能讀到以股價日為上限的 2330 籌碼資料。驗證無法讀取 `line_messages`、`daily_chip_scores` 未授權欄位、不能寫入資料。不要為測試插入私人使用者紀錄。
4. 再以唯讀方式執行 `scripts/line_chip_readiness.py`，檢查前述範圍、資料時效、額外權限為零。這只能使「選擇性籌碼查詢權限」通過，**不能自行認定正式 LINE 候選閘道已驗收或切換**。
5. 若需要回復且另外核准，使用同樣受控方式執行 `sql/line_chip_reader_column_rollback.sql`，再次實際登入確認七欄被拒絕；如存在額外整表權限需人工安全審查。原版 Webhook 的回復屬於**另一個**操作流程，不能以撤回 DB 權限取代。
6. 上線仍需另行授權的事項：候選 Neon Function 的新程式部署／憑證、`LINE_CHIP_SCORE_DETAILS_ENABLED=true`、官方簽章及 LINE 真實帳號驗收、原版 Webhook 切換與回復測試。**這些都不是本輪開發的一部分。**

## 不變項

- `public.daily_composite_scores`、`public.daily_chip_scores` 的**資料列**不修改；SQL 僅可能在未來明確核准後修改角色 ACL。
- 無 LINE API 發送、Webhook 設定 PUT、交易下單或部署。
- CI 使用假股票、假帳號與本地 PostgreSQL，不觸碰正式 Neon。
