# 2026-11-20 原版 LINE webhook 寫入權限事件（受控診斷）

狀態：**已完成最小欄位授權、等待真實 LINE 測試確認；不可宣稱已修復完成。**

## 問題與時序

- 正式 LINE Webhook 原版 `linewebhook` Deployment 4，原本 URL 經 2026-11-20 22:20（Asia/Taipei）的受控切換工作驗證恢復。
- Neon Function Logs: 原版 `linewebhook` 於 2026-11-20 **20:13、21:54、22:22、22:34** 均出現 `permission denied for table line_messages`（UTC 12:13、13:54、14:22、14:34）；此錯誤在 22:16 受控切換測試之前已存在。
- Neon 已建立 `line_stock_reader`（2026-11-20 03:59:32Z）與 `line_stock_delivery`（03:59:41Z）最小權限角色。兩者出現在原版 `linewebhook` Deployment 4（2026-11-18）之後。
- 用獨立臨時 Neon Function（僅讀取 `DATABASE_URL` 和 `DATABASE_URL_UNPOOLED` 的 URL 使用者名稱，不讀取、不回傳密碼）和一次性 GitHub Actions 實測：**兩個 Neon 自動注入的連線均指向 `twstock`，角色為 `line_stock_delivery`**。這與 Neon CLI 查得的預設管理連線 `twstock_admin` 不同。
- **安全清理：**臨時診斷 Function `dbrolechecknov20` 已刪除，一次性 GitHub workflow `one-time-neon-role-audit.yml` 已移除；歷史 Actions 執行紀錄保留作稽核。

## 權限模擬（只用 EXPLAIN，不寫入）

使用 `line_stock_delivery` 身分：

| SQL 模式 | 變更前 | 加欄位權限後 |
| --- | --- | --- |
| `INSERT (...) RETURNING event_id` | 允許 | 允許 |
| `INSERT (...)` 無 `RETURNING` | 允許 | 允許 |
| `INSERT (...) RETURNING id` | permission denied | **允許** |
| `INSERT (...) RETURNING *` | permission denied | 拒絕（預期） |
| `INSERT (..., received_at)` | permission denied | 拒絕（預期） |

原版 Function 原始碼未取得，**並未證明原版 INSERT 實際使用 RETURNING id**。此權限修正屬於最小範圍的可檢驗候選修復。

## 2026-11-20 已套用的唯一正式資料庫權限變更

執行：

```sql
GRANT SELECT (id) ON TABLE public.line_messages TO line_stock_delivery;
```

正式 Neon `twstock` 權限複查：

- `has_column_privilege('line_stock_delivery', 'public.line_messages', 'id', 'SELECT') = true`
- `message_text`、`line_user_id` 的 SELECT 仍為 `false`
- 整張表 `SELECT` 仍為 `false`
- 原本最低限度的入站事件 INSERT／`event_id` SELECT 不變；沒有更新舊 `linewebhook` 程式、LINE URL 或憑證
- 新版 `linestockgateway` Deployment 6 仍停用

必要時的可逆 SQL：

```sql
REVOKE SELECT (id) ON TABLE public.line_messages FROM line_stock_delivery;
```

**注意：** 回復前需考量依賴此權限的新舊函式，並確認原問題診斷完畢；不要因為一次未回覆就擴權至訊息全文或整表讀取。

## 尚未完成：真實 LINE 驗收

請用原本 LINE 個人帳號向原版官方帳號送出一次 `你好`，觀察是否有回覆。查核 Neon 原版 `linewebhook` 同時段日誌是否仍報 `permission denied`，再確認是否產生資料庫文字收件紀錄。若錯誤仍存在，下一步應取得原始 `INSERT` SQL 或加入不洩漏使用者訊息的受控角色／SQL 稽核；不得在沒有證據下授予 `SELECT *`、整表 `INSERT` 或 `SUPERUSER`。

這份紀錄不含 LINE token、Channel secret、Postgres 密碼、完整連線字串、訊息文字或使用者 ID。
