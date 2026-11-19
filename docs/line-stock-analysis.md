# LINE 股票代碼查詢（獨立 Neon Function）

## 目前功能

- LINE 傳送「2330」、「分析 2330」或「股票 6488」後，查詢現有 Neon `twstock` 的資料。
- LINE 傳送「清單」可顯示最近一次有評分的前 10 檔候選股票；傳送「1」～「10」、「編號 1」或「第 2 名」會分析對應序號。清單每天可能變動，請先查詢當前清單。
- 回覆股票代碼、候選公司名稱、市場、最新可用收盤行情、九均線、RSI14、ATR14、SMC 和綜合/短波長評分。
- 各個資料來源都有自己的日期；若技術指標、SMC 或評分比收盤行情舊，明確標示，避免誤用。
- 不從交易所下載任何完整歷史行情、不更新任何資料表、不下單。
- 股票池是待驗證候選清單，不能把候選名單誤當成全部已確認普通股。
- 依使用者要求封鎖 `1808`。若代碼重複或無資料，不猜測、不製造數據。
- 僅接受 LINE 有效 HMAC-SHA256 webhook 簽章；SQL 採參數化查詢。
- 對 `/health` 提供健康檢查；對 `/` 和 `/webhook` 提供經驗簽的 LINE POST webhook。

## 設計邊界

本專案的 Neon 預設分支 **已經有** 一個名為 `linewebhook` 的函式。這個新增功能故意使用另一個 slug `linestockanalysis`，不覆寫或刪除現有 `linewebhook`、不擅自改變 LINE Developers Webhook URL。

Neon 部署前必須在安全管理介面配置下列兩個環境變數（請不要把值提交到 GitHub）：

- `LINE_CHANNEL_SECRET`：LINE Messaging API channel secret，用來驗證原始請求簽章。
- `LINE_CHANNEL_ACCESS_TOKEN`：LINE channel access token，用於 Reply API。

Neon Functions 若搭配該 Neon 分支的 Postgres，執行時可注入 `DATABASE_URL`。若部署到其他環境，須自行以安全方式設定唯讀連線。以上變數僅由部署環境提供，程式碼不可硬編碼。

本函式只使用 SELECT；建議正式上線另使用資料庫**唯讀角色**及最小必要權限。未連接到 LINE Developers Webhook URL 前，實際在 LINE 傳訊仍會由舊的 `linewebhook` 處理。

## 本地自動測試

```bash
cd line-stock-analysis
npm install
npm test
```

測試使用假資料庫與假 LINE 回覆傳輸，不需要任何 Neon 或 LINE 憑證，也不會傳送真實訊息。GitHub Actions 工作流程 `LINE Stock Code Analysis Tests` 會執行這些測試，並透過 `npm run bundle` 產生包含 Postgres driver 的獨立 `dist/index.mjs`，封裝成 `deployment.zip` 作為 CI artifact（**僅打包、不部署**）。

## 未來安全部署步驟（尚未執行）

1. 先在測試 Neon branch 以新 slug 部署 `linestockanalysis`，勿覆蓋現有 `linewebhook`。
2. 在安全的部署工具中設定 LINE channel secret 與 channel access token，**不要將值輸入 Git 版本庫、CI 日誌或聊天紀錄**。
3. 先對新函式執行 `GET /health`、無效簽章拒絕測試、合法簽章 LINE 開發者驗證。測試中勿發送未經授權的公開推播。
4. 經人工同意後，再決定讓既有 webhook 轉呼叫此功能，或在 LINE Developers 控制台更新 Webhook URL。LINE 一個 channel 僅有一個 webhook URL，**不能以新增函式就假設它已自動接通 LINE**。
5. 以 2330、6488、1808、未知代碼，以及「清單」、「1」、「編號 2」進行端到端測試，確認資料日期、排行編號與缺漏提示。

## 狀態

- GitHub 程式碼、單元測試和 CI：此功能分支開發中。
- 正式 webhook 切換：**尚未執行**。
- Neon 現有 `linewebhook`：**保留、不覆寫**。
- 五年大量下載、Neon 資料寫入、PR 合併：**未授權，本功能不執行**。
