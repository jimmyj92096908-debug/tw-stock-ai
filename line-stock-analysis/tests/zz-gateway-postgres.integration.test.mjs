// End-to-end LINE gateway verification with real disposable PostgreSQL, not
// Neon, LINE API, or any real LINE user. This test intentionally runs last.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import pg from 'pg';
import { createSingleAccountCandidate } from '../single-account-candidate.mjs';
import { createSingleAccountGateway } from '../single-account-gateway.mjs';
import { createDeliveryStore } from '../delivery-state.mjs';
import { DATA_STATUS_SQL } from '../handler.mjs';

const uri=process.env.LINE_CI_POSTGRES_URL;
const SECRET='ci-only-not-a-line-channel-secret';
const NOW=Date.parse('2026-11-20T05:00:00Z');

function signed(events) {
  const body=JSON.stringify({destination:'U-ci-not-a-real-bot',events});
  return new Request('https://ci.invalid/webhook',{
    method:'POST',headers:{
      'content-type':'application/json',
      'x-line-signature':createHmac('sha256',SECRET).update(body).digest('base64')
    },body
  });
}
function event(text,id,extras={}) {
  return {
    type:'message',source:{type:'user',userId:'U-ci-not-a-real-user'},
    message:{type:'text',text},webhookEventId:id,
    replyToken:'ci-fake-'+id,timestamp:NOW,
    deliveryContext:{isRedelivery:false},
    ...extras
  };
}

test('LINE signed mixed events use real SQL claims and retain legacy recipient logging',{
  skip:!uri && 'Only disposable PostgreSQL CI is supported'
},async()=>{
  const parsed=new URL(uri);
  if(!['127.0.0.1','localhost'].includes(parsed.hostname) ||
     parsed.pathname!=='/line_ci_test' ||
     !['postgres:','postgresql:'].includes(parsed.protocol)) {
    throw Error('Refusing to run integrated test outside localhost/line_ci_test');
  }

  const pool=new pg.Pool({connectionString:uri,max:3,connectionTimeoutMillis:4000});
  try {
    await pool.query(`CREATE TABLE IF NOT EXISTS public.line_messages (
      id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      event_id TEXT UNIQUE,
      line_user_id TEXT,
      message_type TEXT NOT NULL,
      message_text TEXT,
      received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )`);
    const ddl=await readFile(
      new URL('../../sql/line_reply_delivery_schema.sql',import.meta.url),'utf8'
    );
    await pool.query(ddl);
    await pool.query(`CREATE TABLE IF NOT EXISTS public.stock_master (
      market TEXT NOT NULL,stock_id TEXT NOT NULL,stock_name TEXT NOT NULL,
      PRIMARY KEY(market,stock_id)
    )`);
    await pool.query(`CREATE TABLE IF NOT EXISTS public.daily_prices (
      market TEXT NOT NULL,stock_id TEXT NOT NULL,trade_date DATE NOT NULL,
      close NUMERIC,PRIMARY KEY(market,stock_id,trade_date)
    )`);
    await pool.query(`CREATE TABLE IF NOT EXISTS public.daily_composite_scores (
      market TEXT NOT NULL,stock_id TEXT NOT NULL,as_of_date DATE NOT NULL,
      total_score NUMERIC,PRIMARY KEY(market,stock_id,as_of_date)
    )`);

    const replies=[],legacy=[];
    let attempts=0;
    const store=createDeliveryStore((sql,params)=>pool.query(sql,params));
    const stockHandler=createSingleAccountCandidate({
      channelSecret:SECRET,store,now:()=>NOW,
      query:async(sql,params)=>{
        assert.equal(sql,DATA_STATUS_SQL);
        assert.deepEqual(params,[]);
        return pool.query(sql,params);
      },
      sendReply:async(token,text)=>{
        attempts++;
        // First LINE response is lost after DB recorded inbound event.
        if(attempts===1) throw Error('CI-only temporary failure');
        replies.push({token,text});
      }
    });
    const gateway=createSingleAccountGateway({
      channelSecret:SECRET,stockHandler,
      forwardLegacy:async(body,sig)=>{
        assert.equal(
          createHmac('sha256',SECRET).update(body).digest('base64'),sig
        );
        legacy.push(JSON.parse(body).events.map(e=>e.webhookEventId));
        return {status:200};
      }
    });
    const stockEvent=event('資料狀態','ci-gateway-e2e-stock');
    const legacyEvent=event('你好','ci-gateway-e2e-legacy');

    // Fail before forwarding legacy; persistent inbound record must survive.
    const first=await gateway(signed([stockEvent,legacyEvent]));
    assert.equal(first.status,502);
    assert.deepEqual(legacy,[]);
    const logged=await pool.query(`
      SELECT message_type,message_text,line_user_id FROM public.line_messages
      WHERE event_id=$1
    `,['ci-gateway-e2e-stock']);
    assert.equal(logged.rows.length,1);
    assert.deepEqual(logged.rows[0],{
      message_type:'text',message_text:'資料狀態',
      line_user_id:'U-ci-not-a-real-user'
    });
    const firstState=await pool.query(`
      SELECT state,attempts FROM public.line_reply_delivery WHERE event_id=$1
    `,['ci-gateway-e2e-stock']);
    assert.deepEqual(firstState.rows[0],{state:'retryable',attempts:1});

    const redelivered={
      ...stockEvent,deliveryContext:{isRedelivery:true}
    };
    const retried=await gateway(signed([redelivered,legacyEvent]));
    assert.equal(retried.status,200);
    assert.equal(attempts,2);
    assert.equal(replies.length,1);
    assert.equal(replies[0].token,'ci-fake-ci-gateway-e2e-stock');
    assert.match(replies[0].text,/台股資料庫更新狀態/u);
    assert.deepEqual(legacy,[['ci-gateway-e2e-legacy']]);

    const done=await pool.query(`
      SELECT state,attempts FROM public.line_reply_delivery WHERE event_id=$1
    `,['ci-gateway-e2e-stock']);
    assert.deepEqual(done.rows[0],{state:'sent',attempts:2});

    // Already-sent redelivery must not create a second reply or recipient.
    const repeat=await gateway(signed([redelivered]));
    assert.equal(repeat.status,200);
    assert.equal(replies.length,1);
    const count=await pool.query(`
      SELECT COUNT(*)::int AS n FROM public.line_messages WHERE event_id=$1
    `,['ci-gateway-e2e-stock']);
    assert.equal(count.rows[0].n,1);

    // Old message remains legacy-owned; no duplicated daily-report recipient
    // enrollment from the new stock pipeline.
    const old=await pool.query(`
      SELECT COUNT(*)::int AS n FROM public.line_messages WHERE event_id=$1
    `,['ci-gateway-e2e-legacy']);
    assert.equal(old.rows[0].n,0);
  }finally{
    await pool.end();
  }
});
