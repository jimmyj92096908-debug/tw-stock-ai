"""Build transparent, freshness-aware composite chip scores for every stock in stock_master."""
from __future__ import annotations

import json
import os
from datetime import date
from typing import Any

import psycopg

WEIGHTS = {"institutional": 0.40, "margin": 0.25, "tdcc": 0.25, "insider": 0.10}


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def weighted_score(components: dict[str, float | None]) -> tuple[float | None, float]:
    available = {name: value for name, value in components.items()
                 if name in WEIGHTS and value is not None}
    if not available:
        return None, 0.0
    weight_sum = sum(WEIGHTS[name] for name in available)
    score = sum(WEIGHTS[name] * float(value) for name, value in available.items()) / weight_sum
    return round(clamp(score), 2), round(weight_sum, 2)


def _latest_price_date(cur, market: str, stock_id: str):
    cur.execute(
        "SELECT MAX(trade_date) FROM daily_prices WHERE market=%s AND stock_id=%s",
        (market, stock_id),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _institutional(cur, market: str, stock_id: str, ref_date: date):
    cur.execute("""
      WITH p AS (
        SELECT trade_date, volume FROM daily_prices
        WHERE market=%s AND stock_id=%s AND trade_date<=%s
        ORDER BY trade_date DESC LIMIT 20
      ), f AS (
        SELECT trade_date, foreign_net, trust_net, dealer_net, total_net
        FROM institutional_flows
        WHERE market=%s AND stock_id=%s AND trade_date<=%s
        ORDER BY trade_date DESC LIMIT 20
      )
      SELECT (SELECT COUNT(*) FROM f),
             (SELECT COALESCE(SUM(total_net),0) FROM (SELECT total_net FROM f ORDER BY trade_date DESC LIMIT 5) x),
             (SELECT COALESCE(SUM(total_net),0) FROM f),
             (SELECT COALESCE(SUM(volume),0) FROM (SELECT volume FROM p ORDER BY trade_date DESC LIMIT 5) x),
             (SELECT COALESCE(SUM(volume),0) FROM p),
             (SELECT MAX(trade_date) FROM f)
    """, (market, stock_id, ref_date, market, stock_id, ref_date))
    count, net5, net20, vol5, vol20, latest = cur.fetchone()
    if not count or not vol5 or not vol20 or latest is None:
        return None, {"status": "MISSING", "latest_date": str(latest) if latest else None}
    age = (ref_date - latest).days
    if age > 7:
        return None, {"status": "STALE", "latest_date": str(latest), "age_days": age}
    ratio5 = float(net5) / float(vol5)
    ratio20 = float(net20) / float(vol20)
    # Positive net buying scores above 50; selling scores below 50.
    score = clamp(50 + (ratio5 * 250 + ratio20 * 150) / 2)
    return round(score, 2), {"status": "AVAILABLE", "latest_date": str(latest),
                              "net_buy_5d": int(net5), "net_buy_20d": int(net20),
                              "net_volume_ratio_5d": round(ratio5, 5)}


def _margin(cur, market: str, stock_id: str, ref_date: date):
    cur.execute("""
      SELECT trade_date, margin_balance, short_balance
      FROM margin_short WHERE market=%s AND stock_id=%s AND trade_date<=%s
      ORDER BY trade_date DESC LIMIT 6
    """, (market, stock_id, ref_date))
    rows = cur.fetchall()
    if not rows:
        return None, {"status": "NOT_APPLICABLE" if stock_id == "7827" and market == "twse"
                      else "MISSING", "latest_date": None}
    latest_date, latest_margin, latest_short = rows[0]
    age = (ref_date - latest_date).days
    if age > 7:
        return None, {"status": "STALE", "latest_date": str(latest_date), "age_days": age}
    if len(rows) < 2:
        return None, {"status": "INSUFFICIENT_HISTORY", "latest_date": str(latest_date)}
    previous_date, previous_margin, previous_short = rows[1]
    if previous_margin is None or previous_margin == 0 or latest_margin is None:
        return None, {"status": "MISSING", "latest_date": str(latest_date)}
    change = (float(latest_margin) - float(previous_margin)) / abs(float(previous_margin))
    # Rapid margin expansion is treated as a risk increase, not as a trading signal.
    score = clamp(50 - change * 100)
    return round(score, 2), {"status": "AVAILABLE", "latest_date": str(latest_date),
                              "margin_balance": int(latest_margin),
                              "margin_change_ratio": round(change, 5),
                              "short_balance": int(latest_short or 0)}


def _tdcc(cur, market: str, stock_id: str, ref_date: date):
    cur.execute("""
      SELECT as_of_date, holder_range, share_percent
      FROM tdcc_share_distribution
      WHERE market=%s AND stock_id=%s AND as_of_date<=%s
      ORDER BY as_of_date DESC
    """, (market, stock_id, ref_date))
    rows = cur.fetchall()
    if not rows:
        return None, {"status": "MISSING", "latest_date": None}
    dates = sorted({row[0] for row in rows}, reverse=True)
    latest = dates[0]
    age = (ref_date - latest).days
    if age > 21:
        return None, {"status": "STALE", "latest_date": str(latest), "age_days": age}
    def concentration(as_of):
        subset = [r for r in rows if r[0] == as_of]
        large = sum(float(r[2]) for r in subset
                    if r[1] in ("400,001-600,000", "600,001-800,000",
                                "800,001-1,000,000", "1,000,001以上"))
        small = sum(float(r[2]) for r in subset
                    if r[1] in ("1-999", "1,000-5,000"))
        return large, small
    large_now, small_now = concentration(latest)
    if len(dates) < 2:
        return None, {"status": "INSUFFICIENT_HISTORY", "latest_date": str(latest),
                      "large_holder_percent": round(large_now, 2),
                      "small_holder_percent": round(small_now, 2)}
    large_prev, small_prev = concentration(dates[1])
    delta = (large_now - small_now) - (large_prev - small_prev)
    score = clamp(50 + delta * 5)
    return round(score, 2), {"status": "AVAILABLE", "latest_date": str(latest),
                              "large_holder_percent": round(large_now, 2),
                              "small_holder_percent": round(small_now, 2),
                              "large_minus_small_change_pp": round(delta, 3)}


def _insider(cur, market: str, stock_id: str, ref_date: date):
    cur.execute("""
      SELECT as_of_date, SUM(share_count), SUM(COALESCE(pledged_shares,0)), COUNT(*)
      FROM insider_holdings
      WHERE market=%s AND stock_id=%s AND as_of_date<=%s
      GROUP BY as_of_date ORDER BY as_of_date DESC LIMIT 1
    """, (market, stock_id, ref_date))
    row = cur.fetchone()
    if not row:
        return None, {"status": "MISSING", "latest_date": None}
    latest, shares, pledged, people = row
    age = (ref_date - latest).days
    if age > 120:
        return None, {"status": "STALE", "latest_date": str(latest), "age_days": age}
    if not shares:
        return None, {"status": "MISSING", "latest_date": str(latest)}
    ratio = float(pledged or 0) / float(shares)
    return round(clamp(100 - ratio * 100), 2), {
        "status": "AVAILABLE", "latest_date": str(latest),
        "director_shares": int(shares), "pledged_shares": int(pledged or 0),
        "pledged_ratio": round(ratio, 5), "reported_rows": int(people)}


def calculate_all(database_url: str) -> int:
    insert = """
      INSERT INTO daily_chip_scores
        (market, stock_id, as_of_date, total_score, coverage_weight,
         institutional_score, margin_score, tdcc_score, insider_score,
         component_status, calculated_at)
      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,now())
      ON CONFLICT (market, stock_id, as_of_date) DO UPDATE SET
        total_score=EXCLUDED.total_score, coverage_weight=EXCLUDED.coverage_weight,
        institutional_score=EXCLUDED.institutional_score, margin_score=EXCLUDED.margin_score,
        tdcc_score=EXCLUDED.tdcc_score, insider_score=EXCLUDED.insider_score,
        component_status=EXCLUDED.component_status, calculated_at=now()
    """
    count = 0
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT market, stock_id FROM stock_master ORDER BY market, stock_id")
            stocks = cur.fetchall()
            for market, stock_id in stocks:
                ref_date = _latest_price_date(cur, market, stock_id)
                if ref_date is None:
                    continue
                inst, inst_status = _institutional(cur, market, stock_id, ref_date)
                margin, margin_status = _margin(cur, market, stock_id, ref_date)
                tdcc, tdcc_status = _tdcc(cur, market, stock_id, ref_date)
                insider, insider_status = _insider(cur, market, stock_id, ref_date)
                components = {"institutional": inst, "margin": margin,
                              "tdcc": tdcc, "insider": insider}
                total, coverage = weighted_score(components)
                status = {"institutional": inst_status, "margin": margin_status,
                          "tdcc": tdcc_status, "insider": insider_status}
                cur.execute(insert, (market, stock_id, ref_date, total, coverage,
                    inst, margin, tdcc, insider, json.dumps(status, ensure_ascii=False)))
                count += 1
    return count


def main() -> None:
    from tdcc_data import normalize_database_url
    url = normalize_database_url(os.environ["DATABASE_URL"])
    count = calculate_all(url)
    print(f"綜合籌碼評分完成：{count} 檔股票")
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
              SELECT market, stock_id, as_of_date, total_score, coverage_weight,
                     component_status
              FROM daily_chip_scores ORDER BY market, stock_id
            """)
            for row in cur.fetchall():
                print(*row)


if __name__ == "__main__":
    main()
