import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import {
  createSingleAccountCandidate, observedLegacyReply
} from '../single-account-candidate.mjs';
import { ANALYSIS_SQL, RANKING_SQL } from '../handler.mjs';

const TIME = Date.parse('2026-11-20T00:50:00Z');
function message(text, id='evt-1', extras={}) {
  return {
    type:'message', webhookEventId:id, timestamp:TIME,
    source:{type:'user',userId:'U-test-not-a-real-user'},
    message:{type:'text',text},replyToken:'fake-reply-token',
    ...extras
  };
}
function signedRequest(events, overrideSignature) {
  const body = JSON.stringify({events});
  const signature = overrideSignature ??
    createHmac('sha256','mock-secret').update(body).digest('base64');
  return new Request('https://test.invalid/webhook',{
    method:'POST',headers:{
      'content-type':'application/json','x-line-signature':signature
    },body
  });
}
const sample = {
  market:'twse',stock_id:'2330',stock_name:'台積電',
  price_date:'2026-10-30',close:1500,price_change:5,volume:100000,
  technical_date:null,smc_date:null,score_date:null
};
const ranking = [
  {market:'twse',stock_id:'2330',stock_name:'台積電',total_score:49,as_of_date:'2026-11-18'}
];

function mock(override={}) {
  const logs=[], replies=[], queries=[], replyStates=new Map();
  const knownLogs=new Set();
  const store={
    async recordInbound(record) {
      if(!knownLogs.has(record.event_id)){
        knownLogs.add(record.event_id);
        logs.push(record);
      }
    },
    async claimReply(id) {
      const previous=replyStates.get(id);
      if(previous?.state==='sent') return {acquired:false,reason:'sent'};
      if(previous?.state==='sending') return {acquired:false,reason:'busy'};
      if(previous?.attempts>=3) return {acquired:false,reason:'exhausted'};
      const attempts=(previous?.attempts ?? 0)+1;
      const attemptKey='fake-attempt-'+attempts;
      replyStates.set(id,{attempts,state:'sending',attemptKey});
      return {acquired:true,attemptKey};
    },
    async completeReply(id,key) {
      const current=replyStates.get(id);
      if(current.state!=='sending'||current.attemptKey!==key) throw Error('invalid attempt');
      current.state='sent';
    },
    async failReply(id,key) {
      const current=replyStates.get(id);
      if(current.state!=='sending'||current.attemptKey!==key) throw Error('invalid attempt');
      current.state='retryable';
    }
  };
  const handler = createSingleAccountCandidate({
    channelSecret:'mock-secret', now:()=>TIME, store,
    query:async(sql,args)=>{
      queries.push({sql,args});
      if(sql===RANKING_SQL) return {rows:ranking};
      if(sql===ANALYSIS_SQL) return {rows:[{...sample,stock_id:args[0]}]};
      throw new Error('unexpected SQL');
    },
    sendReply:async(token,body)=>{replies.push({token,body});},
    ...override
  });
  return {handler,store,logs,replies,queries,replyStates};
}

test('observed fallback matches screenshot but is not a full legacy implementation',()=>{
  assert.equal(observedLegacyReply('6213'),
    '收到你的訊息：6213\nAI 台股投資系統正在建置中。');
});

test('stock 2330 records a report-compatible sender independently of reply claim',async()=>{
  const {handler,logs,replies,queries,replyStates}=mock();
  const res=await handler(signedRequest([message('2330')]));
  assert.equal(res.status,200);
  assert.deepEqual(logs,[{
    event_id:'evt-1',line_user_id:'U-test-not-a-real-user',
    message_type:'text',message_text:'2330'
  }]);
  assert.match(replies[0].body,/2330 台積電/u);
  assert.match(replies[0].body,/2026-10-30/u);
  assert.deepEqual(queries[0].args,['2330']);
  assert.equal(replyStates.get('evt-1').state,'sent');
});

test('list, rank, excluded 1808 and old fallback are routed separately',async()=>{
  const {handler,replies,logs}=mock();
  const inputs=['清單','1','1808','你好'];
  for(let i=0;i<inputs.length;i++){
    assert.equal((await handler(signedRequest([message(inputs[i],'evt-'+i)]))).status,200);
  }
  assert.match(replies[0].body,/評分觀察清單/u);
  assert.match(replies[1].body,/清單編號 1/u);
  assert.match(replies[2].body,/1808 已依設定排除/u);
  assert.equal(replies[3].body,'收到你的訊息：你好\nAI 台股投資系統正在建置中。');
  assert.equal(logs.length,4);
});

