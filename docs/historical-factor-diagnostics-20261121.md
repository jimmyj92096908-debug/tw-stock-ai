# 歷史研究資料產生器與因子有效性診斷（只供研究）

本功能由獨立 CLI 執行，**不會**因合併到 main 自動啟動。它不修改
Neon 任何資料表、不調整目前 50% 回補工作、不更動 LINE 或交易權限。
程式可直接讀取離線 JSON；資料庫來源必須明確啟用唯讀權限並
使用 20 秒 SQL timeout、40,000 筆上限及 120 日查詢窗口。
對免費資源有疑慮時，只使用離線模式。

## 要解決的問題

原本 `tw-factor-ridge-1` 儲存的是彙總驗證報告，不是完整每檔每天的
回測資料。新的 `src/research_dataset.py` 可以把現有的 *歷史已評分*
股票、當日因子、調整收盤價，以及從訊號日之後實際交易日取得的進出
價格，組成可重現的研究資料集。指數、除權息、下市/停牌等問題**不會**
因輸出 JSON 而自動得到解決。

**時間規則：** 每筆 `as_of_date` 是已存評分的訊號日期，
`entry_date` 必須晚於訊號日期，`exit_date` 晚於進場日期，
且必須在指定的 `label_cutoff` 當時已知。價格使用既有的調整收盤，
不把訊號當日收盤假設為可執行買價。

**嚴格排除：** 有任一成分股缺乏當時的調整股價、未到期的未來
報酬或不合理的價格日期，會排除*整個訊號日期股票池*，不只排除
難買或表現不佳的單檔股票。當天個股進出日若不一致（例如停牌），
亦排除整個日期以防不同期間比較。股票池至少 5 檔。每個排除原因
和日期數均寫進 manifest。

## 步驟一：從離線已核對資料建立資料集（預設且不連 Neon）

準備 `verified-source-rows.json`，其每筆格式與既有
`src/trained_factor_model.py` 的 `TRAINING_SQL` 輸出相同，
包含：`market`, `stock_id`, `as_of_date`,
`total_score`, `technical_score`, `smc_score`,
`short_term_score`, `swing_score`, `long_term_score`,
`coverage_weight`, `adjusted_close`, `entry_date`,
`entry_close`, `exit_date`, `exit_close`。

```bash
python scripts/research_dataset_pipeline.py prepare \
  --source-json verified-source-rows.json \
  --start 2026-08-01 --end 2026-10-31 \
  --label-cutoff 2026-11-20 \
  --output local-historical-dataset.json
```

資料集含 `rows` 和 `manifest`。其中 `rows_sha256` 是資料更動檢查碼，
**不是資料來源的數位簽章**，無法單靠 SHA 宣稱官方來源可信。
「有行情」與「當日有可用評分」不同，資料集只代表歷史已評分股票，
不能宣稱涵蓋全市場，也不能忽略股票下市、標的選擇與
歷史調整價格可能在公司行動後重算的偏差。

## 可選：手動唯讀查詢既有 Neon 資料（不可自動排程）

只在已確認額度充足且使用受保護的唯讀 PostgreSQL 身分時使用。
**這個命令會消耗免費運算額度，因此目前回補期間不要啟動。**

```bash
RESEARCH_EXPORT_READONLY=yes DATABASE_URL='<protected-read-only-url>' \
python scripts/research_dataset_pipeline.py prepare \
  --read-neon --start 2026-08-01 --end 2026-10-31 \
  --label-cutoff 2026-11-20 \
  --output local-historical-dataset.json
```

本工具使用單一 `REPEATABLE READ, READ ONLY` 交易、受保護連線、
最多 40,000 筆結果與 120 日窗口。回傳太多資料、權限不足或查詢
逾時必須失敗，不改成寫入資料庫、付費升級或反覆重跑。

## 步驟二：只在開發探索區間測量因子有效性

```bash
python scripts/research_dataset_pipeline.py factors \
  --dataset local-historical-dataset.json \
  --exploration-end 2026-09-30 \
  --min-pairs 10 \
  --output factor-exploration.json
```

`exploration-end` 之後的未來觀察期完全不參與這份因子探索報告。
工具每個有效日期只採用**與上一個已檢測持有期不重疊**的觀察日，
對技術、SMC、短線、波段、長線與總評分分別計算：

- Spearman 排名相關係數（IC）、正相關日期比例、每日期樣本數；
- 因子資料可用率、常數因子／樣本不足／缺漏的日期數；
- 該因子 Top 20% 扣除假設往返 30 bps 後相對相同股票池的超額報酬；
- 相同日期、**相同資料可用股票樣本**下，與原始綜合評分 Top 20% 的差異。

不同因子可能有不同可用股票樣本；只有同樣本配對才可比較。
這是**探索性的描述統計**，不是正式獲利率、因果證據或
未來預測準確率。尤其 `total_score` 本來就是其他因子組合，
因子彼此不獨立，因此不根據單一 IC 大小直接調整主模型權重。
本功能不使用舊 holdout 擬合更好的權重，既有 -2.11 個百分點的
歷史樣本外淨超額結果仍維持不通過。

## 離線驗證

```bash
PYTHONPATH=src python -m unittest \
  tests.test_research_dataset_factor_diagnostics \
  tests.test_research_validation_confidence_risk \
  tests.test_trained_factor_model -v
```

CI 測試使用**合成資料**檢驗程式邏輯，不會使用正式 Neon
憑證，也不會產生真實投資績效。所有報告維持
`orders_enabled=false`，不存在交易或 LINE 訊號推送。
