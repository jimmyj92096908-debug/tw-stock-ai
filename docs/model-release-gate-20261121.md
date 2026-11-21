# AI 模型研究／上線驗收閘門：2026-11-21

**模型程式、行情庫與合格股票池已可提供研究分數，不代表已經得到可可靠交易的 AI 訊號。**

原保存的 `models/tw-factor-ridge-1-evaluation.json`：
- 開發樣本共 57 個日期，研究訊號較正面；真正保留期有 **21 個日期、346 個股票觀察**；
- 模型在保存的 holdout 平均淨報酬 **-3.401558%**；
- 對相同期等權研究基準平均淨超額 **-2.114523 個百分點**；
- holdout 早已在模型設計中被查看過，故**不能視為全新獨立樣本外資料**；
- 研究門檻 `holdout_research_gate_passed=false`，交易 `live_trading_approved=false`，LINE 投資訊號 `line_signal_delivery_approved=false`。

另一個實際 Neon 的歷史成熟標籤稽核：2026-07-06 至 10-30
有 79 個保存評分訊號日，只有 9 個同日完整可比較持有期間，
去除重疊後僅 **4 個獨立研究窗口**（最低探索門檻 10 個）。
不能假造已到期報酬，也不能把今天才取得的官方基本面資料
倒填為過去已知。

`src/model_release_acceptance.py` + `scripts/research_model_release_audit.py`
提供**不連資料庫、不改模型的驗收產物**：
- 讀取目前已儲存的模型與基準數值、holdout 樣本及證據 SHA256。
- 負或零淨超額、已檢視過的 holdout、缺少新未見過的真實資料、
  不足 10 個不重疊時間窗口、公司行動當時版本未知、存活偏差
  未審查、成本和流動性壓力測試不足，一律標示阻擋原因。
- 必須額外具有事前封存、獨立核對、非重疊及真實成本壓力驗證的
  **新未見過研究期間**，才能進入*人工研究審查*。
- 即使將來上述條件全部提交，程式仍永遠輸出
  `live_trading_approved=false` 及
  `line_signal_delivery_approved=false`。不能讓 CLI、CI
  自行啟用交易或變更 LINE 訊號權限。
- 新 `.github/workflows/model-release-offline-guard.yml`
  只在相關程式／模型被修改的 push／PR 或手動執行
  **離線驗收**；沒有新的定期付費任務、Neon 連線或下單。

執行方式：

```bash
python scripts/research_model_release_audit.py --out research-release-status.json
PYTHONPATH=src python -m unittest tests.test_model_release_acceptance -v
```

預期正式結果 `decision=BLOCKED`，原因包含
`NEGATIVE_OR_ZERO_SAVED_NET_EXCESS`、
`EXAMINED_HOLDOUT_NOT_INDEPENDENT` 與
`NEW_UNSEEN_FUTURE_HOLDOUT_REQUIRED`。

如果交易所最新行情新增的只有近幾週真實資料，
**不能縮短持有期、放寬最低觀察窗口、挑出有正績效的個股**
來宣稱驗收通過。下階段正確做法是持續保存新實際行情、
當時的特徵與首次觀測的公開資料版本，當未來日期自然成熟後
以已凍結的模型做新預先規劃的樣本外評估。
