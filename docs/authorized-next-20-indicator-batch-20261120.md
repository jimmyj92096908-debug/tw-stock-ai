# 2026-11-20：已授權下一批上市股票補算與綜合評分銜接

## 正式 Neon 第二批已完成（可重現驗收）

[GitHub Actions #44725314839](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/runs/44725314839)
已於 2026-11-20 完整執行，結論為 **completed / success**。
[Artifact #14624500622](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/runs/44725314839/artifacts/14624500622)
保存指標補算前後、評分重算前後及兩項驗證結果。

GitHub 及另外執行的 Neon 唯讀 SELECT 均確認：

| 項目 | 第二批之前 | 第二批之後 | 變化 |
| --- | ---: | ---: | ---: |
| 上市符合資格 | 1,085 | 1,085 | 0 |
| 上市技術／SMC 已補齊 | 43 | **63** | +20 |
| 上市技術／SMC 待補算 | 1,042 | **1,022** | -20 |
| 上市技術／SMC 都尚未開始 | 940 | **920** | -20 |
| 上櫃已補齊 | 21 | 21 | 0 |
| 全資料庫有效綜合評分股票 | 166 | **186** | +20 |
| 最新有價日、研究基本資料條件合格 | 155 | **175** | +20 |

最新收盤與綜合評分日期都是 **2026-11-19**。
股價行情沒有被本次補算改寫；評分只是歷史研究資料，不是經驗證的可交易訊號。
本批次的可重用唯讀評分銜接檢查器與測試保留在
`scripts/indicator_score_followthrough.py`、
`tests/test_indicator_score_followthrough.py`。

本次單次啟動的 GitHub workflow 與其啟動專屬測試已退役，
但正式 `daily-indicator-catchup.yml` （03:10，Tue–Sat）
與 `composite-after-market-refresh.yml` 保留，
其第一次**真正由 `schedule` 事件啟動**仍需觀察，不能以這次
人工授權的一次性 GitHub push 成功當成已驗證每日自動可靠度。


## 目標

首次正式小批次已由 Neon 確認：TWSE 技術／SMC 完整覆蓋 41→43，待補 1,044→1,042；其後綜合評分 164→166，有效研究排序最新日 153→155。

這次後續操作在已授權的範圍內，把**單批上限 20 檔／市場**送到 Neon，並核對調整行情 → 技術／SMC → 綜合評分全流程，不能以程式執行成功代替資料庫的真實進展。

## 安全約束

- 這是只觸發一次的 GitHub Actions 工作，只有包含唯一識別字串
  `ACTIVATE-ONCE-20261120-NEXT20-INDICATOR` 的主分支 squash merge 首次執行可以寫入；PR 不觸發寫入，GitHub rerun_attempt 大於 1 也不能寫入。
- 和正常每日 `Verified History Indicator Catch-Up` 使用同一把 concurrency 鎖，防止兩批同時寫入。
- 每個市場每批最多 20 檔，仍要求至少 60 日真實收盤、近期行情、排除 1808。每檔使用 SAVEPOINT；失敗的單檔回滾。
- 指標正式寫入前及後以 `REPEATABLE READ READ ONLY` 做總量及候選核對；只有待補下降、已補齊同步上升，才可進入綜合評分。
- 使用現有 `scripts/score_after_refresh.py` 重算符合條件的研究分數，前後透過唯讀稽核確認最新評分日與最新行情一致，且有效評分覆蓋度提升。
- GitHub Artifacts 保留完整的指標及評分前後 JSON 30 天；任何失敗須保留失敗證據，不能宣稱全部成功。
- **不改原始官方行情、不更動 LINE Webhook、不啟動交易訊號或下單。**

## 驗收與清理

GitHub PR 的 Python 測試須全部成功才能合併。合併後確認正式 Actions 執行結果為成功，並再次用獨立 Neon 唯讀 SELECT 核對待補股數、有效評分與最新日期。

本次專用工作流程在成功驗收後即予移除，保留原本週二至週六台灣時間 03:10 的正式受控自動排程。正式每日排程首次 `schedule` 執行仍必須另行確認，不能把此次一次性寫入當成無人值守排程驗證。
