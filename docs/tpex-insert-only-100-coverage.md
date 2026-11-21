# 主分母 1,991 檔向 100% 前進：上櫃官方歷史「只新增」管線

最近正式 Neon 唯讀查核：`stock_master=1991`，
`daily_prices` 有有效收盤的股票 `1982`，達 60 個有效交易日的
股票 `1109`；其中上櫃 `890` 檔有效有價股票中，只有 `22` 檔
有 >=60 日歷史。其餘大部分上櫃股票的日線歷史過短，**不能先
算 60 日技術指標再宣稱全面完成**。

新 `scripts/tpex_official_history_insert_only.py` 只使用專案內已存在
且具測試的 TPEx 官方 `tpex_market_data.fetch_month`，針對
有 1～59 筆真實有效收盤的上櫃股票，在不付費的前提下每日少量
補最近 5 個完整或當前月份的正式日 K：

- 逐筆核對來源必須是 `TPEX_TRADING_STOCK`、代號正確、
  交易日落在實際要求的月份且不在未來、OHLC 合理、
  數值非負且無重複日期。停牌、無成交或來源無正值收盤的
  日子不偽造價格。
- 對 `daily_prices` 只執行
  `ON CONFLICT (market,stock_id,trade_date) DO NOTHING`，
  **現有原始股價完全保留**。不呼叫現有
  `src/db_storage.py` 的 `ON CONFLICT ... DO UPDATE`
  匯入器。
- 使用既有的 `market_data_refresh_state` 記錄成功、
  官方沒有可新增的正值價格及來源驗證失敗，最短間隔兩天，
  不讓少數無歷史的代號佔滿每日輪替。
- 最多每次 10 檔、每檔 5 個月份、合計 50 次官方月資料請求；
  單一股票匯入失敗時回滾該股票事務，不影響既有資料。
- Neon 目前資料庫接近 800MB 時停止；不會付費擴容。
- `.github/workflows/tpex-official-insert-only-history.yml` 每週二至
  週六**台北時間 02:10** 每次最多 10 檔，和既有
  `daily-bounded-history-enrichment` 使用同一個並行鎖。
  下游既有的 03:10 指標補算排程再挑出有 >=60 日資料的股票
  補計技術與 SMC，評分仍須依既有正式評分流程通過驗收。
  沒有重複觸發原本的一次性 50% 任務。
- 合併後不自動補算全部 870 檔；一次性受控推送只對
  **2 檔**啟動來源 canary，待確認真實增量後才讓日常批次
  漸進改善。來源限速、Neon 免費運算與 Actions 使用者
  原有額度均優先，不得購買 API 或付費資源。

## 為何還不能宣稱全市場 100%

這個模組只覆蓋符合基本資料格式且目前在資料庫已有至少一筆有效
行情的上櫃股票。未有任何正值行情的 9 檔、剛掛牌或上市尚不足
60 個實際交易日的股票、來源官方端點未提供歷史、失去交易資格的
股票及原研究模型特別排除的 1808，需獨立評估交易資格與官方歷史，
而非假造、複製其他股票價格或填補缺漏作成功。

「可研究股票池 100%」與「所有 1,991 檔 100%」不同。
任何新的 60 日合格股票加入後，都必須重新計算分母與
同一股票、同一最新有效收盤日的技術、SMC、綜合評分交集。
最終全量目標依賴官方歷史的可取得性，**不是時間或成本可保證**。

## 測試

```bash
PYTHONPATH=src python -m unittest \
  tests.test_tpex_official_history_insert_only \
  tests.test_tpex_market_data -v
```

資料匯入腳本只接受 `--apply` 加上
`STOCK_TPEX_INSERT_ONLY_HISTORY_ENABLED=yes`；
預設離線安全驗證不寫入任何資料。
