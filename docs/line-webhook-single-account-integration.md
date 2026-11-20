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

## 已取得的舊版文字訊息實證（2026-11-20）

使用者在既有 LINE 官方帳號發出 `6213`、`2330` 後，收到：

```text
收到你的訊息：6213
AI 台股投資系統正在建置中。
```

其中 `2330` 也回覆相同格式，顯示原本 Webhook 能接收並回覆，但還沒有股票指標分析。這只證明這兩個文字情境，不能推論所有舊版指令、追蹤、圖片及群組行為。

## 依舊版實證建立的候選整合（尚未部署）

- `line-stock-analysis/single-account-candidate.mjs` 採用原本可觀察的文字回覆作為不識別指令的後備文字，股票指令轉入現有 `buildReplyText`。
- 先驗證 LINE HMAC，再處理一對一文字事件；透過注入的 `recordMessage` 介面草擬與原本每日報告相容的收件者紀錄。後續已另新增參數化 SQL writer 與預設停用的候選入口；**兩者均未部署到正式 Neon，亦未在正式資料庫執行寫入**。
- `line-stock-analysis/tests/single-account-candidate.test.mjs` 使用假 Channel Secret、假使用者 ID、假資料庫與假 LINE Reply API，測試文字、排行榜、封鎖代碼、無效簽章、重送、記錄失敗及非文字事件。
- **仍有上線阻擋事項**：原版完整功能未知；實際 DB 記錄的交易與重送策略尚未完成。特別是「先記錄、再回覆」在 LINE Reply API 失敗後，若重送被唯一事件 ID 去重，可能造成漏回覆；正式實作前需處理。
- 因此 GitHub 測試成功仍不是 LINE 正式端到端成功。沒有取得使用者切換授權，絕不更改 `linewebhook`、正式 Webhook URL 或每日報告排程。

## 第二階段：訊息收件與 LINE Reply 重送的修正（2026-11-20）

### 已實作但未部署的程式

- `line-stock-analysis/delivery-state.mjs`：可注入的 PostgreSQL SQL adapter。先用 `INSERT ... ON CONFLICT DO NOTHING` 記錄既有 `line_messages` 收件欄位，再獨立申請 reply lease；**重複的訊息紀錄不代表回覆成功**。
- `sql/line_reply_delivery_schema.sql`：提議新增 `public.line_reply_delivery`。僅記錄 `webhookEventId`、回覆狀態、嘗試次數、租約識別碼與有效期限，沒有使用者 ID 或訊息全文；**尚未套用正式資料庫**。
- `line-stock-analysis/single-account-candidate.mjs`：原本的 HMAC 驗證先行，只處理已知一對一文字情境，將股票指令導向既有查詢；未知文字暫按截圖中觀察到的固定提示處理，但舊版完整功能仍未知。
- `line-stock-analysis/single-account-entry.mjs`：與目前 `index.mjs` 分離、**預設停用且未打包部署**的候選執行入口。僅在 `LINE_SINGLE_ACCOUNT_ENABLED=true` 且所有必要環境變數齊全時處理 Webhook。使用兩條不同的最小權限 PostgreSQL 連線：`LINE_STOCK_READ_DATABASE_URL` 和 `LINE_LOG_WRITE_DATABASE_URL`。
- 每日 LINE 報告 `src/send_line_report.py` 保持不變。

### 已驗證

`line-stock-analysis/tests/delivery-postgres.integration.test.mjs` 與 GitHub Actions 使用**一次性本機 PostgreSQL 17 容器**，資料庫固定為 `line_ci_test`，且測試程式拒絕連到非 `127.0.0.1/localhost` 的資料庫；絕不連線到正式 Neon。確認：

- 重複收件事件只寫入一次 `line_messages`，不會阻斷後續 reply 重試。
- 多個並行請求只能申領同一個 `webhookEventId` 一次。
- Reply 成功後標記 `sent`；狀態為 `sent` 時不再重送。
- Reply 明確失敗時可回到 `retryable`；30 秒逾期租約可由下一個請求重領；最多 3 次。
- 先前租約的呼叫者不能替目前新租約標記完成。
- 無效簽章、不合法事件、找不到資料庫與暫停模式均安全拒絕或跳過。

