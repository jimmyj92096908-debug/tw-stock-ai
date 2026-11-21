# 一般產業官方資產負債表（上市＋上櫃）首次觀測存證

截至 2026-11-21，正式 Neon：1,991 檔股票主檔、合格研究池 1,139/1,139 完整評分，官方月營收 1,988 筆，2026 Q3 官方一般產業累計損益／EPS 1,944 筆，整庫約 232 MB、Free 方案。

官方上市和上櫃提供**一般產業的最新季度資產負債表**，而非每家企業完整歷史首次公告資料。來源固定為：

- TWSE 官方：`https://openapi.twse.com.tw/v1/opendata/t187ap07_L_ci`
- TPEx 官方：`https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap07_O_ci`

採用官方欄位「年度」「季別」「公司代號」「出表日期」（若存在）、「資產總計」「負債總計」「權益總計」「流動資產」「流動負債」「歸屬於母公司業主之權益合計」，TPEx 允許已確認資料規格的英文字段別名。

**所有金額保留官方原值及其千元新台幣口徑**，不把「權益總計」錯用成「母公司業主權益」、不將負債率和 ROE 混同。對於資產、負債、權益三個主要欄位皆非空的資料，核對 `資產 ≈ 負債＋權益`（容許來源四捨五入），若不合則保留原始值、`accounting_identity_verified=false`，不能提供正常的研究財務比率。這項檢查**不是會計查核報告，也不能證明審計意見為無保留**。

新資料庫表 `public.official_balance_sheet_observations`：
- 依 `(market,stock_id,period_end,payload_sha256)` 主鍵**只新增缺漏或官方不同版本**，不 UPDATE 或 DELETE，另以 PostgreSQL trigger 拒絕既存版本重寫；
- 真正 `first_observed_at` 僅在完成官方 HTTPS 回應**之後**取得，無個別公司公告時分則保持未知；
- 「出表日期」是官方表格日期，不等於公司逐筆對市場公布的時點；不得以季度末回填或推定過去回測已知；
- 只允許既有 `stock_master` 股票，其他發行人或證券類別不偷偷插入；
- `asof_balance` 僅回傳在台灣 13:30 訊號截點以前**確實已第一次觀測**的版本，且資產恆等式不通過時停用財務比率研究。
- 原始行情、`financial_statements` 舊資料表、`daily_composite_scores`、固定 Ridge 模型及 LINE／交易功能均不修改。

## 免費額度、排程與來源錯誤

重用既有 `official-monthly-revenue-archive.yml` 的**每月同一個 GitHub Action**，不新增另一個付費排程；各市場最多一次固定 HTTPS GET、單回應上限 8MB、每市場 1–2,500 行、禁止重導到未授權來源，全部來源資料先通過檢查才進行單筆 PostgreSQL 交易，Neon 800MB 保守停止線保持不變。官方任一來源錯誤則整批停止，不以猜測補欄位。

首批正式驗證使用**唯一一次**且經過 CI 的主分支新增檔案 `.github/official-balance-first-seen-authorized-20261121.txt`。沒有額外補價、不修改市場與模型資料；成功或失敗都保存非敏感摘要。

## 測試與界線

```bash
PYTHONPATH=src python -m unittest \
  tests.test_official_balance_sheet_archive \
  tests.test_official_balance_sheet_postgres -v
```

在隔離 PostgreSQL 17 實際測：插入一筆、相同主鍵第二次零寫入、不同官方金額生成新 SHA 並保留舊版、不屬於 `stock_master` 的公司拒絕、UPDATE 與 DELETE 被 trigger 阻擋，且事務最後完全 rollback。純測試另檢驗每筆會計恆等式、首次下載前不可見、官方表格日期、數值格式與失敗的 HTTPS 驗證。

**現金流量表**：在 TWSE／TPEx 已查核的最新 openapi 財務報表目錄中可確認資產負債表與損益表，但尚未確認一個同等可靠的即時「一般產業現金流量表」官方免金鑰端點。故**不會創建或填充現金流／自由現金流假欄位**，也不宣稱 ROE、負債率或任何新增基本面因子已通過獨立樣本外投資績效驗證。銀行、保險、金控等特殊格式需專用報表及完整會計口徑，不能混入一般產業的假完整率。
