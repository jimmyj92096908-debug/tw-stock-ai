import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import {
  createSingleAccountGateway, isStockCommandEvent
} from '../single-account-gateway.mjs';
import { verifyLineSignature } from '../handler.mjs';
import { validateLegacyWebhookUrl } from '../single-account-entry.mjs';

function textEvent(text,id='e1',source={type:'user',userId:'U-fake'}){
  return {type:'message',source,webhookEventId:id,timestamp:1770000000000,
    replyToken:'fake-'+id,message:{type:'text',text}};
}
function signed(payload) {
  const body=JSON.stringify(payload);
  const signature=createHmac('sha256','fake-gateway-secret').update(body).digest('base64');
  const request=new Request('https://example.test/webhook',{
    method:'POST',headers:{
      'content-type':'application/json','x-line-signature':signature
    },body
  });
  return {request,body,signature};
}
function harness(stockImpl,legacyImpl){
  const stockCalls=[],legacyCalls=[],order=[];
  const handler=createSingleAccountGateway({
    channelSecret:'fake-gateway-secret',
    stockHandler:async request=>{
      const body=await request.text();
      const signature=request.headers.get('x-line-signature');
      assert.equal(verifyLineSignature(body,signature,'fake-gateway-secret'),true);
      const payload=JSON.parse(body);
      stockCalls.push(payload);
      order.push('stock');
      return stockImpl ? stockImpl(payload) : new Response('OK',{status:200});
    },
    forwardLegacy:async(body,signature)=>{
      assert.equal(verifyLineSignature(body,signature,'fake-gateway-secret'),true);
      legacyCalls.push({body,signature,payload:JSON.parse(body)});
      order.push('legacy');
      return legacyImpl ? legacyImpl(body,signature) : {status:200};
    }
  });
  return {handler,stockCalls,legacyCalls,order};
}

test('route only supported private stock commands to new handler',()=>{
  for(const input of ['2330','股票 6488','清單','1','編號 2','1808']){
    assert.equal(isStockCommandEvent(textEvent(input)),true,input);
  }
  for(const input of ['你好','說明','abc','2330 6488']){
    assert.equal(isStockCommandEvent(textEvent(input)),false,input);
  }
  assert.equal(isStockCommandEvent(textEvent('2330','e1',{type:'group',groupId:'G-fake'})),false);
  assert.equal(isStockCommandEvent({...textEvent('2330'),mode:'standby'}),false);
  assert.equal(isStockCommandEvent({type:'follow'}),false);
});

test('all stock events reach only stock handler and not original webhook',async()=>{
  const {handler,stockCalls,legacyCalls}=harness();
  const {request}=signed({destination:'U-fake-bot',events:[textEvent('2330'),textEvent('清單','e2')]});
  assert.equal((await handler(request)).status,200);
  assert.deepEqual(stockCalls[0].events.map(x=>x.webhookEventId),['e1','e2']);
  assert.equal(legacyCalls.length,0);
});

test('all legacy events retain exact raw bytes, signature and original destination',async()=>{
  const {handler,stockCalls,legacyCalls}=harness();
  const original=signed({destination:'U-fake-bot',events:[
    textEvent('你好'),{type:'follow',webhookEventId:'e2',replyToken:'fake-e2'}
  ]});
  assert.equal((await handler(original.request)).status,200);
  assert.equal(stockCalls.length,0);
  assert.equal(legacyCalls.length,1);
  assert.equal(legacyCalls[0].body,original.body);
  assert.equal(legacyCalls[0].signature,original.signature);
  assert.equal(legacyCalls[0].payload.destination,'U-fake-bot');
});

test('mixed stock/legacy batches are split, re-signed, ordered and not duplicated',async()=>{
  const {handler,stockCalls,legacyCalls,order}=harness();
  const events=[
    textEvent('2330','s1'),textEvent('你好','l1'),
    textEvent('清單','s2'),textEvent('2330','l2',{type:'group',groupId:'G-test'}),
    {type:'follow',webhookEventId:'l3'}
  ];
  const {request}=signed({destination:'U-fake-bot',events});
  assert.equal((await handler(request)).status,200);
  assert.deepEqual(order,['stock','legacy']);
  assert.deepEqual(stockCalls[0].events.map(x=>x.webhookEventId),['s1','s2']);
  assert.deepEqual(legacyCalls[0].payload.events.map(x=>x.webhookEventId),['l1','l2','l3']);
  assert.equal(legacyCalls[0].payload.destination,'U-fake-bot');
});

test('bad external signature is rejected before either backend is called',async()=>{
  const {handler,stockCalls,legacyCalls}=harness();
  const {body}=signed({events:[textEvent('2330')]});
  const result=await handler(new Request('https://example.test/webhook',{
    method:'POST',
    headers:{'content-type':'application/json','x-line-signature':'tampered'},
    body
  }));
  assert.equal(result.status,401);
  assert.equal(stockCalls.length+legacyCalls.length,0);
});

test('stock failure stops legacy forwarding so whole batch can be redelivered',async()=>{
  const {handler,legacyCalls}=harness(()=>new Response('Temporary',{status:502}));
  const {request}=signed({events:[textEvent('2330'),textEvent('你好','e2')]});
  assert.equal((await handler(request)).status,502);
  assert.equal(legacyCalls.length,0);
});

test('legacy upstream failure results in retryable non-2xx status',async()=>{
  const {handler,stockCalls}=harness(null,()=>({status:500}));
  const {request}=signed({events:[textEvent('2330'),textEvent('你好','e2')]});
  assert.equal((await handler(request)).status,502);
  assert.equal(stockCalls.length,1);
});

test('invalid payloads fail closed and never reach either backend',async()=>{
  const {handler,stockCalls,legacyCalls}=harness();
  const {request}=signed({events:Array.from({length:21},(_,i)=>textEvent('2330','e'+i))});
  assert.equal((await handler(request)).status,400);
  assert.equal(stockCalls.length+legacyCalls.length,0);
});

test('legacy webhook target is pinned to original Neon function, not an arbitrary host',()=>{
  const base='https://br-purple-smoke-a1t9dmzz-linewebhook.compute.c-1.ap-southeast-1.aws.neon.tech';
  assert.equal(validateLegacyWebhookUrl(base),base+'/');
  assert.equal(validateLegacyWebhookUrl(base+'/webhook'),base+'/webhook');
  for(const invalid of [
    '', 'http://'+base.slice(8), 'https://example.org/',
    base+'@evil.example.org/', base+'/?target=https://evil.example.org',
    base+'/unexpected',base+'/#fragment'
  ]) assert.throws(()=>validateLegacyWebhookUrl(invalid));
});

test('stock-like events without a complete LINE reply contract stay on legacy path',async()=>{
  const malformed=[
    textEvent('2330','evt-no-user',{type:'user'}),
    {...textEvent('2330','evt-no-token'),replyToken:undefined},
    {...textEvent('2330','evt-no-id'),webhookEventId:undefined},
    {...textEvent('2330','evt-bad-msg'),message:{type:'text'}},
    {...textEvent('2330','evt-number-msg'),message:{type:'text',text:2330}}
  ];
  for(const event of malformed) {
    assert.equal(isStockCommandEvent(event),false);
  }
  const {handler,legacyCalls,stockCalls}=harness();
  const {request}=signed({events:malformed});
  assert.equal((await handler(request)).status,200);
  assert.equal(stockCalls.length,0);
  assert.equal(legacyCalls.length,1);
  assert.equal(legacyCalls[0].payload.events.length,malformed.length);
});
