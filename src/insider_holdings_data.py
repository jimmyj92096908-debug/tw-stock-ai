"""Import current official monthly director/supervisor holdings snapshots.

TWSE and TPEx endpoints are latest-snapshot feeds; they do not provide a
reliable historical backfill. Each row is retained by its reported as-of date.
"""
from __future__ import annotations
import hashlib, json, os, re
from datetime import date
from typing import Any

import psycopg
import requests

TWSE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap11_L"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap11_O"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TaiwanStockResearch/1.0)"}
STOCKS = {"twse": {"6213", "4919", "7827"}, "tpex": {"8937"}}


def key(value: Any) -> str:
    return re.sub(r"[\s　：:％%()（）_\-]", "", str(value or "")).lstrip("\ufeff").lower()


def number(value: Any) -> float | None:
    raw = str(value if value is not None else "").replace(",", "").replace("%", "").strip()
    if raw in ("", "-", "--", "—", "N/A", "無"):
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def as_date(value: Any) -> str | None:
    raw = str(value or "").strip()
    digits = re.sub(r"[^0-9]", "", raw)
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
    if len(digits) == 7:
        return f"{int(digits[:3]) + 1911}-{digits[3:5]}-{digits[5:]}"
    if len(digits) == 6:
        return f"{digits[:4]}-{digits[4:6]}-01"
    if len(digits) == 5:
        return f"{int(digits[:3]) + 1911}-{digits[3:5]}-01"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    return None

ALIASES = {
    "stock": ("公司代號", "證券代號", "股票代號", "代號", "公司代碼", "SecuritiesCompanyCode", "CompanyCode", "stock_id"),
    "date": ("資料年月", "資料日期", "年月", "日期", "年月日", "Date", "DataDate", "as_of_date"),
    "name": ("姓名", "董監事姓名", "姓名或法人名稱", "Name", "PersonName"),
    "role": ("職稱", "職稱名稱", "身分", "董監事職稱", "Title", "Position", "PersonPositionName"),
    "shares": ("持有股數", "持股數", "持股餘額", "持有股份", "目前持股", "持股股數", "HeldShares", "Shareholding"),
    "pledged": ("設質股數", "質押股數", "設質股份", "質權設定股數", "PledgedShares"),
    "percent": ("持股比例", "持股百分比", "持股比率", "持股比", "ShareholdingRatio", "SharePercent"),
}


def _select(columns: dict[str, str], field: str, required: bool = True):
    found = next((columns.get(key(alias)) for alias in ALIASES[field]
                  if columns.get(key(alias)) is not None), None)
    if required and found is None:
        raise RuntimeError(f"董監持股資料缺少欄位 {field}; 實際欄位={list(columns.values())}")
    return found


def parse_rows(rows: list[dict], market: str) -> list[dict]:
    if market not in ("twse", "tpex") or not isinstance(rows, list) or not rows:
        raise RuntimeError(f"{market} 官方董監持股回應為空或格式錯誤")
    columns = {key(k): k for row in rows if isinstance(row, dict) for k in row}
    selected = {f: _select(columns, f, f in ("stock", "date", "name", "role", "shares"))
                for f in ALIASES}
    output = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get(selected["stock"], "")).strip()
        if code not in STOCKS[market]:
            continue
        as_of = as_date(row.get(selected["date"]))
        name = str(row.get(selected["name"], "") or "").strip()
        role = str(row.get(selected["role"], "") or "").strip()
        shares = number(row.get(selected["shares"]))
        pledged = number(row.get(selected["pledged"])) if selected["pledged"] else None
        percent = number(row.get(selected["percent"])) if selected["percent"] else None
        if not as_of or not name or not role or shares is None or shares < 0:
            raise RuntimeError(f"{market} {code} 董監持股必要欄位缺漏或數值錯誤")
        if pledged is not None and (pledged < 0 or pledged > shares):
            raise RuntimeError(f"{market} {code} 設質股數超出持股數")
        if percent is not None and (percent < 0 or percent > 100):
            raise RuntimeError(f"{market} {code} 持股比例超出 0-100")
        output.append({
            "market": market, "stock_id": code, "as_of_date": as_of,
            "person_name": name, "person_role": role, "share_count": int(shares),
            "share_percent": percent, "pledged_shares": int(pledged) if pledged is not None else None,
            "record_key": hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")).hexdigest(),
        })
    if not output:
        raise RuntimeError(f"{market} 官方資料中找不到指定股票")
    dates = {r["as_of_date"] for r in output}
    if len(dates) != 1:
        raise RuntimeError(f"{market} 同批董監持股資料日期不一致：{sorted(dates)}")
    return output


