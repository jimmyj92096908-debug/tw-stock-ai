import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { createSingleAccountGateway } from '../single-account-gateway.mjs';
import { createSingleAccountCandidate } from '../single-account-candidate.mjs';
import { DATA_STATUS_SQL } from '../handler.mjs';

const TIME=Date.parse('2026-11-20T08:00:00Z');
const secret='fake-only-status-channel-secret';

function event(text,id){
  return {
    type:'message',webhookEventId:id,
    timestamp:TIME,replyToken:'fake-'+id,
    source:{type:'user',userId:'U-not-a-real-user'},
    message:{type:'text',text},
    deliveryContext:{isRedelivery:false}
  };
}

function signed(events) {
  const body=JSON.stringify({events});
  const signature=createHmac('sha256',secret).update(body).digest('base64');
  return new Request('https://example.test/webhook',{
    method:'POST',headers:{
      'content-type':'application/json',
      'x-line-signature':signature
    },body
  });
}

test('signed LINE 資料狀態 flows through the gateway and preserves old message route',async()=>{
  const calls=[],replies=[],legacy=[],states=new Map();
  const store={
    async recordInbound(row){calls.push({kind:'record',row});},
    async claimReply(id){
      if(states.get(id)==='sent')return {acquired:false,reason:'sent'};
      states.set(id,'sending');
      return {acquired:true,attemptKey:'fake-claim'};
    },
    async completeReply(id){states.set(id,'sent');},
    async failReply(id){states.set(id,'retryable');}
  };
  const stockHandler=createSingleAccountCandidate({
    channelSecret:secret,now:()=>TIME,store,
    query:async(sql,params)=>{
      assert.equal(sql,DATA_STATUS_SQL);
      assert.deepEqual(params,[]);
      return {rows:[{
        universe:1991,priced:40,price_date:'2026-11-19',
        score_date:'2026-11-18',scored_latest:18
      }]};
    },
    sendReply:async(replyToken,text)=>replies.push({replyToken,text})
  });
  const gateway=createSingleAccountGateway({
    channelSecret:secret,stockHandler,
    forwardLegacy:async(body,signature)=>{
      assert.equal(signature,createHmac('sha256',secret).update(body).digest('base64'));
      legacy.push(JSON.parse(body).events);
      return {status:200};
    }
  });

  const first=await gateway(signed([event('資料狀態','evt-status'),event('你好','evt-old')]));
  assert.equal(first.status,200);
  assert.equal(replies.length,1);
  assert.equal(replies[0].replyToken,'fake-evt-status');
  assert.match(replies[0].text,/台股資料庫更新狀態/u);
  assert.match(replies[0].text,/尚無行情：1,951 檔/u);
  assert.equal(calls.length,1);
  assert.equal(calls[0].row.message_type,'text');
  assert.deepEqual(legacy[0].map(e=>e.webhookEventId),['evt-old']);

  const repeated=await gateway(signed([event('資料狀態','evt-status')]));
  assert.equal(repeated.status,200);
  assert.equal(replies.length,1); // existing successful reply is not duplicated
});
