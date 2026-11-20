import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { parseStockCode, buildReplyText, verifyLineSignature } from '../handler.mjs';
import { createSingleAccountGateway, isStockCommandEvent } from '../single-account-gateway.mjs';
import { formatResearchModelStatus, RESEARCH_REPORT_URL } from '../research-model-status.mjs';
import model from '../../models/tw-factor-ridge-1-research.json' with { type:'json' };
import report from '../../models/tw-factor-ridge-1-evaluation.json' with { type:'json' };

const SECRET='fake-not-a-line-channel-secret';
function event(text,id='research-e1') {
  return {
    type:'message',source:{type:'user',userId:'U-not-real-user'},
    webhookEventId:id,replyToken:'fake-token-'+id,
    message:{type:'text',text}
  };
}
function request(events){
  const body=JSON.stringify({destination:'U-not-real-bot',events});
  return new Request('https://example.invalid/webhook',{
    method:'POST',
    headers:{'content-type':'application/json','x-line-signature':
      createHmac('sha256',SECRET).update(body).digest('base64')},
    body
  });
}

test('saved research evidence explicitly failed real holdout',()=>{
  const result=formatResearchModelStatus();
  assert.match(result,/tw-factor-ridge-1/u);
  assert.match(result,/未通過/u);
  assert.match(result,/-2\.11/u);
  assert.match(result,/不是|非即時/u);
  assert.ok(result.includes(RESEARCH_REPORT_URL));
  assert.equal(report.live_trading_approved,false);
  assert.equal(report.holdout_research_gate_passed,false);
  assert.equal(report.holdout_is_pristine_independent_validation,false);
  assert.equal(model.may_send_trade_signals,false);
  assert.ok(result.length<4900);
});

test('no research report exists if held-out evaluation claims release',()=>{
  for(const falsified of [
    {...report,holdout_research_gate_passed:true},
    {...report,live_trading_approved:true},
    {...report,line_signal_delivery_approved:true},
    {...report,model_version:'incompatible-version'},
    {...report,holdout_is_pristine_independent_validation:true},
    {...report,holdout:{...report.holdout,model_mean_net_excess:null}},
  ]) {
    const answer=formatResearchModelStatus(falsified,model);
    assert.match(answer,/暫不提供/u);
    assert.equal(answer.includes(RESEARCH_REPORT_URL),false);
  }
});

test('research commands require no database query and cannot generate buy signals',async()=>{
  for(const input of ['模型狀態','研究模型','研究報告','AI模型']){
    assert.equal(parseStockCode(input).kind,'research',input);
    let count=0;
    const reply=await buildReplyText(input,async()=>{count++;throw Error('Should not query');});
    assert.equal(count,0);
    assert.match(reply,/績效驗收：未通過/u);
    assert.match(reply,/不可提供買賣訊號/u);
  }
});

test('signed private research command is kept away from legacy, other events are untouched',async()=>{
  const stock=[],old=[];
  const gateway=createSingleAccountGateway({
    channelSecret:SECRET,
    stockHandler:async request=>{
      const raw=await request.text();
      assert.ok(verifyLineSignature(raw,request.headers.get('x-line-signature'),SECRET));
      stock.push(JSON.parse(raw));
      return new Response('OK',{status:200});
    },
    forwardLegacy:async (body,sig)=>{
      assert.ok(verifyLineSignature(body,sig,SECRET));
      old.push(JSON.parse(body));
      return {status:200};
    }
  });
  const userEvent=event('研究報告','r1');
  const oldEvent=event('你好','l1');
  const groupEvent={...event('模型狀態','g1'),source:{type:'group',groupId:'G-not-real'}};
  assert.ok(isStockCommandEvent(userEvent));
  assert.ok(!isStockCommandEvent(groupEvent));
  assert.equal((await gateway(request([userEvent,oldEvent,groupEvent]))).status,200);
  assert.deepEqual(stock[0].events.map(e=>e.webhookEventId),['r1']);
  assert.deepEqual(old[0].events.map(e=>e.webhookEventId),['l1','g1']);
});

test('invalid external signature cannot reach research or legacy handler',async()=>{
  let attempts=0;
  const gateway=createSingleAccountGateway({
    channelSecret:SECRET,
    stockHandler:async()=>{attempts++;return new Response('OK');},
    forwardLegacy:async()=>{attempts++;return {status:200};}
  });
  const raw=JSON.stringify({events:[event('研究報告')]});
  const response=await gateway(new Request('https://example.invalid/webhook',{
    method:'POST',headers:{'x-line-signature':'invalid'},body:raw
  }));
  assert.equal(response.status,401);
  assert.equal(attempts,0);
});

test('research status cannot accidentally be enabled as an actual trading signal',()=>{
  const tampered={...model,production_release_approved:true};
  assert.match(formatResearchModelStatus(report,tampered),/暫不提供/u);
});
