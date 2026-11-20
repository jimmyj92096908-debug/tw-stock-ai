# 2026-11-20 第三批：正式台股技術／SMC 補算與研究評分

## 正式資料庫已驗證的成果

- 已獲使用者授權在既有 20 檔／市場／批的上限內持續補算
- 第三批主分支工作：[GitHub Actions #44728697062](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/runs/44728697062)
- TWSE 符合至少 60 日有效行情且最近 7 日內有行情：**1,085 檔**
- TWSE 技術與 SMC 完整覆蓋：**63 → 83 檔**
- TWSE 尚待補算：**1,022 → 1,002 檔**
- TWSE 技術與 SMC 均完全未開始：**920 → 900 檔**
- TPEx：21 檔符合資格且已補齊，待補 0 檔
- 以上數字由 Neon 的獨立唯讀 SQL 驗證，與 GitHub 的補算前後核對結果相符

## 綜合評分接續

使用原有的 `scripts/score_after_refresh.py` 處理已補齊的股票，
並由 `scripts/indicator_score_followthrough.py` 比較正式 Neon
的兩次唯讀覆蓋率稽核。若最新有效評分沒有增加，工作會失敗而不會
宣稱整個分析鏈完成。

> 此段的正式評分結果以
> [第三批 GitHub Actions #44728697062](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/runs/44728697062)
> 的最終執行結論及獨立 Neon SQL 為準；不能僅因技術指標成功寫入就宣稱評分完成。

## 排程及風險界線

此次暫時的單次 push 觸發工作及其專用測試於驗收後退役，
正常的 `daily-indicator-catchup.yml`、綜合評分與唯讀研究報告排程
繼續保留。

本次僅更新調整行情、技術指標、SMC 與後續研究綜合評分；
不修改官方原始收盤行情、不切換正式 LINE Webhook、
不啟動 AI 交易訊號或自動下單。研究模型樣本外績效仍未通過驗收。
