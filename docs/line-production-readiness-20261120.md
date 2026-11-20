# LINE 單一帳號股票分析：正式上線驗收與安全回復紀錄

更新：2026-11-20（Asia/Taipei）。本頁區分「程式／隔離資料庫測試」與「實際 LINE 已切換」。

## 現有產品

- 股票候選資料庫 `twstock`：股票代碼搜尋、行情、技術指標、SMC、綜合評分與排行榜，資料日期以表內交易日為準，並非即時行情。
- GitHub Actions：官方行情快照、上市全市場日期型歷史行情回補、上櫃有限額逐檔回補、指標追補、綜合評分重算、唯讀資料品質稽核、每日 LINE 報告。
- 原本的 LINE 官方帳號使用 Neon `linewebhook` Deployment 4，既有私人訊息紀錄 `public.line_messages` 仍用作每日推播的收件者來源。
- 新版 `linestockgateway` Deployment 2 與 `linestockanalysis` Deployment 3 是**獨立候選服務**，並非正式 LINE Webhook 的入口。

## 實測結果

1. **正式 LINE Webhook 查核**：GitHub Actions #44691278454，使用 LINE 官方只讀 API 檢視，回傳 `active=true`、`is_original_legacy_webhook=true`。原本 LINE 設定沒有修改。
2. **新閘道安全停用**：同次測試，`GET /health` HTTP 200，未簽章 `POST /webhook` HTTP 503；不可解讀為已接收到真實 LINE 事件。測試後已移除一次性 workflow。
3. **Neon 角色真正登入**：在完全隔離的 Neon 子分支 `line-gateway-permission-acceptance-20261120`，使用 `line_stock_reader` 可執行股票名單 SELECT、不能 SELECT LINE 訊息全文；使用 `line_stock_delivery` 可新增假的純測試收件事件並讀取自己的 event_id，不能讀取原始訊息全文或股票價格。全部權限由 PostgreSQL 實際強制執行，沒有在正式資料庫建立假 LINE 使用者。
4. **真實 PostgreSQL 回覆狀態重試**：同一個隔離 Neon 子分支中，使用 `line_stock_delivery` 角色確認：初次 claim（attempts=1）→ `retryable` → 重領（attempts=2）→ `sent` → 再領被拒。正式資料庫的 `line_reply_delivery` 不受影響。
5. **網路安全修正**：新閘道傳送帶 LINE 簽章的原始訊息至固定舊網址時，`redirect:'manual'` 且每次重新驗證主機，拒絕把原始 LINE 事件、reply token 或訊息轉送到上游 301/302/307/308 的其它主機；也不輸出上游 HTTP 回應正文。LINE Reply API 同樣禁止轉址。
6. **每日推播容錯**：對單一收件者被 LINE 拒絕（HTTP 400/404/422）的情況，繼續處理剩餘收件者，但把工作結果標示為失敗供維運追查；已成功推送的人仍記錄到原有 `line_messages`，同一天重跑會跳過已完成者。401、403、429 或伺服器錯誤會立即中斷，避免未經授權或配額不足時繼續大量傳送。
7. **整合自動測試**：新增實際一次性 PostgreSQL + 模擬簽章/LINE API/舊版代理的整合測試，確認「收件寫入成功、回覆失敗、重新交付、只回覆一次、舊訊息仍轉送原系統」全流程。CI 的 PostgreSQL 測試採序列化，避免共用 `public` 模擬表發生測試競爭。**此測試沒有使用正式 LINE 使用者、回覆 Token 或寫入正式 Neon。**

## 研究模型狀態指令（候選閘道，尚未正式啟用）

新版候選 LINE 股票查詢增加 `模型狀態`、`研究報告`、`研究模型`、`AI模型` 的私聊指令。指令內容由已合併至主分支的 `models/tw-factor-ridge-1-research.json` 和 `models/tw-factor-ridge-1-evaluation.json` 產生，**不是即時模型預測或下單指示**。會明白呈現模型版本、研究資料期間、未通過的樣本外績效，以及最新已產生的 GitHub Actions 研究報告入口。

