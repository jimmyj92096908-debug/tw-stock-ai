"""Combine technical, SMC and chip subscores into an auditable daily score."""
from __future__ import annotations
import json
import os
from datetime import date
import psycopg

WEIGHTS = {"technical": 0.35, "smc": 0.25, "chip": 0.40}
MIN_COVERAGE = 0.50

def clamp(value, low=0.0, high=100.0):
    return max(low, min(high, float(value)))

def technical_score(row):
    if not row or row.get("close") is None:
        return None, {"status": "MISSING_PRICE"}
    ma_keys = ("ma5","ma10","ma13","ma20","ma34","ma55","ma60","ma120","ma240")
    available = [float(row[k]) for k in ma_keys if row.get(k) is not None]
    if not available:
        return None, {"status":"MISSING_MA"}
    close = float(row["close"])
    above = sum(close > value for value in available)
    below = sum(close < value for value in available)
    alignment = 50 + 50 * (above - below) / len(available)
    rsi = row.get("rsi14")
    rsi_score = 50.0 if rsi is None else (65.0 if float(rsi) < 30 else 55.0 if float(rsi) < 45 else 45.0 if float(rsi) > 70 else 55.0 if float(rsi) <= 60 else 50.0)
    v5, v20 = row.get("volume_ma5"), row.get("volume_ma20")
    volume_score = 50.0
    ratio = None
    if v5 is not None and v20 is not None and float(v20) > 0:
        ratio = float(v5) / float(v20)
        volume_score = 60.0 if ratio >= 1.2 else 40.0 if ratio <= 0.8 else 50.0
    score = clamp(alignment * 0.60 + rsi_score * 0.25 + volume_score * 0.15)
    return round(score,2), {"status":"AVAILABLE","ma_count":len(available),
        "price_above_ma":above,"price_below_ma":below,"rsi14":float(rsi) if rsi is not None else None,
        "volume_ratio_5d_20d":round(ratio,3) if ratio is not None else None}

def smc_score(row):
    if not row:
        return None, {"status":"MISSING"}
    trend = row.get("trend_direction")
    if trend is None:
        return None, {"status":"MISSING_TREND"}
    score = 50.0 + (15.0 if int(trend)>0 else -15.0 if int(trend)<0 else 0.0)
    for key, delta in (("bos_bullish",8),("choch_bullish",10),("liquidity_sweep_low",6),
                       ("bos_bearish",-8),("choch_bearish",-10),("liquidity_sweep_high",-6)):
        if row.get(key):
            score += delta
    ob = row.get("order_block_type")
    fvg = row.get("fvg_type")
    if ob == "bullish": score += 3
    elif ob == "bearish": score -= 3
    if fvg == "bullish": score += 3
    elif fvg == "bearish": score -= 3
    return round(clamp(score),2), {"status":"AVAILABLE","trend_direction":int(trend),
        "order_block_type":ob,"fvg_type":fvg}

def combine_scores(components, minimum_coverage=MIN_COVERAGE):
    available = {k: float(v) for k,v in components.items() if k in WEIGHTS and v is not None}
    coverage = round(sum(WEIGHTS[k] for k in available),2)
    if not available:
        return None, coverage
    score = round(sum(WEIGHTS[k]*v for k,v in available.items())/coverage,2)
    return (score if coverage >= minimum_coverage else None), coverage

def calculate_all(database_url):
    upsert = """INSERT INTO daily_composite_scores
    (market,stock_id,as_of_date,total_score,coverage_weight,technical_score,smc_score,chip_score,component_status,calculated_at)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,now())
    ON CONFLICT (market,stock_id,as_of_date) DO UPDATE SET
    total_score=EXCLUDED.total_score,coverage_weight=EXCLUDED.coverage_weight,
    technical_score=EXCLUDED.technical_score,smc_score=EXCLUDED.smc_score,
    chip_score=EXCLUDED.chip_score,component_status=EXCLUDED.component_status,calculated_at=now()"""
    count=0
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT DISTINCT market,stock_id FROM daily_prices
                           WHERE stock_id IN ('6213','8937','4919','7827') ORDER BY market,stock_id""")
            stocks=cur.fetchall()
            for market,stock_id in stocks:
                cur.execute("""SELECT p.trade_date,p.close,t.ma5,t.ma10,t.ma13,t.ma20,t.ma34,t.ma55,t.ma60,t.ma120,t.ma240,
                    t.rsi14,t.volume_ma5,t.volume_ma20
                    FROM daily_prices p LEFT JOIN daily_technicals t USING (market,stock_id,trade_date)
                    WHERE p.market=%s AND p.stock_id=%s ORDER BY p.trade_date DESC LIMIT 1""",(market,stock_id))
                tr=cur.fetchone()
                if not tr: continue
                keys=("trade_date","close","ma5","ma10","ma13","ma20","ma34","ma55","ma60","ma120","ma240","rsi14","volume_ma5","volume_ma20")
                tech_row=dict(zip(keys,tr))
                tech,tech_status=technical_score(tech_row)
                cur.execute("""SELECT trend_direction,bos_bullish,bos_bearish,choch_bullish,choch_bearish,
                    liquidity_sweep_high,liquidity_sweep_low,order_block_type,fvg_type
                    FROM daily_smc WHERE market=%s AND stock_id=%s AND trade_date=%s""",(market,stock_id,tr[0]))
                sr=cur.fetchone()
                smc_keys=("trend_direction","bos_bullish","bos_bearish","choch_bullish","choch_bearish",
                    "liquidity_sweep_high","liquidity_sweep_low","order_block_type","fvg_type")
                smc,s_status=smc_score(dict(zip(smc_keys,sr)) if sr else None)
                cur.execute("""SELECT total_score,coverage_weight,as_of_date FROM daily_chip_scores
                    WHERE market=%s AND stock_id=%s ORDER BY as_of_date DESC LIMIT 1""",(market,stock_id))
                cr=cur.fetchone()
                chip=None
                chip_status={"status":"MISSING"}
                if cr and cr[0] is not None and float(cr[1]) >= 0.50:
                    chip=float(cr[0]); chip_status={"status":"AVAILABLE","as_of_date":str(cr[2]),"source_coverage":float(cr[1])}
                elif cr:
                    chip_status={"status":"INSUFFICIENT_SOURCE_COVERAGE","as_of_date":str(cr[2]),"source_coverage":float(cr[1])}
                total,coverage=combine_scores({"technical":tech,"smc":smc,"chip":chip})
                status={"technical":tech_status,"smc":s_status,"chip":chip_status}
                cur.execute(upsert,(market,stock_id,tr[0],total,coverage,tech,smc,chip,json.dumps(status,ensure_ascii=False)))
                count+=1
    return count

def main():
    from tdcc_data import normalize_database_url
    url=normalize_database_url(os.environ["DATABASE_URL"])
    count=calculate_all(url)
    print(f"多因子綜合評分完成：{count} 檔")
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT market,stock_id,as_of_date,total_score,coverage_weight,component_status FROM daily_composite_scores ORDER BY market,stock_id")
            for row in cur.fetchall(): print(*row)

if __name__=="__main__": main()