test('invalid signature cannot write records, query DB or send LINE reply',async()=>{
  const {handler,logs,replies,queries}=mock();
  const r=await handler(signedRequest([message('2330')],'bad'));
  assert.equal(r.status,401);
  assert.equal(logs.length,0);
  assert.equal(replies.length,0);
  assert.equal(queries.length,0);
});

test('group, follow, nontext and standby events are not enrolled or replied',async()=>{
  const {handler,logs,replies}=mock();
  const events=[
    message('2330','evt-group',{source:{type:'group',groupId:'G-test'}}),
    {type:'follow',webhookEventId:'evt-follow',replyToken:'token',source:{type:'user',userId:'U-test'}},
    {type:'message',webhookEventId:'evt-image',replyToken:'token',source:{type:'user',userId:'U-test'},message:{type:'image'}},
    message('2330','evt-standby',{mode:'standby'})
  ];
  assert.equal((await handler(signedRequest(events))).status,200);
  assert.equal(logs.length,0);
  assert.equal(replies.length,0);
});

test('redelivered already-sent event neither duplicates recipient nor sends again',async()=>{
  const {handler,replies,logs}=mock();
  assert.equal((await handler(signedRequest([message('2330')]))).status,200);
  const redelivered=message('2330','evt-1',{deliveryContext:{isRedelivery:true}});
  assert.equal((await handler(signedRequest([redelivered]))).status,200);
  assert.equal(replies.length,1);
  assert.equal(logs.length,1);
});

test('reply failure after inbound INSERT can retry without losing the reply',async()=>{
  let attempts=0;
  const {handler,logs,replyStates}=mock({
    sendReply:async()=>{attempts++; if(attempts===1) throw Error('temporary LINE failure');}
  });
  assert.equal((await handler(signedRequest([message('2330')]))).status,502);
  assert.equal(logs.length,1);
  assert.equal(replyStates.get('evt-1').state,'retryable');
  const redelivered=message('2330','evt-1',{deliveryContext:{isRedelivery:true}});
  assert.equal((await handler(signedRequest([redelivered]))).status,200);
  assert.equal(replyStates.get('evt-1').state,'sent');
  assert.equal(logs.length,1);
  assert.equal(attempts,2);
});

test('3 failed attempts bound retry loop even on further redelivery',async()=>{
  let attempted=0;
  const {handler,replyStates}=mock({
    sendReply:async()=>{attempted++;throw Error('LINE reply fails');}
  });
  for(let i=0;i<3;i++){
    assert.equal((await handler(signedRequest([message('2330')]))).status,502);
  }
  assert.equal(replyStates.get('evt-1').attempts,3);
  assert.equal((await handler(signedRequest([message('2330')]))).status,200);
  assert.equal(attempted,3);
});

test('in-progress claim prevents concurrent duplicate send and requests redelivery',async()=>{
  const m=mock();
  m.replyStates.set('evt-1',{state:'sending',attempts:1,attemptKey:'active'});
  assert.equal((await m.handler(signedRequest([message('2330')]))).status,503);
  assert.equal(m.replies.length,0);
});

test('expired original reply token is not attempted but direct user is enrolled',async()=>{
  const m=mock();
  const expired=message('2330','evt-1',{timestamp:TIME-21*60*1000});
  assert.equal((await m.handler(signedRequest([expired]))).status,200);
  assert.equal(m.logs.length,1);
  assert.equal(m.replies.length,0);
  assert.equal(m.replyStates.size,0);
});

test('recording errors fail closed before any LINE reply',async()=>{
  const base=mock();
  const store={...base.store,recordInbound:async()=>{throw Error('private database details')}};
  const {handler,replies}=mock({store});
  const r=await handler(signedRequest([message('2330')]));
  assert.equal(r.status,502);
  assert.equal(replies.length,0);
  assert.doesNotMatch(await r.text(),/private/u);
});

test('acknowledgement failure is explicitly unconfirmed, not reported as success',async()=>{
  const base=mock();
  const store={...base.store,completeReply:async()=>{throw Error('db update failed')}};
  const {handler,replies}=mock({store});
  const r=await handler(signedRequest([message('2330')]));
  assert.equal(r.status,502);
  assert.equal(replies.length,1);
  assert.match(await r.text(),/unconfirmed/u);
});

test('missing event ID or store fail closed; health endpoint stays available',async()=>{
  const m=mock();
  assert.equal((await m.handler(signedRequest([message('2330',undefined,{webhookEventId:undefined})]))).status,400);
  assert.equal(m.logs.length,0);
  const disabled=mock({store:undefined});
  // undefined override uses the default store; explicit null is required.
  const missing=mock({store:null});
  assert.equal((await missing.handler(signedRequest([message('2330')]))).status,503);
  assert.equal((await missing.handler(new Request('https://test.invalid/health'))).status,200);
});
