# 台股 AI 投資分析系統｜tw-stock-ai

以台灣證券交易所（TWSE）與櫃買中心（TPEx）官方公開資料、Neon PostgreSQL、Python 與 LINE Messaging API 建立的台股資料分析專案。

> **狀態（2026-11-20）**：行情匯入、歷史回補、技術指標、SMC、綜合評分、資料品質稽核、原本的 LINE 日報已具備正式執行程式與自動化。單一 LINE 官方帳號的**新版股票指令仍未切換正式 Webhook**，不可宣稱使用者現在就能收到新版分析。所有資訊均為歷史資料整理，不是即時報價或下單指令。

## 第一階段：立即使用的研究報告（已在正式 Neon 實測）

**可以直接使用：** [最新研究報告執行清單](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/workflows/first-stage-report.yml)。選擇最新的 `completed / success` 執行，在 **Artifacts** 下載 `twstock-first-stage-research-report`，解壓縮後開啟 `research-report.html`。同時提供 Markdown 和 JSON。此報告是歷史研究用途，不是即時報價或買賣訊號。

**從真實資料到研究報告的完整鏈路：**

```text
TWSE / TPEx 官方行情 → 有效歷史收盤 → 調整行情／技術指標／SMC
                 → 綜合評分 → 已保存的訓練模型排名 → HTML / MD / JSON
```

