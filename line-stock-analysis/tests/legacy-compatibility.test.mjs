import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { planLineEvent } from '../legacy-compatibility.mjs';
import { createWebhookHandler, ANALYSIS_SQL, RANKING_SQL } from '../handler.mjs';

const stockRow = {
  market:'twse',stock_id:'2330',stock_name:'台積電',price_date:'2026-10-30',
  close:'1500.5',price_change:'10',volume:42000000,technical_date:'2026-10-30',
  ma5:'1490',ma10:'1480',ma13:'1470',ma20:'1460',ma34:'1450',
  ma55:'1440',ma60:'1430',ma120:'1420',ma240:'1410',rsi14:'60',
  atr14:'30',smc_date:'2026-10-30',trend_direction:1,
  score_date:'2026-10-30',total_score:'43.18',coverage_weight:'0.65'
};
const ranks = [
  { market:'twse',stock_id:'2330',stock_name:'台積電',total_score:43.18,as_of_date:'2026-11-18' },
  { market:'tpex',stock_id:'6488',stock_name:'環球晶',total_score:40,as_of_date:'2026-11-18' }
];
function textEvent(message, extra = {}) {
  return {
    type:'message',webhookEventId:'test-webhook-event-1',
    source:{type:'user',userId:'U-fake-only'},
    message:{type:'text',text:message},replyToken:'fake-reply-token',
    ...extra
  };
}
function signed(event) {
  const body=JSON.stringify({events:[event]});
  const sig=createHmac('sha256','simulated-secret').update(body).digest('base64');
  return new Request('https://test.invalid/webhook',{
    method:'POST',headers:{'x-line-signature':sig,'content-type':'application/json'},body
  });
}

test('draft preserves daily report enrollment shape for direct user text',()=>{
  const r=planLineEvent(textEvent('2330'));
  assert.equal(r.route,'stock');
  assert.deepEqual(r.record,{
    event_id:'test-webhook-event-1',line_user_id:'U-fake-only',
    message_type:'text',message_text:'2330'
  });
  assert.equal(planLineEvent(textEvent('清單')).route,'stock');
  assert.equal(planLineEvent(textEvent('1')).route,'stock');
  assert.equal(planLineEvent(textEvent('1808')).route,'stock');
});

test('draft keeps unknown commands and non-text events on legacy path',()=>{
  assert.equal(planLineEvent(textEvent('舊版特殊指令')).route,'legacy');
  assert.equal(planLineEvent(textEvent('說明')).route,'legacy');
  assert.deepEqual(planLineEvent({type:'follow',webhookEventId:'follow'}),{
    route:'legacy',record:null
  });
  assert.deepEqual(planLineEvent({type:'message',message:{type:'image'}}),{
    route:'legacy',record:null
  });
});

test('draft must not enroll group messages or events without stable IDs',()=>{
  assert.equal(planLineEvent(textEvent('2330',{source:{type:'group',groupId:'G-fake'}})).record,null);
  assert.equal(planLineEvent(textEvent('2330',{webhookEventId:undefined})).record,null);
});

test('fake signed LINE request simulates stock, ranking and excluded replies without sending to LINE',async()=>{
  const replies=[];
  const queries=[];
  const handler=createWebhookHandler({
    channelSecret:'simulated-secret',
    query:async(sql,params)=>{
      queries.push([sql,params]);
      if(sql===RANKING_SQL) return {rows:ranks};
      if(sql===ANALYSIS_SQL) return {rows:[{...stockRow,stock_id:params[0]}]};
      throw Error('Unexpected SQL');
    },
    sendReply:async(_replyToken,msg)=>replies.push(msg)
  });
  for(const input of ['2330','清單','1','1808']) {
    const reply=await handler(signed(textEvent(input)));
    assert.equal(reply.status,200,input);
  }
  assert.match(replies[0],/2330 台積電/u);
  assert.match(replies[0],/2026-10-30/u);
  assert.match(replies[0],/超過 7 日/u);
  assert.match(replies[1],/評分觀察清單/u);
  assert.match(replies[2],/清單編號 1/u);
  assert.match(replies[3],/1808 已依設定排除/u);
  assert.deepEqual(queries.filter(([sql])=>sql===ANALYSIS_SQL).map(([,params])=>params),[['2330'],['2330']]);
  assert.equal(queries.filter(([sql])=>sql===RANKING_SQL).length,2);
  // sendReply is an in-memory stub; no LINE account or live DB is contacted.
});

test('fake invalid LINE signature produces no DB access and no reply',async()=>{
  let sideEffects=0;
  const handler=createWebhookHandler({
    channelSecret:'simulated-secret',
    query:async()=>{sideEffects++;return {rows:[]};},
    sendReply:async()=>{sideEffects++;}
  });
  const result=await handler(new Request('https://test.invalid/webhook',{
    method:'POST',headers:{'content-type':'application/json','x-line-signature':'invalid'},
    body:JSON.stringify({events:[textEvent('2330')]})
  }));
  assert.equal(result.status,401);
  assert.equal(sideEffects,0);
});
