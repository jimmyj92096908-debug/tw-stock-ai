# 首次技術指標至綜合評分串接驗收 — 2026-11-20

這是一次性正式 Neon 操作的執行紀錄，**不是股票交易建議**。

## 已由 GitHub Actions 與獨立 Neon 唯讀 SQL 驗證

- 指標補算：[PR #28](https://github.com/jimmyj92096908-debug/tw-stock-ai/pull/28)
  的 [Actions #44720719864](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/runs/44720719864)
  已成功。TWSE 技術及 SMC 完整覆蓋由 41 增至 43 檔，待補由 1,044 降至
  **1,042**，另有 940 檔技術／SMC 兩類均未開始。上櫃 21 檔已完成。
- 評分接續：[PR #30](https://github.com/jimmyj92096908-debug/tw-stock-ai/pull/30)
  的 [Actions #44722651205](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/runs/44722651205)
  狀態為 `success`，既有 `scripts/score_after_refresh.py`
  **處理 166 檔候選股票**；兩檔新補算股票 1626 與 1702 的當日綜合評分
  從 0/2 變為 2/2。
- 正式 Neon 2026-11-19 同日獨立唯讀檢查：

  | 代碼 | 最新有效綜合評分 | 覆蓋權重 |
  | --- | ---: | ---: |
  | 1626 | 21.56 | 0.60 |
  | 1702 | 28.44 | 0.60 |

- 全資料庫有效綜合評分股票由 **164 增加至 166 檔**。在最新有效評分日
  能匹配同日正收盤價、模型覆蓋權重 0.50～1.00，且不含排除代碼
  1808 的研究股票從先前 153 檔增加到 **155 檔**。
  不可把 166 檔評分總數直接稱為 155 檔研究股票，或反之。

## 後續正式流程

`daily-indicator-catchup.yml` 已核准並保留主分支的台灣時間
週二至週六 03:10 排程，最多 20 檔／市場／批，逐檔 SAVEPOINT，
前後 READ ONLY 證據，無有效進展即阻止評分重算。

`composite-after-market-refresh.yml` 只在成功的正式 scheduled
指標補算或其他已授權官方來源快照後自動執行評分。
一次性補算與評分驗收都成功，但**首次正式 03:10 例行排程仍待
下一次 GitHub `schedule` 事件確認**。

這次使用的唯一觸發字串 workflow 已在完成後移除，以避免往後
重複啟動。歷史 GitHub Actions 執行紀錄與證據檔保留。

原有 LINE Webhook 未切換；AI 統計研究模型在樣本外績效仍不通過，
**交易訊號及自動下單維持停用**。