- **已驗收：** 2026-11-20 正式 Neon 受控批次成功，且指標補算後綜合評分與研究報告均已成功更新；一次性驗收通道完成後會移除。查看 [真實批次 #44725314839](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/runs/44725314839) 及 [報告 #44726935466](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/runs/44726935466)。
- **已設定：** 台灣時間週二至週六 03:10，每市場每批最多 20 檔的自動技術／SMC 補算；有效補算後重算綜合評分，成功後以唯讀方式刷新報告，另保留 04:45 獨立報告排程。每次是否真正執行，必須以 GitHub Actions 的 `schedule` 事件及 Neon 補算前後證據核對；不能只憑已合併程式宣稱完成。
- **資料覆蓋提醒：** 有歷史行情不等於技術／SMC 或綜合評分已補齊。請以**最新**報告中的 `indicator_pending`、`indicator_complete`、`scored_stocks` 與日期判斷；固定在 README 的數字可能過時。
- **最近一次獨立確認（2026-11-20，行情日 2026-11-19）：** 上市 1,085 檔符合近期 60 日補算資格，技術／SMC 已補齊 **83 檔**、待補 **1,002 檔**；上櫃 21 檔均已補齊。全資料庫有效綜合評分 **206 檔**、最新行情日合格研究股票 **195 檔**。本數字為歷史快照，不會自動隨 README 更新；以最新研究報告及 [第三批正式驗證](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/runs/44728697062) 為準。
- **尚未完成：** 新版 LINE Webhook 尚未正式切換。候選 Neon 閘道仍缺同一頻道受保護的 LINE Channel Secret / Channel Access Token 和真實端到端驗收，不能把候選程式測試通過當作 LINE 已上線。研究模型樣本外績效仍未過關，交易訊號與自動下單維持關閉。

詳見 [研究報告使用說明](docs/first-stage-research-report.md)、[真實補算驗收](docs/authorized-next-20-indicator-batch-20261120.md)、[LINE 正式上線門檻](docs/line-production-readiness-20261120.md)。

## 系統架構

```text
TWSE / TPEx 公開資料
    │
    ├─ 官方全市場每日行情（日期、OHLC、成交量核驗）
    ├─ 上市全市場日期型歷史資料（每次最多 8 日）
    └─ 上櫃與特定股票歷史資料（有限額來源下載）
    │
    ▼
Neon PostgreSQL · twstock
    ├─ stock_master                    候選股票名單
    ├─ daily_prices                    實際成交日價格
    ├─ daily_adjusted_prices           經公司行動調整的行情
    ├─ daily_technicals                均線、RSI、ATR 等
    ├─ daily_smc                       市場結構、流動性與 SMC 事件
    ├─ daily_composite_scores          多因子綜合評分
    ├─ line_messages                   原本每日報告收件與去重紀錄
    └─ line_reply_delivery             新閘道的回覆狀態／重試
    │
    ├─ GitHub Actions 自動品質稽核
    ├─ GitHub Actions 每日 LINE 報告 → 現有 LINE OA
    └─ 新版 LINE 單一帳號分流閘道（尚未正式接管）
         ├─ 股票指令 → 已存資料查詢
         └─ 其他訊息 → 原本 linewebhook
```

## 已有功能

| 功能 | 主要程式 | 說明 |
| --- | --- | --- |
| 股票池與行情 | `src/stock_list.py`, `src/official_snapshot_ingest.py` | 交易日、來源與官方數值驗證；不可合成缺漏行情 |
| 上市日期型歷史回補 | `src/twse_dated_history.py` | 每次最多 8 個官方日期；以交易日鍵去重，不覆蓋既有收盤價 |
| 上櫃／個股歷史回補 | `src/bounded_history_enrichment.py`, `src/full_market_refresh.py` | 小批次、來源月份上限與進度紀錄 |
| 技術指標與調整行情 | `src/build_adjusted_prices.py`, `src/calculate_technicals.py` | 以實際行情日計算，長期 MA 需要更多交易日 |
| SMC 分析 | `src/calculate_smc.py` | 結構事件、流動性標記與其他欄位 |
| 綜合評分 | `src/composite_score.py` | 選擇資料已達要求的候選股票，並記錄評分日期與因子涵蓋 |
| 資料品質稽核 | `src/stock_db_audit.py` | 唯讀檢查行情、評分、覆蓋率、資料日期與 60／120／240 日歷史完整度 |
| LINE 每日資料報告 | `src/send_line_report.py` | 沿用現有好友訊息紀錄；已送成功去重，單一收件者錯誤不阻塞其他人 |
| LINE 股票查詢候選 | `line-stock-analysis/` | HMAC 驗證、參數化 SQL、Reply Token 重試／去重、舊功能轉送與可回復設計 |

**資料覆蓋不是分析覆蓋。** 即使某股票已有單日行情，也不代表已達 60、120 或 240 個有效交易日，更不代表已完成 SMC 或綜合評分。所有日期與有效結果應查資料庫，而非使用固定假數據。

## 已訓練的研究模型（尚未提供交易訊號）

本分支另提供真正由歷史資料估計係數的 `tw-factor-ridge-1` 統計排名模型，不是未訓練的假 AI。它使用既有多因子評分、技術/SMC 與多週期資料，對官方行情的除權息調整後報酬做時間隔離評估，並保留可重現的訓練係數、數值矩陣與模型研究排名快照：

- 主要模型：`src/trained_factor_model.py`
- 讀取資料／輸出模型檔的指令：`scripts/trained_factor_pipeline.py`
- 真實 Neon 訓練係數與驗證證據：`models/tw-factor-ridge-1-*.json`
- 驗收規則與重跑說明：`docs/trained-factor-model.md`

驗證狀態：**模型程式完成，但樣本外績效不通過**。模型已使用 57 個開發日期訓練，21 個已知樣本外日期的平均扣假設成本超額報酬約 -2.11 個百分點，且這段樣本外區間曾在早期版本被檢視過，尚不能稱獨立投資績效證明。所有最新排名均屬研究成果，內建 `abstain=true`、`live_trading_approved=false`，沒有自動下單或 LINE 交易訊號。

## LINE 指令（新版功能完成正式切換後才適用）

| 指令 | 預定回覆 |
| --- | --- |
| `2330`、`分析 2330`、`股票 6488` | 最新可用收盤資料、技術指標、SMC 與綜合評分 |
| `清單` | 最新可用且同評分日有收盤價的前 10 檔觀察清單 |
| `1` 至 `10`、`編號 2` | 查詢當次清單對應股票 |
| `資料狀態` | 價格／歷史完整度／技術／SMC／評分覆蓋與日期 |
| `模型狀態`、`研究報告` | 已保存研究模型版本、失敗的樣本外驗收，以及唯讀研究報告入口；不可提供買賣訊號 |
| `說明` | 使用方式 |
| `1808` | 依既有排除設定拒絕分析 |

原本的 **LINE 官方帳號、原本 `linewebhook`、好友收件者記錄及每日報告必須保留**。目前 LINE 官方設定仍指向原版，不會因主分支合併新程式而自動切換。

## 開發與測試

需 Python 3.11 與 Node.js 24，並準備相應的 PostgreSQL 環境。執行下列**離線單元測試**不需要真實 LINE 使用者，也不會主動傳送訊息：

```bash
python -m pip install -r requirements.txt
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py' -v

cd line-stock-analysis
npm install --no-audit --no-fund
npm test
npm run bundle
npm run bundle:candidate
```

本機若未設定 `STOCK_CI_POSTGRES_URL` 或 `LINE_CI_POSTGRES_URL`，需要一次性 PostgreSQL 的整合測試會略過；GitHub Actions 的隔離 PostgreSQL 工作流程會正式測試 SQL 及回覆狀態。開發環境**不可把 CI 的整合測試連到正式 Neon**。

### 唯讀資料庫檢查

設定受保護、最小權限的 `DATABASE_URL` 後：

```bash
python src/stock_db_audit.py
python src/stock_db_audit.py --json
```

資料稽核使用唯讀交易，輸出彙總資料而非 LINE User ID 或私人訊息。正式資料庫帳密、LINE Token 與 Channel Secret 絕不可貼進 GitHub、Issue、CI 日誌或聊天訊息。

### 常用 GitHub Actions

| 工作流程 | 目的 |
| --- | --- |
| `daily-official-market-snapshot.yml` | 官方每日行情 |
| `daily-twse-dated-history.yml` | 上市歷史日期限額回補 |
| `daily-bounded-history-enrichment.yml` | 上櫃與特定個股有限額回補 |
| `daily-indicator-catchup.yml` | 待股票有足夠歷史後補技術／SMC |
| `composite-after-market-refresh.yml` | 受控更新綜合評分 |
| `twstock-data-quality-monitor.yml` | 唯讀健康檢查與異常偵測 |
| `daily-line-report.yml` | 原本每日 LINE 報告；手動預設 dry-run |
| `line-stock-analysis-tests.yml` | LINE 指令、簽章、整合與隔離資料庫回覆測試 |
| `line-gateway-official-canary.yml` | 手動觸發官方已簽章空事件測試；不切換 Webhook |
| `line-webhook-inspect-restore.yml` | 官方 Webhook 唯讀檢查與明確確認後復原舊址 |

排程是否按時成功，應以 GitHub Actions 的實際執行紀錄為準。

## 正式 LINE 上線狀態與阻礙

- **原本 `linewebhook` 正在運作**；使用 LINE 官方唯讀 API 確認註冊的 Webhook 仍為舊址。
- 新的 `linestockgateway` 已在 Neon 作為隔離函式部署，資料庫讀寫使用各自最小權限角色：`line_stock_reader`、`line_stock_delivery`；在隔離資料庫已驗證回覆去重及授權邊界。
- **仍待在 Neon 新閘道的受保護環境設定**：同一個 LINE 頻道的 `LINE_CHANNEL_SECRET`、`LINE_CHANNEL_ACCESS_TOKEN`。此時 `LINE_SINGLE_ACCOUNT_ENABLED` 必須保留關閉，不得將正式 Webhook URL 指向尚不能處理事件的閘道。
- 配置後先執行官方簽章空事件測試，再用**受控測試帳號**驗證股票指令、一般文字、重送、每日報告收件者及舊版轉送。全部通過才可切換，保留原 URL 作為回復路徑。

詳見 [LINE 正式上線驗收與缺漏](docs/line-production-readiness-20261120.md)。**目前不能把「程式已合併」誤認為「新版 LINE 分析已正式啟用」。**

## 其他文件

- [專案正式環境與架構](docs/production-readiness-20261120.md)
- [資料品質、覆蓋率與歷史缺漏](docs/stock-data-quality-2026-11-20.md)
- [上市官方歷史行情與指標追補](docs/dated-bulk-market-history-20261120.md)
- [LINE 指令詳細說明](docs/line-stock-analysis.md)
- [LINE 與原本 Webhook 的相容性設計](docs/line-webhook-single-account-integration.md)

## 風險與聲明

資料來源可能延遲、停牌或缺漏，評分不是獲利保證，也不是買賣、證券投資顧問或自動下單建議。本專案不使用假行情填補缺資料的股票，不會僅因有價格就推定所有技術指標完整。正式使用時仍需遵守適用的資料使用條款、LINE Messaging API 配額與個人資料保護要求。
