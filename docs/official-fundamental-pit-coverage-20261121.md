# 官方基本面可使用性（PIT）完整交集稽核

**已正式入庫的基本面原始資料不代表可拿來回測 2026-11-20 以前的交易決策。** 2026-11-21 才首次經官方 HTTPS 回覆取得的季度 EPS 與資產負債資料，只能出現在其後的研究訊號中。

本階段在既有正式 Neon **唯讀 REPEATABLE READ** 交易下，以同一個台灣收盤 `YYYY-MM-DD 13:30+08` 為截止時間，對三項真實來源分別取**當時已第一次觀測且季度／月份已結束**的最新歷史版本：
1. `official_quarterly_income_observations`：一般產業累計 EPS、淨利及真實首次觀測時間。
2. `official_balance_sheet_observations`：季度資產、負債、權益、流動資產／流動負債，並以 `accounting_identity_verified` 排除異常帳務比例。
3. `official_revenue_observations`：當月營收最新可見月份與首次觀測。

三個來源**各自**按 `first_observed_at <= 截止時刻` 篩選；跨資料表的季度損益與資產負債還必須是**同一個 period_end**，才算可比較。其後才針對**全部 `stock_master` 真實股票清單**，分別統計 TWSE 與 TPEx 的：
- 各個來源當時可用的真實股票數，以及三項來源同時已知的交集；
- 當時同季度且會計恆等式正確、同時有 EPS 和淨利的股票數；
- 若未來僅做探索性研究，存在正資產且完整分子的**負債／資產比率可計算**的股票數；
- 存在流動資產與正的流動負債、分母不為零的**流動比率可計算**股票數；
- 不通過會計恆等式的版本數及缺少流動負債分母的公司數。

**目前不計算 ROE**，因為 Q3 累計淨利除以單一季末權益不是可以直接驗證的全年 ROE；可靠 ROE 需要正確淨利期間、期初／期末平均權益以及當時已公告的完整連續來源。也不宣稱已有官方現金流量表、自由現金流或銀行／保險業完整口徑。

`scripts/audit_official_fundamentals_pit.py`：
- 預設以資料庫實際**最新真實有效收盤日**作為研究訊號日期；
- `--as-of 2026-11-20` 可審核歷史真正有價的交易日，拒絕不在當時行情中的星期六、假日、尚未收盤的未來日期；
- 所有時間由 PostgreSQL `clock_timestamp()` 和台北 `Asia/Taipei` 時區核對；
- 只用 `default_transaction_read_only=on` + `SET TRANSACTION ... READ ONLY`，25 秒 SQL timeout、六個安全綁定參數；
- 結果僅含各市場彙總數、分母及缺漏原因，不輸出個股選股名單／密碼、未啟用任何 LINE／交易，也不修改既有模型權重。

執行指令：
```bash
PYTHONPATH=src python -m unittest tests.test_official_fundamental_pit_coverage tests.test_official_fundamental_pit_postgres -v
DATABASE_URL='<existing-protected-readonly-url>' python scripts/audit_official_fundamentals_pit.py --as-of 2026-11-20 --out official-fundamental-pit-audit.json
```

Python 純單元測試會拒絕虛假分母、負數覆蓋、混入假日期與未來資訊。另以**隔離 PostgreSQL17** 真正建三來源財報表、公司主檔與來源版本，驗證舊交易日三來源可用數為 0、官方首度觀測後才可用、事後官方修正不得污染觀測前日期，最後完整 rollback。

此唯讀稽核亦已接到既有**每月同一 GitHub Action**官方來源存證流程，不新增付費工作排程；月營收、季度 EPS、資產負債三來源更新後，會自動留下當時市場訊號日的可用性報告。成功取得今天的資料，不得將研究池整體評分覆蓋率或 AI alpha 宣稱成 100%。
