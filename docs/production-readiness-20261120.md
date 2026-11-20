# 台股 AI 專案：正式環境與 LINE 整合驗收（2026-11-20）

> 本文件依實際 Neon、LINE Messaging API、GitHub Actions 查詢及 CI 結果整理。文件中的查核結果有時間性；**程式已合併不代表 LINE 已正式切換**。

## 1. 現行架構

```text
台灣證交所 TWSE / 櫃買中心 TPEx 官方資料
              │
              ▼
  GitHub Actions 限額下載＋資料日期校驗
              │
              ▼
       Neon PostgreSQL twstock
       ├── stock_master
       ├── daily_prices
       ├── daily_adjusted_prices
       ├── daily_technicals
       ├── daily_smc
       ├── daily_composite_scores
       ├── line_messages (原本日報收件者資料來源)
       └── line_reply_delivery (Webhook 回覆去重狀態)
              │
      ┌───────┴────────────────┐
      ▼                        ▼
GitHub Actions LINE 日報    LINE 股票查詢候選閘道
（原流程保留）           linestockgateway (預設停用)
                               │
                   ┌───────────┴────────────┐
                   ▼                        ▼
              股票指令                    其他事件
           讀取 twstock               轉送原 linewebhook
```

**目前正式 LINE Developers Webhook URL 仍指向原始函式**，新閘道不會收到真實事件。

## 2. 正式資料庫已核對數據

| 分類 | 2026-11-20 核對結果 |
| --- | ---: |
| 候選股票名單 | 1,991 |
| 至少一個有效收盤行情日 | 1,968 |
| 日 K 明細 | 121,832 |
| 至少 60 個有效收盤日 | 1,104 |
| 至少 120 個有效收盤日 | 38 |
| 至少 240 個有效收盤日 | 38 |
| 有技術指標 | 144 |
| 有 SMC | 144 |
| 曾有有效綜合評分 | 144 |
| 最新可用行情與綜合評分日期 | 2026-11-19 |

**歷史價格覆蓋 ≠ 全部指標完整**。部分股票只有 60 日，可計算某些短／中期指標，無法據此聲稱具有完整 120／240 日訊號。新版 LINE `資料狀態` 指令已分別標示以上涵蓋情況。

## 3. 已建置且保留的排程

- `daily-official-market-snapshot.yml`：官方每日全市場價格補入（不能造價）。
- `daily-twse-dated-history.yml`：有配額的證交所全市場歷史日期回補，每次最多 8 個日期；手動預設 dry run。
- `daily-bounded-history-enrichment.yml`：有配額的逐檔歷史資料補齊，避免影響官方來源。
- `daily-indicator-catchup.yml`：已儲存至少 60 個有效行情日後才補調整價格、技術指標與 SMC。
- `composite-after-market-refresh.yml`：於符合來源／分支／工作成功條件後重算評分；手動預設不寫入。
- `daily-line-report.yml`：原本 LINE 日報排程，沿用原有收件者紀錄、去重與每日報表。
- `twstock-data-quality-monitor.yml`：唯讀檢查資料涵蓋、基本 OHLC、評分與日期異常；增加**獨立排程**，避免 GitHub `workflow_run` 連鎖觸發深度限制使監控漏跑。

GitHub cron 是已設定的工作，不代表未來每次都已成功；請以 GitHub Actions 的成功／失敗紀錄為準。

## 4. LINE 正式端點（已從官方 GET API 直接查核）

- LINE Messaging API `GET /v2/bot/channel/webhook/endpoint` 實際回傳 `active=true`。
- 目前正式 Webhook：`https://br-purple-smoke-a1t9dmzz-linewebhook.compute.c-1.ap-southeast-1.aws.neon.tech/`，原本 `linewebhook` Deployment 4。
- 新版隔離閘道：`https://br-purple-smoke-a1t9dmzz-linestockgateway.compute.c-1.ap-southeast-1.aws.neon.tech/`，Deployment 1。
- 新閘道已部署 Node.js 24 自包含程式；**未配置正式執行憑證、預設不啟用**：`GET /health` 為 HTTP 200；無效／未啟用的 `POST /webhook` 為 HTTP 503。尚無實際 LINE 回覆。
- 舊版 HMAC 空事件驗證：無效簽章 HTTP 401、有效簽章 HTTP 200，未送出 LINE 訊息。

