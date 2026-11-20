// Real disposable PostgreSQL 17 SQL acceptance for the exact-name lookup and
// full research query. Never connects to production Neon or real LINE.
import test from 'node:test';
import assert from 'node:assert/strict';
import pg from 'pg';
import { ANALYSIS_SQL, STOCK_NAME_SQL, buildReplyText } from '../handler.mjs';

const url=process.env.LINE_CI_POSTGRES_URL;
test('real PostgreSQL resolves 聯茂 and returns price, indicators, SMC and scores', {
  skip:!url && 'Only disposable local PostgreSQL CI'
},async()=>{
  const parsed=new URL(url);
  if(!['localhost','127.0.0.1'].includes(parsed.hostname) ||
     parsed.pathname!=='/line_ci_test' ||
     !['postgres:','postgresql:'].includes(parsed.protocol)) {
    throw Error('Refusing a non-local test database');
  }
  const pool=new pg.Pool({connectionString:url,max:1});
  const schema='ci_stockname_e2e';
  try {
    await pool.query('CREATE SCHEMA IF NOT EXISTS '+schema);
    await pool.query(`CREATE TABLE IF NOT EXISTS ${schema}.stock_master (
      market TEXT NOT NULL, stock_id TEXT NOT NULL, stock_name TEXT NOT NULL,
      PRIMARY KEY(market,stock_id))`);
    await pool.query(`CREATE TABLE IF NOT EXISTS ${schema}.daily_prices (
      market TEXT NOT NULL,stock_id TEXT NOT NULL,trade_date DATE NOT NULL,
      open NUMERIC,high NUMERIC,low NUMERIC,close NUMERIC,price_change NUMERIC,
      volume BIGINT,PRIMARY KEY(market,stock_id,trade_date))`);
    await pool.query(`CREATE TABLE IF NOT EXISTS ${schema}.daily_technicals (
      market TEXT NOT NULL,stock_id TEXT NOT NULL,trade_date DATE NOT NULL,
      ma5 NUMERIC,ma10 NUMERIC,ma13 NUMERIC,ma20 NUMERIC,ma34 NUMERIC,
      ma55 NUMERIC,ma60 NUMERIC,ma120 NUMERIC,ma240 NUMERIC,rsi14 NUMERIC,
      atr14 NUMERIC,volume_ma5 NUMERIC,volume_ma20 NUMERIC,
      PRIMARY KEY(market,stock_id,trade_date))`);
    await pool.query(`CREATE TABLE IF NOT EXISTS ${schema}.daily_smc (
      market TEXT NOT NULL,stock_id TEXT NOT NULL,trade_date DATE NOT NULL,
      trend_direction SMALLINT,bos_bullish BOOLEAN,bos_bearish BOOLEAN,
      choch_bullish BOOLEAN,choch_bearish BOOLEAN,
      liquidity_sweep_high BOOLEAN,liquidity_sweep_low BOOLEAN,
      order_block_type TEXT,order_block_high NUMERIC,order_block_low NUMERIC,
      fvg_type TEXT,fvg_high NUMERIC,fvg_low NUMERIC,
      PRIMARY KEY(market,stock_id,trade_date))`);
    await pool.query(`CREATE TABLE IF NOT EXISTS ${schema}.daily_composite_scores (
      market TEXT NOT NULL,stock_id TEXT NOT NULL,as_of_date DATE NOT NULL,
      total_score NUMERIC,coverage_weight NUMERIC,short_term_score NUMERIC,
      swing_score NUMERIC,long_term_score NUMERIC,chip_score NUMERIC,
      technical_score NUMERIC,smc_score NUMERIC,
      PRIMARY KEY(market,stock_id,as_of_date))`);
    await pool.query(`INSERT INTO ${schema}.stock_master
      (market,stock_id,stock_name) VALUES('twse','6213','聯茂')
      ON CONFLICT(market,stock_id) DO UPDATE SET stock_name=EXCLUDED.stock_name`);
    const priceRows=Array.from({length:60},(_,i)=>[
      'twse','6213',new Date(Date.UTC(2026,8,1+i)).toISOString().slice(0,10),
      400,410,390,395,-5,10757913
    ]);
    for(const values of priceRows) {
      await pool.query(`INSERT INTO ${schema}.daily_prices
        (market,stock_id,trade_date,open,high,low,close,price_change,volume)
        VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)
        ON CONFLICT DO NOTHING`,values);
    }
    await pool.query(`INSERT INTO ${schema}.daily_technicals
      (market,stock_id,trade_date,ma5,ma20,ma60,rsi14,atr14,volume_ma20)
      VALUES('twse','6213','2026-10-30',455.7,595.53,607.77,29.93,58.96,19797043)
      ON CONFLICT DO NOTHING`);
    await pool.query(`INSERT INTO ${schema}.daily_smc
      (market,stock_id,trade_date,trend_direction,bos_bearish)
      VALUES('twse','6213','2026-10-30',-1,true)
      ON CONFLICT DO NOTHING`);
    await pool.query(`INSERT INTO ${schema}.daily_composite_scores
      (market,stock_id,as_of_date,total_score,coverage_weight,
        short_term_score,swing_score,long_term_score,technical_score,smc_score)
      VALUES('twse','6213','2026-10-30',32.33,.60,28.12,22.50,34.06,30.42,35)
      ON CONFLICT DO NOTHING`);

    const query=async(sql,args)=>pool.query(sql.replaceAll('public.','ci_stockname_e2e.'),args);
    const byCode=await buildReplyText('6213',query);
    const byName=await buildReplyText('聯茂',query);
    assert.equal(byName.replace('名稱查詢｜',''),byCode);
    assert.match(byName,/6213 聯茂/u);
    assert.match(byName,/RSI14：29\.9/u);
    assert.match(byName,/SMC/u);
    assert.match(byName,/總分：32\.3/u);
    assert.match(byName,/短中期偏弱/u);
    assert.match(byName,/歷史區間/u);
    assert.match(byName,/非買賣指令/u);
    const name=await query(STOCK_NAME_SQL,['聯茂']);
    assert.deepEqual(name.rows.map(x=>x.stock_id),['6213']);
    const direct=await query(ANALYSIS_SQL,['6213']);
    assert.equal(direct.rows.length,1);
    assert.equal(Number(direct.rows[0].total_score),32.33);
  } finally {
    await pool.query('DROP SCHEMA IF EXISTS ci_stockname_e2e CASCADE');
    await pool.end();
  }
});
