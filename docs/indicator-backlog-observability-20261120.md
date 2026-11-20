# 技術／SMC 補算進度：每日真實資料稽核

## 目的

每日的研究分析報告與資料品質監控會從 Neon 執行純唯讀 SQL，查詢**真正符合補算資格**的台股。不要把「有行情 98.84%」誤稱為「已有完整 AI／SMC 分析 98.84%」。

## 跟既有補算流程一致的定義

對每個 `(market,stock_id)`：

1. 排除既定禁止補算的代碼 `1808`。
2. 必須有至少 **60 筆非 NULL 收盤行情**，且最後收盤日期距離全資料庫最新有價日期 **7 天內**。
3. 當技術指標筆數或 SMC 筆數**少於**符合條件的歷史收盤筆數，就算「待補」。
4. 兩者均已至少覆蓋歷史筆數，才算「已補齊」。兩者均為零則另外標示「未開始」。

這是**資料覆蓋檢查**，不代表所有技術指標數值都達到完整 120／240 日的觀察窗；也不代表綜合評分已重新計算。

## 2026-11-20 正式 Neon 唯讀基準值

| 市場 | 符合 60 日且近期行情 | 待補 | 補齊 | 技術／SMC 都尚未開始 |
| --- | ---: | ---: | ---: | ---: |
| TWSE 上市 | 1,085 | 1,044 | 41 | 942 |
| TPEx 上櫃 | 21 | 0 | 21 | 0 |
| 合計 | 1,106 | 1,044 | 62 | 942 |

每日受控補算最高 20 檔／市場，若每次成功處理 20 檔上市股且沒有新增待補，數學上**至少需要 53 次成功批次**。這不是 53 個工作天的承諾；失敗、假日、歷史回補、新增股與排程是否執行均會改變結果。

## 檢查結果位置

- [First-Stage Research Report (Read-Only)](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/workflows/first-stage-report.yml)：輸出 HTML、Markdown、JSON 的分析覆蓋與模型研究排名，未通過績效驗收時繼續停用交易訊號。
- [TW Stock Data Quality Monitor (Read-Only)](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/workflows/twstock-data-quality-monitor.yml)：檢視每日 Summary 內的上市、上櫃待補股數和總計，取得當次 Aggregate-only JSON。
- 行情、技術與評分的最新日期必須分開顯示。若待補股數沒有下降，應檢查歷史回補與指標工作流程的**實際 GitHub execution logs**；不能把測試成功認作資料庫已完成。

此變更只加 SQL SELECT、格式化和測試。它**不會自動啟用**額外補算排程、直接寫入 Neon、發送 LINE 或改動正式 Webhook。正式資料更新需繼續受原本的寫入授權、批次上限與 PostgreSQL savepoint 保護。