### 仍不代表完全可靠

- LINE 官方文件說重送 Webhook 沿用相同 `webhookEventId` 與 reply token，且有時限；重送也需要在 LINE Developers 開啟「Webhook redelivery」，本專案**尚未更改該設定**。
- Reply API 可能已接受訊息，但 HTTP 回應途中遺失。這時資料庫與 LINE 的結果無法以一般 PostgreSQL 交易做到真正 exactly-once；候選程式回傳 502 並標記不確定，最多有限次數重試，同一個 reply token 已使用時 LINE 可能拒絕重試。
- 若重送關閉、時間已過、三次均失敗或發生不確定的網路錯誤，仍可能漏回覆。必須加入監控、異常處理流程並在正式上線前測試。
- 新候選入口目前只支援可觀察的一對一文字行為；原本可能還有 `follow`、`unsend`、其他類型訊息。因原始 `linewebhook` 程式不可得，**不可視為功能完全相容，也不得正式切換**。
- 原始 `line_messages` 可能包含使用者文字及 LINE User ID；需要確認告知、留存與取消傳送訊息（unsend）處理，再授權正式寫入。

### 權限設計（尚未建立帳號或授權）

讀取角色只需對 `public.stock_master`、`public.daily_prices`、`public.daily_technicals`、`public.daily_smc`、`public.daily_composite_scores` 的 `SELECT` 權限。寫入角色只需對 `public.line_messages` 指定的訊息欄位有 `INSERT`、對 `event_id` 有 `SELECT`，以及對新 `public.line_reply_delivery` 具必要的 `SELECT/INSERT/UPDATE` 權限。憑證必須在受保護的部署環境建立、設定，不得寫進 GitHub。

### 上線前仍需的人工核准

1. 取得舊版程式或完成足以涵蓋正式使用情境的黑箱測試（至少每日報告收件者維持、私人訊息、群組、追蹤/封鎖、非文字、unsend）。
2. 在非正式環境驗證新表與最小權限角色，審核使用者訊息留存；確認 LINE Webhook redelivery 設定、觀測與重試策略。
3. 由使用者**明確授權**正式資料庫遷移、正式部署及 Webhook URL 變更；每項均與本次開發分開核准。
4. 保存完整原始 Webhook URL 與部署版本，準備實際回復步驟；切換後在原本 LINE 帳號驗證並監控。

官方依據：
- https://developers.line.biz/en/docs/messaging-api/receiving-messages/
- https://developers.line.biz/en/reference/messaging-api/#send-reply-message

## 第三階段：沿用原有 `linewebhook` 的分流閘道（2026-11-20，未部署）

因舊版函式的完整原始碼仍未取得，改採用**轉送原本服務，而非重寫其未知功能**的候選方案：