def fetch_json(url: str) -> list[dict]:
    response = requests.get(url, headers={**HEADERS, "Accept": "application/json"}, timeout=(15, 90))
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for field in ("data", "result", "aaData"):
            if isinstance(payload.get(field), list):
                return payload[field]
    raise RuntimeError(f"官方 API 回應格式非預期：{url}")


def fetch_records() -> list[dict]:
    twse = parse_rows(fetch_json(TWSE_URL), "twse")
    tpex = parse_rows(fetch_json(TPEX_URL), "tpex")
    expected = {"6213", "4919", "7827", "8937"}
    present = {r["stock_id"] for r in twse + tpex}
    if present != expected:
        raise RuntimeError(f"董監持股目標股票不完整；缺少={sorted(expected-present)}")
    return twse + tpex


def save_records(records: list[dict]) -> int:
    from tdcc_data import normalize_database_url
    sql = """
      INSERT INTO insider_holdings
        (market, stock_id, as_of_date, person_name, person_role, record_key,
         share_count, share_percent, pledged_shares, source, retrieved_at)
      VALUES
        (%(market)s, %(stock_id)s, %(as_of_date)s, %(person_name)s, %(person_role)s, %(record_key)s,
         %(share_count)s, %(share_percent)s, %(pledged_shares)s, %(source)s, now())
      ON CONFLICT (market, stock_id, as_of_date, record_key)
      DO UPDATE SET person_name=EXCLUDED.person_name, person_role=EXCLUDED.person_role,
        share_count=EXCLUDED.share_count, share_percent=EXCLUDED.share_percent,
        pledged_shares=EXCLUDED.pledged_shares, source=EXCLUDED.source, retrieved_at=now()
    """
    for row in records:
        row["source"] = "TWSE_t187ap11_L" if row["market"] == "twse" else "TPEX_mopsfin_t187ap11_O"
    with psycopg.connect(normalize_database_url(os.environ["DATABASE_URL"])) as conn:
        with conn.cursor() as cur:
            # Add a stable source-row key and migrate the old person/role primary key.
            cur.execute("ALTER TABLE insider_holdings ADD COLUMN IF NOT EXISTS record_key TEXT")
            cur.execute("""
              UPDATE insider_holdings
              SET record_key = md5(concat_ws('|', market, stock_id, as_of_date::text,
                  person_name, person_role, share_count::text,
                  coalesce(share_percent::text, ''), coalesce(pledged_shares::text, ''), source))
              WHERE record_key IS NULL
            """)
            cur.execute("ALTER TABLE insider_holdings ALTER COLUMN record_key SET NOT NULL")
            cur.execute("""
              DO $$
              DECLARE old_pk TEXT;
              BEGIN
                SELECT conname INTO old_pk
                FROM pg_constraint
                WHERE conrelid = 'insider_holdings'::regclass AND contype = 'p'
                  AND pg_get_constraintdef(oid) NOT LIKE '%record_key%';
                IF old_pk IS NOT NULL THEN
                  EXECUTE format('ALTER TABLE insider_holdings DROP CONSTRAINT %I', old_pk);
                END IF;
                IF NOT EXISTS (
                  SELECT 1 FROM pg_constraint
                  WHERE conrelid = 'insider_holdings'::regclass AND contype = 'p'
                    AND pg_get_constraintdef(oid) LIKE '%record_key%'
                ) THEN
                  ALTER TABLE insider_holdings
                    ADD CONSTRAINT insider_holdings_pkey
                    PRIMARY KEY (market, stock_id, as_of_date, record_key);
                END IF;
              END $$;
            """)
            # Replace only the dates being refreshed; transaction rollback protects prior data.
            for market, code, as_of in sorted({
                (r["market"], r["stock_id"], r["as_of_date"]) for r in records
            }):
                cur.execute(
                    "DELETE FROM insider_holdings WHERE market=%s AND stock_id=%s AND as_of_date=%s",
                    (market, code, as_of),
                )
            cur.executemany(sql, records)
    return len(records)


def main():
    records = fetch_records()
    count = save_records(records)
    print(f"董監持股成功寫入 {count} 筆；資料月份 {records[0]['as_of_date']}")
    for market, codes in STOCKS.items():
        for code in sorted(codes):
            subset = [r for r in records if r["market"] == market and r["stock_id"] == code]
            total = sum(r["share_count"] for r in subset)
            pledged = sum(r["pledged_shares"] or 0 for r in subset)
            print(market, code, "人員筆數", len(subset), "持股合計", total, "設質合計", pledged)


if __name__ == "__main__":
    import psycopg
    main()
