import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { createSingleAccountGateway } from '../single-account-gateway.mjs';

const SECRET='fake-canary-test-channel-secret-not-real';
function buildRequest(payload, signature=undefined) {
  const body=JSON.stringify(payload);
  const hmac=signature ?? createHmac('sha256',SECRET).update(body).digest('base64');
  return new Request('https://ci.example.invalid/webhook',{
    method:'POST',headers:{
      'content-type':'application/json',
      'x-line-signature':hmac
    },body
  });
}
function testGateway({enabled=false,secret=SECRET}={}) {
  const calls={stock:0,legacy:0};
  const gateway=createSingleAccountGateway({
    channelSecret:secret,enabled,
    stockHandler:async()=>{
      calls.stock++;
      return new Response('stock',{status:200});
    },
    forwardLegacy:async()=>{
      calls.legacy++;
      return {status:200};
    }
  });
  return {gateway,calls};
}

test('disabled gateway returns 200 only for LINE-signed empty connectivity event',async()=>{
  const {gateway,calls}=testGateway();
  const request=buildRequest({destination:'U-ci-fake-bot',events:[]});
  const result=await gateway(request);
  assert.equal(result.status,200);
  assert.equal(calls.stock,0);
  assert.equal(calls.legacy,0);
});

test('even valid signed stock and legacy events cannot execute while disabled',async()=>{
  const {gateway,calls}=testGateway();
  for(const text of ['2330','模型狀態','清單','你好']){
    const event={
      type:'message',source:{type:'user',userId:'U-not-real'},
      webhookEventId:'test-event',replyToken:'not-real-reply-token',
      message:{type:'text',text}
    };
    const result=await gateway(buildRequest({destination:'U-ci-fake-bot',events:[event]}));
    assert.equal(result.status,503,text);
  }
  assert.equal(calls.stock,0);
  assert.equal(calls.legacy,0);
});

test('unsigned, tampered and malformed empty events fail without reaching backend',async()=>{
  const {gateway,calls}=testGateway();
  const cases=[
    buildRequest({destination:'U-ci-fake-bot',events:[]},'invalid-signature'),
    buildRequest({events:[]}),
    buildRequest({destination:'U-ci-fake-bot',events:null}),
    buildRequest({destination:'U-ci-fake-bot',events:[{}]}),
    buildRequest({destination:'',events:[]}),
  ];
  for(const request of cases){
    assert.equal((await gateway(request)).status,503);
  }
  assert.equal(calls.stock,0);
  assert.equal(calls.legacy,0);
});

test('no channel secret disables even a correctly formed connectivity event',async()=>{
  const {gateway,calls}=testGateway({secret:''});
  assert.equal((await gateway(buildRequest({destination:'U-ci-fake-bot',events:[]}))).status,503);
  assert.equal(calls.stock+calls.legacy,0);
});

test('disabled canary is bounded by original payload byte limit',async()=>{
  const {gateway,calls}=testGateway();
  const large=buildRequest({destination:'x'.repeat(256100),events:[]});
  assert.equal((await gateway(large)).status,413);
  assert.equal(calls.stock+calls.legacy,0);
});

test('enabled gateway retains original empty-event legacy relay behavior',async()=>{
  const {gateway,calls}=testGateway({enabled:true});
  assert.equal((await gateway(buildRequest({destination:'U-ci-fake-bot',events:[]}))).status,200);
  assert.equal(calls.stock,0);
  assert.equal(calls.legacy,1);
});

test('disabled health endpoint still responds without processing any event',async()=>{
  const {gateway,calls}=testGateway();
  assert.equal((await gateway(new Request('https://ci.example.invalid/health'))).status,200);
  assert.equal(calls.stock+calls.legacy,0);
});