- `line-stock-analysis/single-account-gateway.mjs` 先驗證 LINE 原始 Webhook 的 HMAC 簽章，再依事件內容分流。
- 僅一對一私人文字訊息中的四位股票代碼、`清單`、`1～10`、排除代碼等明確支援指令，由新股票候選處理器處理並以獨立 reply 狀態去重。
- 一般文字、追蹤事件、群組、非文字、未知指令、待命模式等，**不重新實作舊功能**，直接轉送到既有 `linewebhook`，保留原本的處理路徑。
- 當同一個 LINE Webhook POST 同時包含股票與舊版事件時，分開事件集合、保留其他合法欄位並重新計算各集合的 `X-Line-Signature`，確保舊版不會消耗股票事件的 reply token，也避免一個事件被兩個處理器回覆。
- 先處理股票子集合：如果失敗，原本 webhook 不會收到舊版子集合，HTTP 回傳非 2xx 供 LINE 選擇重送；如果舊版轉送失敗，同樣回傳非 2xx，已成功回覆的股票事件由資料庫 reply 狀態阻止重送。
- `line-stock-analysis/single-account-entry.mjs` 的舊版轉送目的地由 `LINE_LEGACY_WEBHOOK_URL` 指定，但只允許目前已存在 Neon `linewebhook` 的**固定 HTTPS 主機與受限路徑**，不接受任意 URL。啟用仍需 `LINE_SINGLE_ACCOUNT_ENABLED=true` 與各自的授權憑證。
- `line-stock-analysis/tests/single-account-gateway.test.mjs` 模擬原始合法/偽造簽章、純股票事件、純舊版事件、混合事件、群組/待命、轉送失敗等；不接觸真實 LINE 或正式資料庫。
- **並未修改**舊 `linewebhook`、LINE Developers 正式 Webhook URL、原本 `src/send_line_report.py` 或已上線的 `index.mjs`。目前 `build.mjs` 仍然**只封裝 `index.mjs`**，不會打包這個候選分流閘道。

### 此方案仍需驗收的問題

1. 必須先確認 LINE Developers 當前原始 Webhook 的**精確路徑**、原本函式對重新簽章與轉送事件的相容性，並做有限度的實際驗收。模擬測試不等於原本函式真的接受轉送。
2. 候選入口需要另外審核的讀／寫帳密、回覆狀態表、監控與 LINE 重送設定；**尚未設定、尚未套用正式資料庫**。
3. 原本的 `linewebhook` 須繼續可直接使用，並在切換失敗時將 LINE Developers Webhook URL 復原；任何正式切換必須取得使用者明確授權。
4. 就算保留所有非股票事件舊路徑，仍有短暫失效、LINE token 逾時、混合事件重送、舊函式回覆失敗等剩餘風險，因此不能宣稱 exactly-once 或正式可用。

結論：分流方案可在**一個 LINE 官方帳號**下保留原本的訊息路徑，同時新增股票指令，但仍處於未部署的測試階段。

## 第四階段：時間限制、防止誤攔截、可打包驗證（2026-11-20）

