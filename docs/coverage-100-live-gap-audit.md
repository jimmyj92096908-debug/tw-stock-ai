# 台股全市場「100%」缺口查核：唯讀、分母固定、不能偽造成功

`scripts/coverage_100_audit.py` 對 `stock_master` 每一筆股票主鍵
分類**一個主要阻礙**，同時記錄當日技術、SMC 與綜合評分旗標。

此報告的兩個百分率**不可混為一談**：

1. `currently_eligible_fraction`：
   價格有效、最後價格日距全市場最新有效價格日七天內、至少
   60 筆真正的有效交易日、非研究例外 1808 的股票中，
   **同股票同最後有效收盤日**有技術＋SMC＋有效綜合評分的比例。
2. `full_master_matched_composite_fraction`：
   上述符合完整條件的股票占全部 `stock_master` 清單的比例。
   缺行情、歷史不足、上市未滿 60 個交易日或行情過期均留在分母，
   不會偷偷刪掉以便宣稱「全市場 100%」。

分類：`NO_VERIFIED_PRICE`、`RESEARCH_EXCLUDED`、
`STALE_LAST_VALID_PRICE`、`LESS_THAN_60_VALID_SESSIONS`、
`MISSING_LATEST_TECHNICAL`、`MISSING_LATEST_SMC`、
`MISSING_LATEST_COMPOSITE`、`LATEST_RESEARCH_COHORT_COMPLETE`。

阻礙分類不是官方停牌或下市證明。例如只看到一筆成交行情，
只能說資料庫缺少歷史，**不能直接說交易所完全無歷史可提供**。
來源可取得性、交易資格及公司掛牌日期需另外核對。

## 使用方式

**離線：** 由已驗證、與 `AUDIT_SQL` 輸出欄位一致的本地 JSON
作分析，不需要任何 Neon 權限或運算：

```bash
python scripts/coverage_100_audit.py \
  --source-json verified-stock-audit-rows.json \
  --output coverage-100-audit.json
```

**人工啟動的即時唯讀查核**（不會進行任何價格或評分回補）：

```bash
STOCK_100_AUDIT_READONLY=yes DATABASE_URL='<existing-protected-url>' \
python scripts/coverage_100_audit.py \
  --read-neon --output coverage-100-audit.json
```

使用既有受保護資料庫連線，強制
`REPEATABLE READ READ ONLY`、`default_transaction_read_only=on`、
20 秒 SQL 逾時，最多 2,500 檔；不新增週期性工作、
不覆寫行情、不重算任何得分，也不透過 LINE 傳送。

本模組可供**受控上櫃歷史回補及目前 100% 合格股票批次**完成後，
用真實同一快照確認剩餘 9 檔完全缺價、低於 60 日的
上櫃股票，以及指標已完成但評分尚待重算的真正原因。
未驗證之資料來源及真正未來預測績效，仍必須標示未知。

## 測試

```bash
PYTHONPATH=src python -m unittest tests.test_coverage_100_audit -v
```

本功能採用本地合成資料驗證邏輯，測試本身不連任何正式資料庫。
