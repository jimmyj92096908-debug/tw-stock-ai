# 官方基本面第一階段：月營收首次觀測快照（禁止歷史資料倒填）

2026-11-21 正式 Neon 唯讀查核：`public.financial_statements` **目前 0 筆**。不能假設已有 EPS、營收、現金流或 ROE 等基本面資料，更不能用今天查到的歷史數字冒充該日已公布的可交易資訊。

本階段新增 **官方 TWSE／TPEx 最新月份營收快照**：

- TWSE `https://openapi.twse.com.tw/v1/opendata/t187ap05_L`
- TPEx `https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O`
- 無 API Key、限兩次 HTTPS 官方 GET、固定來源 allowlist、禁止 HTTP redirect 和單次超過 6 MB、每市場最多 2,500 筆。
- 交易所欄位 `資料年月` 是營收歸屬月；`出表日期` 是官方表格日期，**不是逐家公司真實申報或公開時間**。只記錄請求**回覆後**的可信 `first_observed_at`，絕不推導該公司在更早日期已可交易使用。
- 只新增存在於既有 `stock_master` 的股票，`official_revenue_observations` 唯一主鍵 `(market,stock_id,period_end,payload_sha256)`，`ON CONFLICT DO NOTHING`。若官方修訂同一公司／月份的值，會以另一個摘要新增下一版；**不得覆寫任何已觀測版本**。
- `src/official_revenue_archive.py` 可根據 `first_observed_at` 及實際台灣收盤 13:30，安全擷取某日**當時已觀測**的營收，不能把 2026-11-21 才觀測的值放進 2026-10 的歷史信號。
- 既有 `financial_statements` 不以假資料填入；月營收只在**新表中觀測存證**，尚不會直接接到 AI 訓練或真實交易推薦。EPS、ROE、現金流等仍需有個別正式申報紀錄及披露時間才可成為 PIT 因子。
- 月份變更時用 `period_end` 與首次觀測時點判斷；若兩個官方端點有一個被拒、回傳異常或缺欄，整次回補**失敗停止**，不冒稱兩市都有官方資料。
- 正式 Neon Free 低於 **800 MB** 才可入庫；不修改 LINE、原始行情、模型權重、不增加任何交易。
- **最低頻率每月一次**：既有 GitHub Free Actions 於每月 15 日台灣 14:15 執行，也支援唯一主分支授權標記檔 `.github/official-revenue-archive-authorized-canary-20261121.txt` 做第一次正式查核。此次新增是為了自動形成未來 as-of 歷史，不能回溯補造今天以前的原始觀測版本。

## 測試

```bash
PYTHONPATH=src python -m unittest tests.test_revenue_snapshot_archive tests.test_offline_research_hardening -v
```

測試涵蓋正式民國年月解析、時間區正確換算、來源欄位限制、正規化與財報極值、同月修訂追加、收盤當時未知則拒絕、請求白名單、跳轉與大小阻擋、明確寫入閘門，以及正式 SQL 的 append-only 主鍵。

**已確認的來源限制**：TWSE／TPEx 開放資料通常是當期最新月份，沒有每家公司精確首次發布時戳，也不提供一條可以安全倒推歷史全部公告時間的開放 API。從首次觀測之日起逐月存證才有可靠的模型基本面研究條件；先前未保存的年份不可拿今天快照當作過去已知。模型既有失敗的樣本外驗證結果也不會因新資料來源而自動變成成功。