- 依 LINE 官方 Reply API 規則區分兩種期限：一般 webhook 回覆 token 應於**收到 webhook 後 1 分鐘內**使用；重送的 token 也應於收到重送 webhook 後 1 分鐘內使用，且**事件發生後 20 分鐘**即不可使用。程式採用保守的 50 秒處理上限和 19 分鐘重送上限；不可聲稱保證在上限內一定成功。
- `single-account-candidate.mjs` 的 `isReplyTokenEligible` 採接收時間判斷，避免把原始事件 `timestamp` 誤當唯一的回覆期限；若資料庫查詢耗盡回覆時間，釋放申領並回覆 HTTP 503，避免嘗試使用可能已逾期的 token。
- `single-account-gateway.mjs` 僅攔截具備**一對一私人 user ID、非空 reply token、有效 webhookEventId 及文字訊息**的股票事件。缺少必要欄位的模糊事件改走原本 `linewebhook` 路徑，不由新版靜默吃掉。
- 新增 `build-candidate.mjs`、`npm run bundle:candidate`，產生 `line-stock-analysis/candidate-dist/index.mjs`。CI 只做建置、語法檢查及**未啟用時 HTTP 503**驗證；此檔不會部署、不會上傳為正式部署包。
- 原本 `build.mjs` 保持不變；正式自動測試的可部署 ZIP 仍僅包含既有 `dist/index.mjs`。
- 新增時間窗口單元測試、慢速資料庫查詢、遺失事件 ID / User ID / reply token 的分流測試。
- 參考文件：[LINE Messaging API 回覆 token](https://developers.line.biz/en/reference/messaging-api/#send-reply-message) 及 [LINE Webhook redelivery](https://developers.line.biz/en/docs/messaging-api/receiving-messages/#redeliver-a-webhook-that-failed-to-be-received)。

### 正式切換後的回復演練（僅作為計畫，未執行）

1. 在任何切換前，在受控設定紀錄**原有** LINE Developers Webhook URL（原本 `linewebhook`），並核對 Neon 現用部署版本；不要將 Secret、Token 或私人訊息放進紀錄。
2. 若新閘道無法完成預期回覆，**優先把 LINE Developers Webhook URL 恢復原本 `linewebhook` URL**，再驗證一般文字訊息可回覆、每日報告收件者仍可讀取、GitHub 排程未異動。
3. Webhook URL 還指向新閘道時，不應單獨將 `LINE_SINGLE_ACCOUNT_ENABLED` 關閉當作回復，因為這只會讓新入口回 HTTP 503；必須先恢復舊 URL。
4. 任何新建立的 `line_reply_delivery` 表、最小權限角色與紀錄不自動刪除；先完成事故分析和保存必要稽核資料。若要移除須另行取得資料庫異動授權。
5. 回復後確認無重複 LINE 回覆、無錯誤代碼、無新增非預期收件者；若需切換回新閘道，先重新完成測試及取得授權。

**開發狀態：此分流閘道尚未部署；真實 LINE Reply API、舊 `linewebhook` 轉送與資料庫最小權限尚未進行端到端驗收。**

## 2026-11-20 合併與正式狀態核對

開發用 PR #10 已在驗證後合併到 `main`（`0f8146f2d6128eabac40a47f8cefc7ee11d632ed`）。這表示程式與自動測試已納入主分支，**不等於 LINE Webhook 已切換**。

- 正式 `linewebhook` 仍維持原本部署 ID 4，未部署或替換其原始程式，避免既有每日報告與訊息記錄受影響。
- `linestockanalysis` 仍維持部署 ID 3；目前在正式 LINE Developers 後台使用的 Webhook URL 尚未改成新版候選閘道。
- 資料庫已完成一部分正式來源驗證的行情與歷史回補，但現有 1,966 檔有非空收盤價的候選股票中，只有 44 檔有技術指標、SMC 與有效評分；LINE 分析須清楚告知不同資料的最新日期及覆蓋程度。
- 下階段仍需執行經實際憑證簽章的代理回覆、舊版訊息紀錄與每日報告整合驗收，並留下可以切回原 URL 的回復策略。未驗證前不應宣稱單一 LINE 帳號新版股票指令可正式使用。

## 2026-11-20 專用 PostgreSQL 最小權限角色（已在正式 Neon 建立並核對）

在 `twstock` 建立 `line_stock_reader` 與 `line_stock_delivery`，二者使用 Neon 的 **read_only** 類型作為基底，撤銷初始的所有 `public` 表與序列權限及預設授權後，僅選擇性重新授權：

- `line_stock_reader`：只可 SELECT `public.stock_master`、`daily_prices`、`daily_technicals`、`daily_smc`、`daily_composite_scores`；對 LINE 私人訊息表沒有 SELECT，也沒有資料寫入權限。
- `line_stock_delivery`：只可 INSERT `line_messages` 的 `event_id`、`line_user_id`、`message_type`、`message_text`，只可 SELECT `event_id`；對 `line_reply_delivery` 有特定狀態欄位的 SELECT／INSERT／UPDATE；無權 DELETE 股票歷史，不能 SELECT LINE 訊息全文，無權讀取 `daily_prices`。
- 已透過 `has_table_privilege`、`has_column_privilege` 及獨立角色登入 SELECT 進行驗證。此舉未修改原本的管理角色 `twstock_admin` 或 `linewebhook` 函式。
- 資料庫內 `line_reply_delivery` 表已存在，但截至本次核對沒有已處理的真實 LINE 回覆事件。不能因此宣稱 LINE Proxy 端到端已完成。

**目前尚未把這兩個角色的密碼配置到新版 Neon 候選函式的環境變數，也尚未將新的分流代理設定成 LINE Developers Webhook URL。** 配置前不可使用管理員資料庫連線取代最小權限角色。不得把密碼或連線字串寫進 GitHub 版本控制。
