# 台股 AI 投資分析模型：可執行完整研究流程（2026-11-21）

## 研究系統完成的範圍

本專案已具備 **官方行情入庫 → 調整行情／技術指標 → SMC → 法人與融資融券籌碼 → 3 因子綜合評分 → 真實已訓練 ridge 排名 → 研究績效稽核 → 只讀研究輸出** 的程式流程。這代表**研究系統可以完整執行與驗證**，不是宣稱模型已能穩定獲利、更不是交易系統已可正式發單。

最新統一入口為：

- `src/investment_model_bundle.py`：核對已保存訓練模型及驗證報告、資料時間戳、獨立籌碼分數與歷史綜合評分的差異，使用固定特徵架構安全產生研究排名，任何失敗都不能開啟 LINE 交易訊號或下單。
- `scripts/investment_model_pipeline.py`：完全離線的模型稽核（預設），以及需明確啟用的 Neon 唯讀研究快照。
- `tests/test_investment_model_bundle.py`：測試訓練模型績效不通過、舊分數不可套新籌碼、同日價格、七天時效、模型係數篡改、單一 MVCC 一致性快照和不能發訊號。
- `.github/workflows/investment-model-complete.yml`：**不需要任何 Neon 或 LINE Secrets** 的可重現模型驗收，包括真實已保存的失敗績效門檻。
- 既有 `src/trained_factor_model.py` 與 `scripts/trained_factor_pipeline.py`：只使用開發期標籤估計固定 ridge 係數，利用時間隔離觀察保留期績效；`research_rank` 只能輸出 **`abstain=true`** 的歷史研究排名。
- 既有 `src/composite_score.py`（技術 35%、SMC 25%、籌碼 40%）及 `src/chip_score.py`（法人 40%、融資融券 25%、TDCC 25%、內部人 10%），兩者都有有效來源覆蓋率條件。模型研究排名不應直接等同於股價預測機率。

## 指令範例

Windows PowerShell 的執行方式：

```powershell
# 專案根目錄。此命令完全離線、不需要正式資料庫或 LINE
python scripts/investment_model_pipeline.py --output research-model-status.json

# 如需在已核准且受保護的執行環境執行正式唯讀驗收：
# 1) 設定 DATABASE_URL 到安全取得的 PostgreSQL 連線字串（切勿放進 Git）
# 2) 明確設定 INVESTMENT_MODEL_READONLY=yes
# 3) 將結果儲存本地檔案，不發送 LINE
$env:INVESTMENT_MODEL_READONLY = 'yes'
python scripts/investment_model_pipeline.py --live-readonly --market twse --stock-id 2330 --limit 10 --output research-model-live.json
```

Linux／GitHub Actions 使用方式相同，僅需以 shell 環境變數設定。

**兩種執行模式的差異**：

- 預設 `offline` 只讀取 Repo 已保存的公開模型 JSON：明確標示 `offline_stock_data_is_not_live=true`，**不會編造最新股票價格或當日排名**。
- `--live-readonly` 需有 `INVESTMENT_MODEL_READONLY=yes` 及 DATABASE_URL，會於單一 PostgreSQL `REPEATABLE READ, READ ONLY` 交易中執行原有的同日 `LATEST_MODEL_SQL` 和公開股票資料狀態查詢。連線帶 `default_transaction_read_only=on`，資料庫伺服器拒絕寫入，**不查詢 `line_messages`、不匯出使用者資訊、不更新任何分析表**。
- 即使最新綜合評分日比行情日舊，仍只能標示為歷史研究排名，不能說是當日即時選股；`ranking_matches_reference_price_date` 只表示**排名日期與查詢個股的行情日是否相同**，不是該個股已被納入當日排名。請另外檢查 `reference_stock_in_rank_cohort`。
- 另計算該排名日期實際有有效價格的股票數（`ranked_date_priced_universe`）與已完成同日綜合評分且符合研究模型門檻的股票數（`ranking.eligible_universe`）。如果少於 **30 檔**或不足同日有效行情股票的 **20%**，輸出 `ranking_sample_status=THIN_OR_UNKNOWN_RANKING_COHORT`；這是避免小樣本冒充全市場的**描述性資料覆蓋警示**，不是模型績效門檻，也不能取代樣本外驗證。
- 獨立籌碼評分僅在來源覆蓋至少 50%、不晚於參考行情日且距行情日不超過七個日曆天時展示。若獨立籌碼評分日比綜合評分新，會明示 `new_chip_not_in_older_composite=true`，**絕不將 11/20 的 2330 籌碼分數併入 11/19 的舊綜合評分**。

