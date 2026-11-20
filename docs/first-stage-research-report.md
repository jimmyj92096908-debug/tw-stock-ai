# 第一階段：可使用的唯讀研究分析報告

目標：使用已訓練的研究模型、現有 Neon 資料與原本的資料品質稽核，產生**真正可閱讀的 HTML、Markdown 與 JSON**。本功能不是下單系統，不會發 LINE 買賣訊號；原本 LINE Webhook Deployment 4 保持不變。

## 在 GitHub 操作

開啟 [First-Stage Research Report (Read-Only)](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/workflows/first-stage-report.yml)，選擇主分支 `main`，按 **Run workflow**。工作流程也預定每週二至週六台灣時間 04:45 執行，使用**現有** GitHub Actions 受保護的 `DATABASE_URL`。

此外，已授權的正式市場行情或技術／SMC 排程成功後，會自動重算綜合評分；**只有該自動綜合評分工作流程成功時**，研究報告也會接著唯讀重新產生一次。它仍保留原有週二至週六台灣時間 04:45 的獨立排程，作為前段排程延遲或事件沒有觸發時的補充；兩種研究報告執行均不寫入 Neon。這段串接不會在綜合評分工作失敗、手動評分、PR 或其他不可信來源成功時自動出版報告。

工作流程先跑獨立格式檢查及完整 Python 測試，通過後才會：唯讀查詢行情健康度、用已保存的模型係數重新排名、組合報告、上傳 **twstock-first-stage-research-report**。打開該次執行紀錄，在 Artifacts 點報告壓縮檔，解壓縮後用瀏覽器開啟 `research-report.html`；`research-report.md` 同時顯示在 Actions 的 Summary，`research-report.json` 可供程式讀取。

工作流程不需要 LINE 密碼、LINE 使用者 ID 或新 Webhook；不修改任何 Neon 資料表，SQL 使用 `SET TRANSACTION READ ONLY`。如資料庫密碼不存在、資料日期不一致或模型風險閘門不符，執行會失敗並留下明確原因，**不發布假報告**。

## 純本地執行

設定最小權限的唯讀 `DATABASE_URL`（不得加入 GitHub 程式碼或文件），執行：

```sh
python -m pip install -r requirements.txt
mkdir -p first-stage-output
python src/stock_db_audit.py --json > first-stage-output/audit.json
python scripts/trained_factor_pipeline.py rank --model-in models/tw-factor-ridge-1-research.json --limit 10 --output first-stage-output/ranking.json
python scripts/render_first_stage_report.py --audit first-stage-output/audit.json --ranking first-stage-output/ranking.json --evaluation models/tw-factor-ridge-1-evaluation.json --outdir first-stage-output
```

僅輸出公開市場的歷史研究排名。輸出的 `abstain=true`、`live_trading_approved=false` 與負樣本外績效不可移除或誤標成買賣建議。模型不保證獲利；不同日的行情、評分也不能混用。

## 正式驗收證明（隨每次研究報告提供）

每次正式研究報告都會在產生 HTML、Markdown、JSON 後，再執行獨立的
`scripts/first_stage_acceptance.py`。它只讀取剛產生的研究報告 JSON，
逐項核對：有價股票、已計算技術與 SMC、有效綜合評分、同日研究排名、
台灣上市／上櫃補算數量、資料品質異常為零、研究模型樣本外評估與
`abstain=true`、`live_trading_approved=false`。

只有全部一致，才會輸出 `first-stage-acceptance.json` 和
`first-stage-acceptance.md`，隨研究 HTML／MD／JSON 一起上傳。
若異常、資料日期不一致、模型交易閘門意外打開或研究排名為空，
整次報告工作會失敗，不產生「已驗收成功」的虛假檔案。

`core_research_mvp_accepted=true` **僅表示原定義的第一階段唯讀研究 MVP
已符合條件**，不表示 1,991 檔全數完成技術指標、不表示定期排程已達
長期穩定性要求，也不代表 LINE 新版 Webhook 通過官方簽章或真實訊息
E2E。這些範圍需各自以後續真實事件驗證。研究模型樣本外五日平均
超額報酬目前為負，交易功能繼續停用。

## 哪些屬第一階段，哪些仍是後續？

第一階段已具備：真實價格與綜合評分查詢、固定已訓練模型權重、歷史研究排名、資料覆蓋率健康度、可下載的人類閱讀報告、離線回歸測試。**仍不包括**新的 LINE Webhook 正式接管、每日 LINE 模型推播、真實交易、已通過績效驗證的交易訊號或 1,991 檔全部完成技術分析。

新版 LINE 查詢要等官方憑證、簽章、真實測試帳號與原服務回退演練通過，才可以另行啟用。請勿將此報告的成功當作 LINE 正式上線證據。
