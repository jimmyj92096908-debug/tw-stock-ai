import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { createSingleAccountCandidate, observedLegacyReply } from '../single-account-candidate.mjs';
import { ANALYSIS_SQL, RANKING_SQL } from '../handler.mjs';

function message(text, id='evt-1', extras={}) {
  return {
    type:'message', webhookEventId:id,
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
  const logs=[], replies=[], queries=[];
  const handler = createSingleAccountCandidate({
    channelSecret:'mock-secret',
    query:async(sql,args)=>{
      queries.push({sql,args});
      if(sql===RANKING_SQL) return {rows:ranking};
      if(sql===ANALYSIS_SQL) return {rows:[{...sample,stock_id:args[0]}]};
      throw new Error('unexpected SQL');
    },
    recordMessage:async row=>{logs.push(row);return true;},
    sendReply:async(token,body)=>{replies.push({token,body});},
    ...override
  });
  return {handler,logs,replies,queries};
}

test('observed fallback matches screenshot and never invents stock analysis',()=>{
  assert.equal(observedLegacyReply('6213'),
    '收到你的訊息：6213\nAI 台股投資系統正在建置中。');
});

test('single account direct text 2330 records report-compatible recipient and analyzes stock',async()=>{
  const {handler,logs,replies,queries}=mock();
  const res=await handler(signedRequest([message('2330')]));
  assert.equal(res.status,200);
  assert.deepEqual(logs,[{
    event_id:'evt-1',line_user_id:'U-test-not-a-real-user',
    message_type:'text',message_text:'2330'
  }]);
  assert.match(replies[0].body,/2330 台積電/u);
  assert.match(replies[0].body,/2026-10-30/u);
  assert.equal(queries.length,1);
  assert.deepEqual(queries[0].args,['2330']);
});

test('list, rank and excluded 1808 use new stock handling while unknown text gets observed old reply',async()=>{
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

test('group, follow and nontext events are not guessed or enrolled in daily report',async()=>{
  const {handler,logs,replies}=mock();
  const events=[
    message('2330','evt-group',{source:{type:'group',groupId:'G-test'}}),
    {type:'follow',webhookEventId:'evt-follow',replyToken:'token',source:{type:'user',userId:'U-test'}},
    {type:'message',webhookEventId:'evt-image',replyToken:'token',source:{type:'user',userId:'U-test'},message:{type:'image'}}
  ];
  assert.equal((await handler(signedRequest(events))).status,200);
  assert.equal(logs.length,0);
  assert.equal(replies.length,0);
});

test('duplicate event is not replied twice if database adapter reports conflict',async()=>{
  let insertCalls=0;
  const {handler,replies}=mock({recordMessage:async()=>++insertCalls===1});
  assert.equal((await handler(signedRequest([message('2330')]))).status,200);
  assert.equal((await handler(signedRequest([message('2330')]))).status,200);
  assert.equal(replies.length,1);
});

test('database log failures do not trigger LINE replies and are surfaced as retryable errors',async()=>{
  const {handler,replies}=mock({recordMessage:async()=>{throw Error('private connection info');}});
  const r=await handler(signedRequest([message('2330')]));
  assert.equal(r.status,502);
  assert.equal(replies.length,0);
  assert.doesNotMatch(await r.text(),/private connection/u);
});

test('missing LINE secret disables integration without exposing stored records',async()=>{
  const {handler,replies}=mock({channelSecret:''});
  assert.equal((await handler(signedRequest([message('2330')]))).status,503);
  assert.equal(replies.length,0);
});
