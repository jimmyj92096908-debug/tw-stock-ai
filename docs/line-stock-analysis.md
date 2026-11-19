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

## 部署與整合狀態（2026-11-20）

- 原 LINE 頻道仍使用原本 `linewebhook`；**尚未切換** Webhook URL。
- Neon `linestockanalysis` 的 Deployment ID **3** 狀態 `completed`，環境已配置 `LINE_CHANNEL_SECRET` 和 `LINE_CHANNEL_ACCESS_TOKEN`；未將憑證提交 GitHub。
- 外部檢查已取得 `GET /health = HTTP 200`、無簽章 `POST /webhook = HTTP 401`；使用者在自己的電腦送合法簽章空事件取得 HTTP 200，對 LINE Bot Info API 驗證 Token 取得 HTTP 200。**真實 LINE 使用者訊息回覆與資料庫端到端路徑尚未驗證**。
- 另外有沒有 LINE 憑證的 `linestocktest` 測試函式；它不是 LINE 新帳號，亦未被 LINE 正式頻道指向。
- 已針對 `twstock` 執行唯讀 SQL 查詢，測試單筆股票及排行。資料有缺漏，且部分股票（例如 2330）最新可用行情仍是 2026-10-30，不是即時價格。
- 在 draft PR #10 新增 `legacy-compatibility.mjs` 純函式整合草案及 mock 測試；**此檔未引入正式部署入口，也未執行資料庫寫入**。
- 因原 `linewebhook` 原始碼不可得，尚無法保證舊版所有行為與報告收件者紀錄可被新函式取代。
- 使用者決定沿用原本 LINE 帳號，不建立第二個帳號。詳細保留方案及切換門檻參閱 [單一 LINE 帳號整合方案](line-webhook-single-account-integration.md)。
- GitHub PR 仍是草稿、未合併。未修改舊函式、沒有改 Webhook URL、沒有發出真實 LINE 訊息或改寫資料庫。
