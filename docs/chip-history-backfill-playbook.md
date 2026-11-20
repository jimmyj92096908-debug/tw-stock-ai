# 2330 籌碼歷史補齊：受控開發與驗收說明

## 問題定位（2026-11-20）

Neon 截至當次核對顯示：`2330` 三大法人及融資融券各只有 **1 個交易日**（2026-11-18），`daily_chip_scores` 最近 `2330` 2026-10-30 覆蓋率 0%，分數 NULL，且 `tdcc_share_distribution`、`insider_holdings` 對 2330 無資料。

這是資料覆蓋不足，不應偽造 0 分或宣稱股票轉弱。程式要求法人至少 20 個真實交易日、融資融券至少兩日、整體籌碼加權來源覆蓋達 50% 方可公開分數。法人權重 40%，融資融券 25%；兩者有效時權重合計 65%。

## 本 PR 完成

1. `2330` 加入 TWSE 法人及融資融券的日常追蹤，與 `6213,4919,7827` 及 TPEx `8937` 一起組成五檔追蹤清單。
2. 每日 `Daily Chip Data Accumulation` 只重新計算這五檔的籌碼分數，不會每次掃描整個股票母體造成 20 分鐘工作超時。計算門檻不降低，資料不足則繼續保留 NULL。
3. `src/chip_history_backfill.py`：只支援 TWSE 有指定日期的官方 T86 / MI_MARGN，根據實際已儲存的有效收盤價交易日制定缺漏清單，最多 30 個交易日。TPEx 最新快照不可當歷史資料使用。
4. **只讀預覽（預設）**：連接 Neon 只用 SELECT；不連網下載、不執行資料庫寫入、不改 LINE Webhook。
5. **兩道明確的回補門檻**：只有另行獲得使用者對正式歷史資料寫入的核准，才允許傳入 `--apply` 及環境變數 `CHIP_HISTORY_WRITE_ENABLED=yes`。在任何 DB INSERT 前，所有官方指定日期的來源必須預先下載、驗證並通過；遇既有主鍵只執行 `ON CONFLICT DO NOTHING`，不覆寫既有記錄。
6. GitHub Actions 防護：開發分支及程式碼 push 不可引起正式籌碼資料庫寫入；正式日排程與 main 上經操作人明確 dispatch 的流程才可寫入。新增程式未包含會自動發動回補的 workflow。

## 操作紀律

本次功能開發不等於使用者授權正式資料庫歷史回補。**禁止在沒有另外明確核准的情況下執行 `--apply`**。

唯一已準備好且不寫入的預覽指令（在已安全設定本地 `DATABASE_URL`、並安裝 `psycopg[binary]` 後）：

```powershell
python src/chip_history_backfill.py --stock 2330 --days 25
```

成功時會輸出 `mode: preview`、`actual_price_sessions`、`missing_institutional`、`missing_margin`，以及兩個 `inserted_*: 0`。不得把僅有收盤價或日後成功執行一次匯入解讀為籌碼分數已具備 20 日樣本。

## 上線驗收門檻

- `src/chip_history_backfill.py` 的全套 no-network 測試與 GitHub Python Tests 通過。
- 來源日期與指派交易日期一致；法人與融資均可解析 2330；缺資料不能補零。
- 正式回補若另獲核准，需確認逐交易日新增筆數、相同主鍵歷史價資料不變；不得根據 TPEx 最新快照回填過去日期。
- 重新計算後檢查 2330 籌碼表各分項 `component_status`；**20 天法人＋2 天融資**只有當兩因子通過最新時效與價格成交量檢查時，才可達 65% 籌碼來源覆蓋。若某來源不符，仍應顯示 NULL。
- 籌碼分數有效後，仍須再重新計算 `daily_composite_scores`，並核對 LINE 使用的是相同或合理時效的資料；不能把新籌碼日期直接貼上舊行情或舊技術指標。
- 此功能不含交易下單、LINE Token 變更、Webhook 切換或手動發送 LINE 訊息。


## 指定日期官方來源驗證（新增，不寫入）

增加第三種受控執行模式：`--verify-sources`。此模式讀取真實已存的股票價格交易日，依缺口向 TWSE T86（法人）與 TWSE MI_MARGN（融資融券）發送 GET 請求，只驗證官方日期、解析格式、2330 唯一紀錄與缺漏數量，**不呼叫 INSERT，不傳送 LINE**。

- 只有 `--stock 2330 --days 25`：純資料庫聚合預覽，不連外。
- 加 `--verify-sources`：只讀資料庫與官方 HTTP 來源，驗證尚未匯入的指定交易日；若任一日無法查證則失敗中止，不宣稱全部可回補。
- 加 `--apply`：另需正式寫入授權及 `CHIP_HISTORY_WRITE_ENABLED=yes`；在完整官方來源驗證成功後才採 `ON CONFLICT DO NOTHING` 寫入。
- `--verify-sources` 與 `--apply` **不得同時指定**，即使外部環境意外設定寫入開關，驗證模式仍不會寫入資料庫。

唯讀來源驗證指令：

```powershell
python src/chip_history_backfill.py --stock 2330 --days 25 --verify-sources
```

已核對 TWSE 2026-11-18、2026-11-19 兩個交易日的 T86 與 MI_MARGN 官方 JSON：均 HTTP 200、官方日期吻合，兩個來源每日期均可解析一筆 2330 有效資料。這是**四項指定日期來源檢查通過**，不是整批 25 日已驗證或正式回補已完成。整批驗證結果必須以專用 GitHub Actions 實際紀錄為準。
