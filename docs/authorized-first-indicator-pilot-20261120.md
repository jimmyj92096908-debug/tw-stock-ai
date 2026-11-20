# 一次性正式 Neon 補算驗收（2026-11-20 授權）

## 執行結果及退役紀錄

2026-11-20 的正式首批已完成，GitHub Actions
[首次真實補算 #44720719864](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/runs/44720719864)
狀態為 **completed / success**；證據 Artifact ID
`14621507426` 保存補算前、補算後及驗證結果。

相同日期再次查詢正式 Neon 已確認：

| 市場 | 待補前 | 待補後 | 已補齊前 | 已補齊後 |
| --- | ---: | ---: | ---: | ---: |
| TWSE | 1,044 | 1,042 | 41 | 43 |
| TPEx | 0 | 0 | 21 | 21 |

TWSE 另外有 942 → 940 檔技術及 SMC 均未開始。
日常自動補算仍由合併 PR #26 的
`daily-indicator-catchup.yml` 控制，每市場每次最多 20 檔。
**本次專用的一次性 GitHub 工作流程及其激活測試會在證據確認後刪除**，
避免後續意外重複啟動。歷史 GitHub 執行與提交紀錄保留。



本工作流程是**明確獲得使用者授權**後，對已啟用的每日補算功能進行一次性首批驗收。

## 操作契約

- 只在這份工作流程經過 PR 審查合併至 `main`，且 squash commit 的訊息包含唯一識別字串
  `ACTIVATE-ONE-TIME-20261120-STOCK-PILOT` 時執行正式寫入。
- 只允許 `github.run_attempt == 1`，避免普通重跑造成新的批次寫入。
- 這個一次性驗收**不設每日排程、也沒有 workflow_dispatch**；正常每日工作仍由已啟用的 `daily-indicator-catchup.yml` 處理。
- 與正式每日補算共用 GitHub `twstock-indicator-catchup` concurrency lock，防止兩個工作在同時間寫入。
- 首批每市場最多 **2 檔**（低於授權的每市場 20 檔上限）；仍需至少 60 筆真實收盤、最近 7 日有效行情及逐檔 PostgreSQL SAVEPOINT。
- 先執行唯讀預檢、無寫入候選預覽、受控補算，再執行唯讀後檢，將前後快照交由 `indicator_batch_reconcile.py` 核對。
- 只有「待補數實際下降、已補齊數同步增加、行情日期與候選總數一致」才可宣稱成功。每次 GitHub 執行的 Artifacts 留存 30 日。

## 安全界線

本次會在正式 Neon 寫入**調整行情、技術指標與 SMC**，但不變更官方原始行情、表結構、LINE 服務、LINE 憑證或自動交易功能。模型負樣本外績效的交易訊號安全閘門保持停用。

一次性驗收成功後，可依現有每日 03:10（Asia/Taipei）排程逐批擴充，且每次仍有 20 檔／市場上限。若首批未通過，必須先調查 GitHub 失敗步驟與 Neon 實際寫入證據，不得以測試綠燈或工作啟動假稱資料已補齊。
