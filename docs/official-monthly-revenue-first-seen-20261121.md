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

## 真實官方來源 canary 的異常與修正紀錄

第一個官方資料歸檔 run
[44870153333](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/runs/44870153333)
執行前所有離線測試通過，但實際 TWSE 回傳中有
**極高年增率（超過原先 100,000% 上限）**，早期解析器
因 `Unsupported finance number` 安全停止，Neon 沒有建立新表、
也沒有寫入月營收。此來源比例可能是比較基期接近 0 而造成，
不能在未知情況下認定為一般有效量化因子。

修正後官方的**當月營業收入金額、交易所表格日、
資料年月、真實第一次取得時間**仍逐項驗證與保存；
`abs(YoY)>10000%` 的來源值僅從可量化的百分比欄位排除
（`reported_yoy_pct=NULL`），並將
`official_yoy_outlier_suppressed=true` 納入版本摘要，
不能把極端比例假造或縮寫成正常值。收入金額本身仍必須
有有限數值且在支援範圍內。這個規則另有純測試鎖定。

最初唯一 marker 已使用，不能重用；修正後只使用另一個
新檔案 `.github/official-revenue-archive-authorized-canary-v2-20261121.txt`
執行一次新的來源真實核對。每月正常自動排程的頻率不變。

## v2 官方來源成功解析，實際 PostgreSQL 寫入問題修復

v2 真實來源 run
[44870517692](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/runs/44870517692)
已越過官方數值驗證，但在實際批量 `INSERT ... SELECT` 時，
psycopg3/PostgreSQL 回報：
`AmbiguousParameter: inconsistent types deduced for parameter $2;
text versus character varying`。同一個命名參數在 INSERT 目標和
`stock_master` 比較中被推斷成不同型別，原本 Python-only
測試無法偵測。正式來源寫入**整個資料庫事務回滾**，
Neon 仍然沒有部分歸檔資料。

v3 修正每個重複參數的明確 PostgreSQL 型別（如
`%(stock_id)s::varchar(6)`、
`%(market)s::text`，以及日期／數值／時區欄位的具體 cast），
並新增`tests/test_revenue_snapshot_archive_postgres.py`；
在既有`Stock Database Diagnostics (Isolated CI)`
臨時 schema 進行第一次插入、完全相同資料再次寫入
`rowcount=0`、下一版來源保留、非 `stock_master` 代號拒絕，
以及 rollback 不留測試資料。

舊授權標記不能重用，v3 僅使用
`.github/official-revenue-archive-authorized-canary-v3-20261121.txt`
單次來源驗證。**CI 通過前不嘗試再次正式寫入**，本修正
不涉及任何付費方案。
