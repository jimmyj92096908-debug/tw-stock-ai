# 台股研究資料庫 100% 覆蓋率：兩個分母不可混為一談

2026-11-21 正式 Neon **唯讀**核對：`stock_master=1991`；有有效收盤資料
`1982`；至少 60 筆有效收盤資料 `1109`；
其中近期價格、達 60 日且非被研究流程排除的 `1808`，現有可處理
集合為 `1107`，此前其中 `994` 檔具有當日技術＋SMC＋完整評分。

原本一次性 50% 回補工作已成功，主分母 1,991 檔的同股票、同資料日
有效交集達 `1002`（50.3%）。但**不能**把這 1,002 檔當成整個
官方市場清單都已有 60 日歷史。

## 第一階段：把當前可分析的股票做完（已具備官方 60 日行情）

`scripts/eligible_100_catchup.py` 以資料庫當時的交易日及該檔
**最後有效收盤日**為基準，定義：

- 資料庫原有股票；排除在研究排名流程中既已排除的 `1808`；
- 至少 60 筆 `close>0` 的實際行情；
- 該檔最後有效收盤日距全市場最新收盤日不超過 7 個日曆日；
- `daily_technicals`、`daily_smc` 及可發表 `daily_composite_scores`
  必須是**同一檔、同一日**。

此集合為可驗證的 `100% eligible`，不是主分母 1,991 檔的 100%。

流程只使用已存在的`batch_indicator_catchup.run` 和
`composite_score.calculate_all`，每批每市場至多 20 檔，最多 9 輪。
保留每批前後證據，任何失敗、未前進、股價原始筆數改變、股票總數改變、
最新有效收盤日改變、研究集合大小改變或覆蓋率退步就停止。限定
PostgreSQL 目前資料庫大小低於 800 MB 才執行，每次讀取快照在
`REPEATABLE READ READ ONLY` 且有 20 秒 SQL timeout。
不補假價格、不寫入 `daily_prices`、不啟動 LINE 或交易。

一次性受控工作流 `.github/workflows/eligible-100-once.yml` 只在
主分支新增專屬授權標記檔、或手動明確 `apply=true` 時觸發；
與既有指標回補工作使用**同一個 Actions 並行鎖**，不會重複寫入。
主流程合併後，標記檔只允許建立一次。不要透過反覆提交標記檔重跑。

## 第二階段：補齊股票歷史行情（當前尚未有足夠 60 日）

有有效收盤價的 1,982 檔中，有多達 873 檔不足 60 筆實際歷史資料，
上櫃股票佔主要部分。另有 9 檔未有可核實有效收盤；某些股票
可能已停止交易、剛上市、未上市滿 60 個交易日、官方端點暫不可用、
或處於歷史缺漏狀態。不能無根據把這些個股標為「處理成功」。

現有 `daily-bounded-history-enrichment.yml` 每交易日有**小量、
受保護**的官方歷史補足排程；`daily-twse-dated-history.yml`
對上市股票利用官方逐日整批查詢。進一步增加速度之前必須確認：

1. 上櫃歷史 API 長期穩定、有明確來源日期、回傳欄位與錯誤分類；
2. **僅新增缺漏 (market,stock_id,trade_date) 主鍵**，不可覆寫現有
   股票原始行情；尤其現有通用 `db_storage.UPSERT_PRICE_SQL`
   的 `ON CONFLICT ... DO UPDATE` 不符合新回補「禁止覆寫既有行情」條件，
   不可直接拿來做全市場大批匯入；
3. 來源不存在、官方停牌或交易日不足時標示 `NO_VERIFIED_SOURCE`，
   不得合成 60 日價格，也不能把 60 日技術特徵類推成 240 日均線；
4. 免費 Neon 與 GitHub Actions 用量需持續驗證，達到額度上限即停止，
   絕不升級到付費方案；
5. 已有獨立的 50% 完成證據，後續工作的覆蓋率必須重新計算，
   不能以舊數字代替新驗收。

因此 **1,991 檔全量 100% 不是當前能如實宣稱完成的目標**；
現階段先做滿可核實的 60 日股票池，後續擴充官方歷史樣本後持續
重新計算 eligible 分母與未完成原因。

## 離線驗收

```bash
PYTHONPATH=src python -m unittest \
  tests.test_eligible_100_catchup \
  tests.test_coverage_50_catchup \
  tests.test_batch_indicator_catchup -v
```

報告 `eligible-100-evidence.json` 只會宣稱
`scope=CURRENT_RECENT_60_SESSION_ELIGIBLE_STOCKS_ONLY`；
即便 `eligible_complete=true` 也永遠標示
`not_all_1991_master_stocks=true`，未來投資效能驗證與實際交易仍未批准。
