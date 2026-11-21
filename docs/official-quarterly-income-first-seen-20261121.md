# 官方季度綜合損益表（一般產業）首次觀測存證

2026-11-21，原本 `public.financial_statements` 仍無任何經正式日期版本核對的完整季度財報；月營收已有 1,988 筆首次觀測存證。**不能把當天剛下載的 2026 年 Q3 數據誤說成 2026 年 9 月 30 日已經公布。**

本階段加入兩個**官方免金鑰、僅為一般產業**的最新季度綜合損益來源：
- TWSE `https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci`。
- TPEx `https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_ci`。

這些官方 OpenAPI 可能只提供**最新已報告季度**，且公司陸續申報，不能假設有完整歷年資料、銀行保險財報或完整市場百分率。其他財務資料（資產負債、現金流量、ROE）尚未接入本模型。一般業別季度損益的當季呈現值可能是 **年初至該季累計 YTD**，故 EPS 和收入均明確標示 `*_ytd_*`；**不能誤把 Q3 的 EPS 當作僅 7–9 月的單季 EPS。**

每筆永久保存：
- 市場別、股票代號、會計年度、季別、真實季度期末；
- 年初累計營業收入（千元新台幣）、營業利益、淨利、基本每股盈餘（元），只存官方存在且可驗證的非空欄位；
- 官方表格 `出表日期`（若官方未提供則保持 NULL，不能臆造）、真實 HTTP 回覆**後**的 `first_observed_at`、固定官方來源端點及正式內容 SHA256；
- 來源同季度修訂會新增不同的 SHA256 版本，既存 `(market,stock_id,period_end,payload_sha256)` 不覆寫；另有 PostgreSQL 實體觸發器拒絕 UPDATE／DELETE。
- 從原本 `stock_master` 核對代號；非現有清單代號不插入。
- `asof_quarterly` 以台灣訊號日 13:30 和真實第一次觀測時間決定是否可用；在第一筆資料下載之前的歷史回測**一律不可見**。官方出表日期不是逐家公司實際公告時分。

## 有上限的正式執行

- 兩個固定官方 HTTPS 端點，最多兩次 GET；嚴格來源 allowlist、禁止 redirect、每筆回應最多 8MB、每市最多 2500 列；異常格式／來源中斷則整批停止，無付費服務或額外 API key。
- Neon Free 800MB 停止線，新增與版本修訂只做 `ON CONFLICT DO NOTHING`。
- 沿用已存在的 `official-monthly-revenue-archive.yml` 每月 15 日台灣時間 14:15 作為月營收與季度最新版本的共同首次觀測作業；**沒有新增週期性付費排程**。
- 初次唯一一次正式來源 canary 由主分支新檔案 `.github/quarterly-income-first-seen-authorized-20261121.txt` 觸發；沿用 `git diff --name-only --diff-filter=A` 核對文件確實在最新 commit 新增，避免重複手動偽觸發。
- 新季度收入的初次入庫只建獨立 `official_quarterly_income_observations`，不往既有 `financial_statements` 回填未經核對的完整會計資料。
- 不會重訓 Ridge 模型、改動權重、修改 LINE、發出 LINE 或券商交易訊號。

## 驗收

```bash
PYTHONPATH=src python -m unittest \
 tests.test_quarterly_income_archive \
 tests.test_quarterly_income_archive_postgres -v
```

真實 PostgreSQL 17 隔離整合測試必須證明：首筆新增成功、完全相同來源重跑零寫入、不同 EPS 來源內容只新增另一個永久版本、清單外股票拒絕、既存來源修訂不允許 UPDATE／DELETE，整個測試 schema 事務最後回滾，不在正式 Neon 寫入假測試公司。

**此流程正式驗收成功才可宣稱「取得最新一般產業季度 EPS 原始存證」；仍不代表所有 1,991 檔歷史財報完整、具備真的過去發布時間，或 AI 模型具有正 alpha。**