## 已證實的真實模型限制：不是「通過」的投資訊號

保存於 `models/tw-factor-ridge-1-evaluation.json` 的既有證據：

| 指標 | 已保存數值 |
| --- | ---: |
| 開發期觀察日 | 57 |
| 開發期股票 | 1,083 |
| 已檢視的樣本外觀察日 | 21 |
| 樣本外股票 | 346 |
| 樣本外平均模型淨超額表現 | **-0.02114523**（約 -2.11 個百分點） |
| 當時樣本外同日正超額比例 | 0.285714 |
| `holdout_research_gate_passed` | `false` |
| `holdout_is_pristine_independent_validation` | `false` |

真實已保存模型的 `development_sha256` 為 NULL；雖有 `training-sufficient-stats.json` 可以重建係數，**不能冒充已保存完整原始訓練資料列指紋**。本統一驗收會如實標示 `no_development_row_fingerprint`。原本樣本外區間已在模型設計時被檢視，**不能再重新調參、用同一樣本外區間稱為新的獨立驗證**。

因此即使程式完整、CI 通過，系統仍固定輸出：

- `overall_status=RESEARCH_ONLY_EVIDENCE_BLOCKED`
- `abstain_from_trading=true`
- `publish_line_trade_signal=false`
- `orders_enabled=false`

若未來取得足夠**未曾使用過的新時間區間資料**，仍須另行設計不可回頭調整的前瞻驗證方案與模型治理；不能以本輪程式測試取代真實獨立績效證明。

## 2330 的資料時間差（以 2026-11-21 查核為例）

- 正式行情 2026-11-20。
- 技術指標及綜合評分最新仍 2026-11-19。
- 獨立籌碼分數 2026-11-20：**40.65/100**、來源覆蓋 **65%**。法人 29.05、融資融券 59.21；TDCC／內部人暫無資料。來源不足的因子保持缺值、不補 0。
- 新版 LINE 查詢程式尚**未啟用**：`line_stock_reader` 正式角色對七個新籌碼欄位仍無 SELECT 權限，官方 Webhook 尚指向舊版。此文件不代表已獲 GRANT、重算 2330 綜合評分、部署 Neon Function 或 LINE 切換授權。

## 剩餘工作與責任邊界

研究模型可完成編碼、測試與唯讀驗收；**不能捏造**尚未發生的未來驗證資料或正向樣本外績效。若要將研究結果進一步變為真正會發送 LINE 交易提示或執行交易的服務，仍需另行完成新的外部樣本、費用／滑價與交易限制核對、正式發布核准。正式 Neon 指標／綜合評分寫入、資料權限 GRANT、LINE Function 部署與 Webhook 切換均不在此 PR 操作範圍。

相關文件：[已訓練模型](trained-factor-model.md) · [LINE 上線門檻](line-production-readiness-20261120.md) · [最小讀取權限](line-chip-reader-grant-runbook.md)。


## 實際 Neon 端到端唯讀實測（2026-11-21）

[一次性真實研究模型驗收 #44797342734](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/runs/44797342734) 成功，且輸出 [JSON 研究報告 Artifact](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/runs/44797342734/artifacts/14658653878)。當時 2330 行情／獨立籌碼日期為 **2026-11-20**，籌碼分數 **40.65**、覆蓋 **65%**；技術與綜合評分仍是 **2026-11-19**。

最新全市場研究排名的來源分數日期為 **2026-11-20**，但當時僅 **7 檔**股票符合當日研究模型排名資格；這不能被當成整個上市／上櫃市場的有效完整排名，亦不能由此推導 2330 已取得 11/20 的綜合評分。因此在完成正式資料日與市場覆蓋率修補以前，先將排名標記為**稀疏樣本**，繼續 `abstain=true`。一次性驗收的程式不會保留在主分支；未來如需重新執行可以使用手動 `Generate Investment Research Model Report (Read Only)` 工作流程，無自動推播。
