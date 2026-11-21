# 真正未來樣本外研究：先封存完整模型訊號，等待未來成熟標籤

2026-11-21 的投資分析系統已具有 1,129/1,129 檔最新合格技術＋SMC＋有效分數（整個 stock_master 為 1,991），但當前 `tw-factor-ridge-1` 保存的 holdout 曾被檢視過、平均淨超額報酬 -2.114523 個百分點、正式研究上線閘門 `BLOCKED`。現存歷史評分去重後僅 4 個完整可比獨立期間，不能重新回算昨天來製造全新驗證。

這次完成「未來首次觀測訊號先凍結」的程式與固定流程；**不是盈利模型上線**。

## 不可事後作弊的封存邊界

- 僅以現存固定 `models/tw-factor-ridge-1-research.json` 模型係數、`feature_names` 與模型檔真實 SHA256 運算；不重新 fit／選出看起來有賺錢的新權重。
- `LATEST_MODEL_SQL` 自 Neon **一個 REPEATABLE READ** 事務取出最新有效行情日的完整評分股票池；最新綜合評分日必須等於整個市場最新有效成交日，且原模型訓練截點嚴格在訊號日前。
- 研究池上下限 50–2,500 檔；每一檔特徵、原評分、當日官方正收盤、固定 Ridge 模型相對分數、**模型與原評分的完整名次**都保存；不得在未來只保留已獲利股票。單日陣列最多 1.8 MB。
- 只允許 **當日台灣 14:00 後**（市場已收盤），或距最後真實行情日最多三天、**週一至週五 08:30 前**（下個可能交易日開盤前），或週末。過去太久的訊號日或下一時段已開盤後，一律拒絕新增；不會拿今天才算出的 2026-10 分數偽稱 2026-10 已觀測。
- `public.research_forward_frozen_cohorts` 以 `(model_version,signal_date)` 為不可覆寫唯一主鍵；以 PostgreSQL 伺服器 `clock_timestamp()` 真實加上 `frozen_at`，保存整日研究池 JSONB、模型 SHA256 和 canonical JSON 資料 SHA256，`ON CONFLICT DO NOTHING`；重複執行內容不變可安全略過，**同日期模型、成分或分數不同時直接報錯**，絕不覆寫先前研究訊號。
- 每次入庫仍限 Neon Free、原始 800 MB 保守停止線；全體成分資料僅在私有保護資料庫內，GitHub summary 僅輸出研究日期／總數／摘要及 `live_trading_approved=false`，不提供個股推薦或發 LINE。
- `composite-after-market-refresh.yml` 已有的正式來源完成後評分流程，僅在成功的**23:00 台灣時間每日官方快照**分支接上一次「整日研究池預先封存」；次日 03:10 指標回補的重新計分**不得回寫同日既存凍結**。新的一次性 `research-forward-once.yml` 只允許主分支實際新增 `.github/forward-research-first-precommit-20261121.txt` 觸發初次 canary，**沒有新的每日計費排程**。

## 新股票、證券異動與前視偏差

此版本保存最新資料庫中存在的完整原始信號股票池，並無法證明歷史上已下市、停止交易的股票都有在當時名單內；研究上仍必須檢查市場存活偏差。調整收盤價在公司行動後可能事後修正，其未來 `t+1` 進場、`t+6` 出場價值還沒有產生；目前 **沒有**取得未來報酬、**沒有**承諾結果正超額。

接下來未來真實交易日自然成熟後，才能使用**已凍結股票名單**、真實官方價格與公司行動版本的來源證據，核對實際進出場和研究成本，要求至少 10 個互不重疊的完整觀察窗口、足夠日曆跨度與正式獨立審查。不能使用未來 outcome 反過來改變已保存的選股成分和 model SHA。

即使數據都足夠，`src/model_release_acceptance.py` 仍明確限制「研究模型可人工審查」而非啟用 LINE 訊號或實際券商下單。

## 測試

```bash
PYTHONPATH=src python -m unittest tests.test_research_forward_freeze -v
```

隔離 PostgreSQL 17 集成測試 `tests.test_research_forward_freeze_postgres`
證明第一筆實際插入成功、同一日期重複插入 `rowcount=0`、
改動模型 cohort hash 不可能覆寫、真正資料庫時戳不可由 Python 補造。
所有測試僅在 GitHub Actions disposable `stock_ci_test` 進行，
不在正式 Neon 進行測試性 UPDATE 或 DELETE。
