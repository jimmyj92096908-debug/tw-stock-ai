// End-to-end mocked transport and persistence: stock reply must not be
// duplicated when the legacy side of a mixed LINE batch fails and redelivers.
// This never connects to LINE, Neon, or any real messaging service.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { createSingleAccountGateway } from '../single-account-gateway.mjs';
import { createSingleAccountCandidate } from '../single-account-candidate.mjs';
import { ANALYSIS_SQL } from '../handler.mjs';

const secret='local-test-only-secret';
const NOW=Date.parse('2026-11-20T08:00:00Z');

function event(text,id,redelivery=false) {
  return {
    type:'message',webhookEventId:id,timestamp:NOW,
    deliveryContext:{isRedelivery:redelivery},
    source:{type:'user',userId:'U-synthetic'},
    message:{type:'text',text},replyToken:'fake-token-'+id
  };
}
function signed(events) {
  const body=JSON.stringify({destination:'U-fake-bot',events});
  const signature=createHmac('sha256',secret).update(body).digest('base64');
  return new Request('https://example.invalid/webhook',{
    method:'POST',
    headers:{'content-type':'application/json','x-line-signature':signature},
    body
  });
}

test('legacy failure followed by redelivery sends at most one stock reply',async()=>{
  const saved=new Set(),replyStatus=new Map();
  const recorded=[],replied=[],forwarded=[],stockQueries=[];
  const store={
    async recordInbound(row) {
      if(!saved.has(row.event_id)) {
        saved.add(row.event_id);
        recorded.push(row);
      }
    },
    async claimReply(id) {
      if(replyStatus.get(id)==='sent') return {acquired:false,reason:'sent'};
      if(replyStatus.get(id)==='sending') return {acquired:false,reason:'busy'};
      replyStatus.set(id,'sending');
      return {acquired:true,attemptKey:'local-key'};
    },
    async completeReply(id,key) {
      assert.equal(key,'local-key');
      assert.equal(replyStatus.get(id),'sending');
      replyStatus.set(id,'sent');
    },
    async failReply(id,key) {
      assert.equal(key,'local-key');
      replyStatus.set(id,'retryable');
    }
  };
  const candidate=createSingleAccountCandidate({
    channelSecret:secret,store,now:()=>NOW,
    query:async(sql,params)=>{
      assert.equal(sql,ANALYSIS_SQL);
      stockQueries.push(params);
      return {rows:[{
        market:'twse',stock_id:'2330',stock_name:'台積電',
        price_date:'2026-11-20',close:'1550',
        score_date:'2026-11-19',total_score:'26.98',
        coverage_weight:'0.60',chip_score:null
      }]};
    },
    sendReply:async(token,text)=>replied.push({token,text})
  });
  let upstreamFailures=0;
  const gateway=createSingleAccountGateway({
    channelSecret:secret,stockHandler:candidate,
    forwardLegacy:async(body,sig)=>{
      assert.equal(createHmac('sha256',secret).update(body).digest('base64'),sig);
      const parsed=JSON.parse(body);
      forwarded.push(parsed.events.map(x=>x.webhookEventId));
      assert.deepEqual(parsed.events.map(x=>x.webhookEventId),['legacy-1']);
      if(upstreamFailures++===0) throw Error('Synthetic legacy transport failure');
      return {status:200};
    }
  });
  const first=await gateway(signed([
    event('2330','stock-1'),event('你好','legacy-1')
  ]));
  assert.equal(first.status,502);
  assert.deepEqual(replied.map(x=>x.token),['fake-token-stock-1']);
  assert.deepEqual(recorded.map(x=>x.event_id),['stock-1']);
  assert.deepEqual(stockQueries,[['2330']]);
  assert.equal(replyStatus.get('stock-1'),'sent');
  assert.deepEqual(forwarded,[['legacy-1']]);

  const redelivery=await gateway(signed([
    event('2330','stock-1',true),event('你好','legacy-1',true)
  ]));
  assert.equal(redelivery.status,200);
  assert.equal(replied.length,1,'Previously sent stock reply may never duplicate');
  assert.equal(recorded.length,1,'Daily report sender log remains idempotent');
  assert.equal(stockQueries.length,1,'Already-sent stock reply needs no second SQL query');
  assert.deepEqual(forwarded,[['legacy-1'],['legacy-1']]);
});