## 5. 正式啟用所需安全設定（尚未完成）

Neon 新閘道環境變數須使用**受保護的部署環境**配置，不應出現在 GitHub 原始碼、CI 輸出、日誌或聊天紀錄。

| 環境變數 | 用途 |
| --- | --- |
| `LINE_CHANNEL_SECRET` | 同一個官方帳號的 LINE 簽章驗證 |
| `LINE_CHANNEL_ACCESS_TOKEN` | 官方帳號 Reply API |
| `LINE_STOCK_READ_DATABASE_URL` | Neon `line_stock_reader`（股票表 SELECT） |
| `LINE_LOG_WRITE_DATABASE_URL` | Neon `line_stock_delivery`（必要訊息欄位和回覆狀態） |
| `LINE_LEGACY_WEBHOOK_URL` | 上列已確認的原始 `linewebhook` 完整 URL |
| `LINE_SINGLE_ACCOUNT_ENABLED` | 預設不設；驗收通過才改 `true` |

已在 Neon 正式資料庫驗證專用讀、寫角色的欄位層級權限；查詢角色無權讀 LINE 私人訊息，收件寫入角色無權 SELECT 訊息全文或刪除行情。 `line_reply_delivery` 表已存在，但正式使用者事件的端到端流程還沒通過。

**不能使用 Neon 管理員 DATABASE_URL 冒充受限角色，更不能把憑證印進 GitHub Actions log。**

## 6. 安全上線順序

1. 確認正式 DB 備份分支、舊版原始 URL、原本每日報告 CI 及收件者紀錄正常。
2. 只在獨立 `linestockgateway` 函式內配置受保護的 LINE／PostgreSQL 專用憑證；不改原始 `linewebhook` 或 LINE Developers 設定。
3. 測試新閘道 HMAC：無效簽章 401；官方空事件測試 200；混合事件可重新簽名轉送舊函式；錯誤時不可靜默吞事件。
4. 由實際管理者控制的測試 LINE 帳號驗證 `2330`、`清單`、`1`、`資料狀態`、`說明`、`1808` 排除及一般文字的回覆；檢查 event ID 去重、有效 token、原本 LINE User ID 日報收件紀錄。
5. 確認可以重跑每日報告 dry run、原始 Webhook 可回復，再用 LINE 官方設定 API 切換到新閘道。保留 LINE Webhook redelivery 原本設定。
6. 如遇真實事件無回覆，**先將 LINE 官方 Webhook URL 恢復上列原始 URL**；先維護使用者收件體驗，再排查新閘道，勿只關掉閘道 enable flag（會造成 503）。

為確保回復能力，新增：
- `scripts/line_webhook_control.py`：預設只用官方 API 查詢既有 Webhook 是否仍為原版；`restore` 需 `--apply` 及額外寫入 gate，目標 URL 永遠固定在已核實原址，修改後重新 GET 驗證。
- `.github/workflows/line-webhook-inspect-restore.yml`：**只有手動觸發**，預設 `inspect`、`apply=false`；回復需明確選擇 `restore` 且 apply true；不存在自動切換至未經驗證端點的流程。
- 對應 `tests/test_line_webhook_control.py` 和 `tests/test_line_webhook_workflow.py` 無網路安全測試。

## 7. 專案可用範圍與尚待完成

- **已可實際使用：** 正式 twstock 資料、行情回補與計算排程、原本 LINE Webhook／每日報告、可在資料庫讀取的股票分析 SQL、資料監控。
- **已部署但尚未對外啟用：** 與原本 LINE 帳號整合的分流閘道 `linestockgateway`，其原始碼、獨立 bundle 與 CI。
- **阻礙完全上線：** 新閘道受保護憑證尚未設定，因此無法做真實 LINE Reply API 的端到端驗收，也尚未將 LINE 官方 Webhook URL 切換。無法用「空事件 HMAC 測試成功」替代真實指令及每日報表收件者驗收。
- **長期資料工作：** 補齊更多 120／240 個交易日的官方歷史行情；目前 144 檔具有效評分、並非 1,968 檔全部有可信分析資料。

此文件以**最小權限、保留舊版功能、可回復、資料不足明示**為正式上線門檻。

## 8. 2026-11-20 最新增量：資料庫角色連線已安全設定到獨立閘道