這條路由在 `single-account-gateway.mjs` 只處理經簽章驗證、符合完整私聊回覆契約的訊息；一般文字、群組、追蹤與非文字事件仍由原有 `linewebhook` 負責。當模型評估與已存模型版本不符，或有人把驗證狀態改成允許交易時，此指令會**拒絕呈現成功**，而不是給出錯誤信號。

這只是**程式碼及離線 E2E 驗收**，不是官方 LINE 用戶已收到回覆；原本的 `linewebhook` Deployment 4 沒有被替換。正式切換仍需要受保護的 Channel Secret 與 Access Token、官方已簽章測試、真實測試帳號的受控端到端驗收和可回復方案。

## 仍未通過的正式啟用門檻

**不能以以上測試直接宣稱已正式上線。** Neon `linestockgateway` 目前部署環境只列出 `LINE_LEGACY_WEBHOOK_URL`、`LINE_LOG_WRITE_DATABASE_URL`、`LINE_SINGLE_ACCOUNT_ENABLED`、`LINE_STOCK_READ_DATABASE_URL`，仍**缺少兩項必備密鑰名稱** `LINE_CHANNEL_SECRET` 和 `LINE_CHANNEL_ACCESS_TOKEN`。由於現有工具不會以明文顯示 LINE 金鑰，不能替使用者從舊函式讀出或複製兩個密鑰，更不能把它們放進 GitHub 版本控制。

正式切換之前需完成以下驗收（每步均可在新入口仍未接管正式帳號時執行）：

1. 由具權限的維運者在受保護的 Neon Functions 設定頁為 `linestockgateway` 配置**同一個 LINE Messaging API 頻道**的 `LINE_CHANNEL_SECRET` 與 `LINE_CHANNEL_ACCESS_TOKEN`；保留已存在的原始 `LINE_LEGACY_WEBHOOK_URL` 及 `line_stock_reader`、`line_stock_delivery` 最小權限 PostgreSQL DSN。不要在聊天或 GitHub Issue 中貼出機密。
2. 保持 `LINE_SINGLE_ACCOUNT_ENABLED` 關閉，先核對環境名稱、DSN、舊版目的地是否完全吻合；確認可以一次復原至原本的 `linewebhook` URL。
3. 以 `.github/workflows/line-gateway-official-canary.yml` 的 **manual** `run_test=true` 對 isolated gateway 做官方已簽章空事件測試。必須看見 **200**；它不會更改註冊的 Webhook URL，也不能證明真實文字事件會成功。
4. 在可回復的受控環境以實際 LINE 測試帳號驗證 `2330`、`清單`、`資料狀態`、其他一般文字、群組、追蹤/取消傳送與重送／失敗，並核對原本每日報告收件者資料。必須確認非股票事件交給舊 `linewebhook`，而股票事件只回一次，兩者不互相消耗 reply token。
5. 只有當所有受控驗收通過，才將 LINE Developers 的正式 Webhook URL 指向新閘道；如發現錯誤，透過 `.github/workflows/line-webhook-inspect-restore.yml` 的 **manual** `action=restore`、`apply=true` 恢復原始 URL，確認原本一般文字回覆和每日報告正常。

> 回復注意：若 LINE Webhook URL 指向新閘道，單純把 `LINE_SINGLE_ACCOUNT_ENABLED` 關閉會造成 HTTP 503，**不能取代把註冊 URL 恢復舊版**。

## 資料庫最新觀察

截至本次 read-only 檢查：候選股票 1,991 檔、1,968 檔有歷史收盤價、共 187,439 筆價格資料；至少 60 日有行情 1,108 檔、至少 120 日 1,093 檔、至少 240 日 38 檔；技術指標／SMC／有效評分各 164 檔。全球最新行情及有效評分日均為 2026-11-19。資料品質依原有定期稽核更新，勿以全域最新日期代表每一檔都已更新。

## 安全界線

本輪沒有切換 LINE 註冊 Webhook URL、沒有部署或覆蓋原本 `linewebhook`、沒有用實際 LINE User ID 或真實訊息執行寫入測試，也沒有在正式 Neon 清除資料。**隔離權限驗證成功不等於正式 LINE 發送測試成功。**
