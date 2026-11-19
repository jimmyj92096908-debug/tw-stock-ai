# 單一 LINE 官方帳號整合方案（尚未正式上線）

## 決策與現狀（2026-11-20）

- 使用現有「AI台股投資作戰系統」LINE 官方帳號，不建立第二個帳號或 Messaging API 頻道。
- **不修改** LINE Developers 的正式 Webhook URL，亦不覆蓋 Neon 現有的 `linewebhook`。
- Neon `linestockanalysis` 已部署 ID 3；`LINE_CHANNEL_SECRET`、`LINE_CHANNEL_ACCESS_TOKEN` 環境變數存在，合法簽章空事件回應 HTTP 200，無簽章請求回應 HTTP 401。這些不等同真實 LINE 回覆驗證。
- Neon `linestocktest` 是**沒有 LINE 憑證**的隔離端點，不能接收此正式帳號的合法事件，並非另一個 LINE 帳號。
- 原始 `linewebhook` 的程式來源未取得，故**無法聲稱舊版所有行為已被完整保留**；切換阻擋條件未解除。

## 目前已從現有程式與資料庫確認的相容性需求

1. `src/send_line_report.py` 從 `public.line_messages` 取出 `message_type='text'` 的 `line_user_id` 作為每日報告收件者。
2. 同一個報告腳本透過 `LINE Push API` 發送每日報告，寫入 `message_type='outgoing_daily_report'` 的紀錄，並以 `event_id` 去重；GitHub 定期作業維持獨立運作。
3. Neon `line_messages` 既有欄位為 `id, event_id, line_user_id, message_type, message_text, received_at, created_at`，`event_id` 設 UNIQUE；未變更表結構或資料。
4. 新版股票分析：`2330`、`分析 2330`、`6488`、`清單`、`1–10`，及被排除的 `1808`；查詢只使用 `SELECT`，資料日期不一定最新。
5. 舊版可能另有追蹤、非文字訊息、未知指令等行為，未取得原始碼前不得臆測或覆寫。

## 未上線的純函式整合契約

`line-stock-analysis/legacy-compatibility.mjs` 只建立未來的路由與紀錄欄位草案，**沒有寫入資料庫、沒有呼叫 LINE API、沒有被任何部署入口引入**。

- LINE 簽章驗證必須發生在任何處理與儲存前。
- 支援的股票指令擬路由到分析功能。已排除的股票應明確回拒。
- 未識別文字、追蹤、圖片等事件保留舊版路由，**不能假設新函式可模擬原本的回覆**。
- 私人一對一文字訊息且具有 `webhookEventId` 時，草擬記錄 `event_id`、`line_user_id`、`message_type='text'`、`message_text`。不把群組訊息直接加入私人收件名單。
- 正式實作記錄前，需經明確同意採用最小權限 DB 寫入角色、原子去重機制、隱私/留存政策及錯誤重試策略。絕不將 LINE Token、Secret 或個人識別碼放進 GitHub 原始碼或測試資料。
- 分流時只有**一個**真正的 LINE 回覆擁有者，避免舊版與新版同時使用同一 replyToken，造成重複或失敗。

## 模擬測試

`line-stock-analysis/tests/legacy-compatibility.test.mjs` 使用假 LINE 事件、假簽章、假 Postgres 回應與記憶體中的假 LINE Reply API，驗證：

- 4 位代碼、`清單`、序號、封鎖股票皆能產生正確類別的分析回覆
- 原本報告收件者所需的文字記錄欄位可被完整建立
- 群組、沒有穩定事件 ID、不明指令與非文字事件不會被誤加進新報告收件名單
- 錯誤簽章不會導致查詢或回覆

測試並未證明真實 LINE Reply API 可用，也未驗證任何舊版未知行為。

## 正式切換的必要條件

1. 找到舊版 `linewebhook` 原始碼或依現有帳號實測列出等效完整行為（不得要求使用者另外申請帳號），建立功能對照。
2. 在獨立**未部署**候選整合入口實作舊版必要功能、持久化寫入與股票分析；測試重送去重、回覆一次、錯誤處理與報告收件者保留。
3. 做不影響正式訊息的測試；評估在同一 LINE 頻道的驗證路徑與受影響使用者。不可用假的 replyToken 呼叫 LINE Reply API 來聲稱成功。
4. 保留舊 URL、部署版本及回復程序；取得使用者**明確切換授權**後才修改 LINE Developers Webhook URL。
5. 切換後以私人帳號實測 `2330`、`清單`、`1`、`1808` 與原有功能；監測異常立即回復。

## 仍未獲授權的事項

- 正式 LINE Webhook 切換
- 覆寫現有 `linewebhook`
- 對正式 `line_messages` 或其他表寫入
- 發送真實 LINE 訊息或推播
- 合併 draft PR #10
