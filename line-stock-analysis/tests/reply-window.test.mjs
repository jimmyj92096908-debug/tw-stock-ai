import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import {
  isReplyTokenEligible, createSingleAccountCandidate
} from '../single-account-candidate.mjs';
import { ANALYSIS_SQL } from '../handler.mjs';

const NOW=Date.parse('2026-11-20T12:00:00Z');

function delivery(text='2330') {
  return {
    type:'message',webhookEventId:'event-reply-window',
    timestamp:NOW-5000,deliveryContext:{isRedelivery:false},
    source:{type:'user',userId:'U-test-only'},
    replyToken:'fake-token',message:{type:'text',text}
  };
}
function signedRequest(events) {
  const body=JSON.stringify({events});
  const signature=createHmac('sha256','test-secret').update(body).digest('base64');
  return new Request('https://test.invalid/webhook',{
    method:'POST',headers:{
      'content-type':'application/json','x-line-signature':signature
    },body
  });
}

test('original event is eligible within receipt window even when timestamp is old',()=>{
  // Unlike redelivery, original reply-token age is measured from receipt.
  const event=delivery();
  event.timestamp=NOW-10*60*1000;
  assert.equal(isReplyTokenEligible(event,NOW,NOW+1000),true);
  assert.equal(isReplyTokenEligible(event,NOW,NOW+49_000),true);
  assert.equal(isReplyTokenEligible(event,NOW,NOW+50_000),false);
});

test('redelivered event has a stricter 20-minute-from-event deadline',()=>{
  const event=delivery();
  event.deliveryContext.isRedelivery=true;
  event.timestamp=NOW-18*60*1000;
  assert.equal(isReplyTokenEligible(event,NOW,NOW+1000),true);
  event.timestamp=NOW-19*60*1000;
  assert.equal(isReplyTokenEligible(event,NOW,NOW+1000),false);
  event.timestamp=undefined;
  assert.equal(isReplyTokenEligible(event,NOW,NOW),false);
  event.timestamp=NOW+120_000;
  assert.equal(isReplyTokenEligible(event,NOW,NOW),false);
});

test('reply window expiration after slow SQL releases claim without sending LINE',async()=>{
  let clock=NOW,recorded=0,claimed=0,released=0,completed=0,replies=0;
  const store={
    recordInbound:async()=>{recorded++;},
    claimReply:async()=>{claimed++;return {acquired:true,attemptKey:'fake-key'};},
    failReply:async()=>{released++;},
    completeReply:async()=>{completed++;}
  };
  const handler=createSingleAccountCandidate({
    channelSecret:'test-secret',now:()=>clock,store,
    query:async(sql,params)=>{
      assert.equal(sql,ANALYSIS_SQL);
      assert.deepEqual(params,['2330']);
      clock+=50_000;
      return {rows:[{market:'twse',stock_id:'2330',stock_name:'台積電',close:1234,price_date:'2026-10-30'}]};
    },
    sendReply:async()=>{replies++;}
  });
  const result=await handler(signedRequest([delivery()]));
  assert.equal(result.status,503);
  assert.equal(await result.text(),'Reply window exceeded');
  assert.equal(recorded,1);
  assert.equal(claimed,1);
  assert.equal(released,1);
  assert.equal(completed,0);
  assert.equal(replies,0);
});

test('expired redelivery retains report enrollment but never claims reply token',async()=>{
  let recorded=0,claims=0,replies=0;
  const event=delivery();
  event.deliveryContext.isRedelivery=true;
  event.timestamp=NOW-21*60*1000;
  const handler=createSingleAccountCandidate({
    channelSecret:'test-secret',now:()=>NOW,
    store:{
      recordInbound:async()=>{recorded++;},
      claimReply:async()=>{claims++;throw Error('should not claim');},
      completeReply:async()=>{},
      failReply:async()=>{}
    },
    query:async()=>{throw Error('query must not run');},
    sendReply:async()=>{replies++;}
  });
  assert.equal((await handler(signedRequest([event]))).status,200);
  assert.equal(recorded,1);
  assert.equal(claims,0);
  assert.equal(replies,0);
});
