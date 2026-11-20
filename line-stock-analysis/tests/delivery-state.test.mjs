import test from 'node:test';
import assert from 'node:assert/strict';
import {
  createDeliveryStore, RECORD_INBOUND_SQL, CLAIM_REPLY_SQL,
  READ_REPLY_STATE_SQL, COMPLETE_REPLY_SQL, FAIL_REPLY_SQL
} from '../delivery-state.mjs';

test('recordInbound writes only required report fields using bound parameters',async()=>{
  const calls=[];
  const store=createDeliveryStore(async(sql,params)=>{
    calls.push({sql,params});return {rows:[]};
  });
  await store.recordInbound({
    event_id:'test-event-id',line_user_id:'U-no-real-user',
    message_type:'text',message_text:"2330'; DROP TABLE public.line_messages; --"
  });
  assert.equal(calls.length,1);
  assert.equal(calls[0].sql,RECORD_INBOUND_SQL);
  assert.deepEqual(calls[0].params,[
    'test-event-id','U-no-real-user',"2330'; DROP TABLE public.line_messages; --"
  ]);
  assert.match(calls[0].sql,/ON CONFLICT \(event_id\) DO NOTHING/u);
  assert.match(calls[0].sql,/\$1.*\$2.*\$3/su);
  assert.doesNotMatch(calls[0].sql,/DROP TABLE/u);
});

test('cannot enroll invalid event or non-text message',async()=>{
  const store=createDeliveryStore(async()=>{throw Error('should not query')});
  await assert.rejects(store.recordInbound({message_type:'image'}),/Invalid/u);
  await assert.rejects(store.recordInbound({event_id:'',line_user_id:'user',message_type:'text',message_text:'2330'}),/Invalid/u);
});

test('claimReply atomically obtains a lease with bounded retries',async()=>{
  const calls=[];
  const store=createDeliveryStore(async(sql,params)=>{
    calls.push({sql,params});
    if(sql===CLAIM_REPLY_SQL)return {rows:[{attempt_key:params[1],attempts:1}]};
    throw Error('unexpected query');
  },{newAttemptKey:()=>'11111111-1111-4111-8111-111111111111'});
  const reply=await store.claimReply('test-event-id');
  assert.deepEqual(reply,{
    acquired:true,attemptKey:'11111111-1111-4111-8111-111111111111'
  });
  assert.deepEqual(calls[0].params,['test-event-id','11111111-1111-4111-8111-111111111111']);
  assert.match(CLAIM_REPLY_SQL,/ON CONFLICT \(event_id\) DO UPDATE/u);
  assert.match(CLAIM_REPLY_SQL,/attempts < 3/u);
  assert.match(CLAIM_REPLY_SQL,/lease_until < NOW\(\)/u);
  assert.match(CLAIM_REPLY_SQL,/RETURNING event_id, attempt_key, attempts/u);
});

test('previously sent, busy, exhausted replies are never claimed',async()=>{
  for(const [state,attempts,reason] of [
    ['sent',1,'sent'],['sending',1,'busy'],['retryable',3,'exhausted']
  ]){
    const store=createDeliveryStore(async(sql,params)=>{
      assert.equal(params[0],'evt');
      if(sql===CLAIM_REPLY_SQL)return {rows:[]};
      assert.equal(sql,READ_REPLY_STATE_SQL);
      return {rows:[{state,attempts}]};
    },{newAttemptKey:()=>'00000000-0000-4000-8000-000000000000'});
    assert.deepEqual(await store.claimReply('evt'),{acquired:false,reason});
  }
});

test('confirm and failure state transitions require the active attempt key',async()=>{
  const calls=[];
  const store=createDeliveryStore(async(sql,params)=>{
    calls.push({sql,params});
    return {rows:[{event_id:'evt'}]};
  });
  await store.completeReply('evt','attempt1');
  await store.failReply('evt','attempt2');
  assert.deepEqual(calls,[
    {sql:COMPLETE_REPLY_SQL,params:['evt','attempt1']},
    {sql:FAIL_REPLY_SQL,params:['evt','attempt2']}
  ]);
  assert.match(COMPLETE_REPLY_SQL,/state = 'sent'/u);
  assert.match(FAIL_REPLY_SQL,/state = 'retryable'/u);
  for(const sql of [COMPLETE_REPLY_SQL,FAIL_REPLY_SQL])
    assert.match(sql,/attempt_key = \$2::uuid AND state = 'sending'/u);
});

test('if completion cannot be persisted, do not assert delivery succeeded',async()=>{
  const store=createDeliveryStore(async()=>({rows:[]}));
  await assert.rejects(store.completeReply('evt','attempt1'),/Could not confirm/u);
  await assert.rejects(store.failReply('evt','attempt1'),/Could not release/u);
});

test('invalid claim IDs and absent SQL executor are rejected',async()=>{
  assert.throws(()=>createDeliveryStore(null),/SQL executor/u);
  const store=createDeliveryStore(async()=>({rows:[]}));
  await assert.rejects(store.claimReply(''),/Webhook event ID/u);
});