本節取代以上第 4、5、7 節中「全部環境變數尚未配置」的早期狀態。

- `PR #12` 已通過三組 CI（LINE、Python、隔離 PostgreSQL）並正式合併 `main`，合併 commit `501c72125cca5f8ad0cf82ad90889148e2fd1fe7`。
- 已利用 Neon 專用連線能力，將 `line_stock_reader`（唯讀分析）和 `line_stock_delivery`（限欄位寫入與回覆狀態）之 **twstock 專用連線字串**，直接存入 Neon `linestockgateway` 受保護環境；沒有輸出到 GitHub、程式碼或維運文件。
- 同步設定已經官方 API 查核的舊版 `LINE_LEGACY_WEBHOOK_URL`；目前 `LINE_SINGLE_ACCOUNT_ENABLED=false`。
- 新版 `linestockgateway` Deployment 2 **已完成部署**；設定後再做外部 HTTP 驗收成功（GitHub Actions #44688374960）：`GET /health` 仍為 200，`POST /webhook` 因未啟用仍為 503。測試過後移除一次性工作流程。
- 已完成四項環境配置：`LINE_STOCK_READ_DATABASE_URL`、`LINE_LOG_WRITE_DATABASE_URL`、`LINE_LEGACY_WEBHOOK_URL`、`LINE_SINGLE_ACCOUNT_ENABLED=false`。**只剩原 LINE 官方帳號 `LINE_CHANNEL_SECRET`、`LINE_CHANNEL_ACCESS_TOKEN` 尚未安全綁定到這支新函式**，以及真正啟用並完成封包簽章、LINE Reply API 和轉送測試。
- 原本的 `linewebhook` Deployment 4、`linestockanalysis` Deployment 3、LINE Developers 目前 active URL 不變。不可將停用中閘道直接設為正式 LINE Webhook URL。

**注意：** 首次正式切換不是單純修改 `LINE_SINGLE_ACCOUNT_ENABLED`；必須先安全配置剩餘兩個 LINE 憑證，確認所有簽章／資料庫權限／回覆／轉送驗收通過，再以完整原 URL 和明確回復措施進行切換。不得將 Channel Secret、Access Token 或 PostgreSQL 角色密碼貼入聊天或提交 GitHub。

## 9. 正式 LINE 上線最後阻礙（實際保密設定檢查）

GitHub Actions #44688708316 執行過只輸出 Boolean 的檢查，隨後已移除這個一次性 workflow；**沒有讀取或印出任何憑證值**。

- GitHub Actions `LINE_CHANNEL_ACCESS_TOKEN`：已設定（可用於現有每日 LINE 報告、官方 Webhook GET 查核）。
- GitHub Actions `LINE_CHANNEL_SECRET`：**尚未設定**。
- GitHub Actions `NEON_API_KEY`：**尚未設定**，所以無法安全地由 GitHub CI 把既有 Secret／Token 自動同步到 Neon 新函式。
- Neon `linestockgateway` Deployment 2 目前已安全存入專用 DB 唯讀／受限寫入連線、原始 Webhook URL 與 `LINE_SINGLE_ACCOUNT_ENABLED=false`；**尚無**此閘道專屬 `LINE_CHANNEL_SECRET`、`LINE_CHANNEL_ACCESS_TOKEN`。
- **不可把原 `linewebhook` 或 `linestockanalysis` 的憑證直接揭露到 CI 或聊天，也不可用替代假密鑰處理 LINE 真實事件。**

因此已完成能安全自動化的程式、資料庫、部署與無使用者訊息的測試；**最後的保密憑證綁定與 LINE 真實事件切換仍未完成**。需要具 Neon 控制台與 LINE Developers 控制台存取權的管理者，在 Neon `linestockgateway` 的受保護環境中設定：
`LINE_CHANNEL_SECRET` 與 `LINE_CHANNEL_ACCESS_TOKEN`（同一個現有 LINE 官方帳號）。
**不要貼入 ChatGPT 聊天或 GitHub 程式庫。**

初次新增後仍須保留 `LINE_SINGLE_ACCOUNT_ENABLED=false`，待 LINE HMAC、舊版事件轉送、Reply API 及每日報表收件驗收完成才可啟用並切換。官方 LINE Webhook 目前仍指向原始版本，沒有被更動。
