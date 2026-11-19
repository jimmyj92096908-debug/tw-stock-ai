import test from 'node:test';
import assert from 'node:assert/strict';
import pg from 'pg';
import {
  parseStockCode, formatDataStatus, DATA_STATUS_SQL, RANKING_SQL, buildReplyText
} from '../handler.mjs';

test('database status is an explicit LINE command, not an accidental stock code',()=>{
  for(const s of ['資料狀態','更新狀態','資料庫狀態','資料更新']){
    assert.equal(parseStockCode(s).kind,'status');
  }
  assert.equal(parseStockCode('資料狀態 nonsense').kind,'invalid');
  assert.equal(parseStockCode('說明').kind,'help');
});

test('status formatter exposes price date, score date and missing coverage',async()=>{
  const data={
    universe:1991,priced:40,price_date:'2026-11-19',
    score_date:'2026-11-18',scored_latest:18
  };
  const msg=formatDataStatus(data);
  assert.match(msg,/2026-11-19/u);
  assert.match(msg,/2026-11-18/u);
  assert.match(msg,/已有行情：40 檔（2\.0%）/u);
  assert.match(msg,/尚無行情：1,951 檔/u);
  assert.match(msg,/最新評分資料筆數：18/u);
  assert.match(msg,/不是交易所完整股票數/u);
  const calls=[];
  const reply=await buildReplyText('資料狀態',async(sql,params)=>{
    calls.push({sql,params});return {rows:[data]};
  });
  assert.equal(reply,msg);
  assert.deepEqual(calls,[{sql:DATA_STATUS_SQL,params:[]}]);
});

test('status formatter is explicit on missing or corrupt data',()=>{
  assert.match(formatDataStatus(null),/無法讀取/u);
  assert.match(formatDataStatus({universe:0,priced:0,scored_latest:0}),/0\.0%/u);
  assert.match(formatDataStatus({universe:2,priced:5,scored_latest:1}),/無法讀取有效/u);
  assert.match(formatDataStatus({universe:'x',priced:0,scored_latest:0}),/無法讀取有效/u);
  assert.match(DATA_STATUS_SQL,/COUNT\(\*\)::int FROM public\.stock_master/u);
  assert.match(RANKING_SQL,/JOIN public\.daily_prices p/u);
  assert.match(RANKING_SQL,/p\.trade_date=c\.as_of_date AND p\.close IS NOT NULL/u);
});

const testUrl=process.env.LINE_CI_POSTGRES_URL;

test('disposable Postgres agrees on real status SQL and excludes unpriced ranking rows',{
  skip:!testUrl && 'Requires a disposable local CI PostgreSQL database'
},async()=>{
  const u=new URL(testUrl);
  if(!['127.0.0.1','localhost'].includes(u.hostname) ||
     u.pathname!=='/line_ci_test' ||
     !['postgres:','postgresql:'].includes(u.protocol)) {
    throw Error('Refusing to modify any database outside disposable localhost CI');
  }
  const client=new pg.Client({connectionString:testUrl});
  await client.connect();
  try {
    await client.query("CREATE TABLE public.stock_master (market TEXT NOT NULL,stock_id TEXT NOT NULL,stock_name TEXT NOT NULL,PRIMARY KEY(market,stock_id))");
    await client.query("CREATE TABLE public.daily_prices (market TEXT NOT NULL,stock_id TEXT NOT NULL,trade_date DATE NOT NULL,close NUMERIC,PRIMARY KEY(market,stock_id,trade_date))");
    await client.query("CREATE TABLE public.daily_composite_scores (market TEXT NOT NULL,stock_id TEXT NOT NULL,as_of_date DATE NOT NULL,total_score NUMERIC,PRIMARY KEY(market,stock_id,as_of_date))");
    await client.query("INSERT INTO public.stock_master VALUES ('twse','2330','台積電'),('twse','1101','測試水泥'),('twse','6213','測試電子'),('tpex','6488','測試矽晶'),('twse','1808','排除標的')");
    await client.query("INSERT INTO public.daily_prices VALUES ('twse','2330','2026-11-18',1400),('twse','1101','2026-11-18',28),('twse','6213','2026-11-18',NULL),('twse','6213','2026-11-19',NULL),('twse','1808','2026-11-18',15)");
    await client.query("INSERT INTO public.daily_composite_scores VALUES ('twse','2330','2026-11-18',80),('twse','1101','2026-11-18',60),('twse','6213','2026-11-18',95),('tpex','6488','2026-11-18',85),('twse','1808','2026-11-18',99),('twse','1101','2026-11-19',NULL)");

    const status=(await client.query(DATA_STATUS_SQL)).rows[0];
    assert.equal(status.universe,5);
    assert.equal(status.priced,3);
    assert.equal(status.scored_latest,5);
    assert.equal(status.score_date.toISOString().slice(0,10),'2026-11-18');
    assert.match(formatDataStatus(status),/尚無行情：2 檔/u);

    const ranked=(await client.query(RANKING_SQL)).rows;
    assert.deepEqual(ranked.map(x=>x.stock_id),['2330','1101']);
    assert.deepEqual(ranked.map(x=>Number(x.total_score)),[80,60]);
  }finally{
    await client.end();
  }
});
