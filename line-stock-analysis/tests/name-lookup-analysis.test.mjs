import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import {
  parseStockCode, STOCK_NAME_SQL, ANALYSIS_SQL, buildReplyText,
  formatStockAnalysis, verifyLineSignature
} from '../handler.mjs';
import { createSingleAccountGateway, isStockCommandEvent } from '../single-account-gateway.mjs';
import { createSingleAccountCandidate } from '../single-account-candidate.mjs';
import { isApprovedStockReadQuery } from '../single-account-entry.mjs';

const SECRET='fake-line-name-test-not-production-secret';
const NOW=Date.parse('2026-11-20T09:00:00Z');
const named={market:'twse',stock_id:'6213',stock_name:'聯茂'};
function event(text,id='evt-stock') {
  return {type:'message',source:{type:'user',userId:'U-simulated-only'},
    webhookEventId:id,replyToken:'fake-'+id,timestamp:NOW,
    message:{type:'text',text}};
}
function signed(events,signatureOverride) {
  const body=JSON.stringify({destination:'U-not-a-real-bot',events});
  const signature=signatureOverride??createHmac('sha256',SECRET).update(body).digest('base64');
  return new Request('https://test.invalid/webhook',{
    method:'POST',headers:{'x-line-signature':signature,'content-type':'application/json'},
    body
  });
}
const stockRow={
  ...named,price_date:'2026-11-19',market_latest_date:'2026-11-19',
  open:'430',high:'435',low:'395',close:'395',price_change:'-43.5',volume:10757913,
  high20:'885',low20:'395',high60:'885',low60:'395',
  technical_date:'2026-11-19',ma5:'455.7',ma10:'493.55',
  ma13:'520',ma20:'595.53',ma34:'600',ma55:'605',ma60:'607.77',
  ma120:'471.1',ma240:'315.73',rsi14:'29.93',atr14:'58.96',
  volume_ma5:'17663923',volume_ma20:'19797043',
  smc_date:'2026-11-19',trend_direction:-1,
  bos_bullish:false,bos_bearish:false,choch_bullish:false,choch_bearish:false,
  liquidity_sweep_high:false,liquidity_sweep_low:false,
  order_block_type:null,fvg_type:null,score_date:'2026-11-19',
  total_score:'32.33',coverage_weight:'0.60',technical_score:'30.42',
  smc_score:'35',short_term_score:'28.12',swing_score:'22.50',
  long_term_score:'34.06',chip_score:null
};
function stubQuery(sql,params) {
  if(sql===STOCK_NAME_SQL) {
    assert.equal(params.length,1);
    return {rows:params[0]==='聯茂'?[named]:[]};
  }
  if(sql===ANALYSIS_SQL) {
    assert.deepEqual(params,['6213']);
    return {rows:[stockRow]};
  }
  throw Error('Unexpected test SQL');
}

test('parse exact four-digit stock codes and Chinese stock names',()=>{
  for(const text of ['6213','分析6213','股票 6213']) {
    assert.deepEqual(parseStockCode(text),{kind:'stock',code:'6213'});
  }
  assert.deepEqual(parseStockCode('聯茂'),{kind:'name',name:'聯茂',explicit:false});
  assert.deepEqual(parseStockCode('分析 聯茂'),{kind:'name',name:'聯茂',explicit:true});
  assert.deepEqual(parseStockCode('股票台積電'),{kind:'name',name:'台積電',explicit:true});
  assert.deepEqual(parseStockCode('M31'),{kind:'name',name:'M31',explicit:false});
  assert.deepEqual(parseStockCode('分析 M31'),{kind:'name',name:'M31',explicit:true});
  assert.deepEqual(parseStockCode('AES-KY'),{kind:'name',name:'AES-KY',explicit:false});
  assert.equal(parseStockCode('ABC').kind,'invalid');
  assert.equal(parseStockCode('研究報告').kind,'research');
  assert.equal(parseStockCode('清單').kind,'list');
  for(const text of ['6213;DROP','聯茂 OR 1=1','12345','0050','聯茂 台積電']) {
    assert.equal(parseStockCode(text).kind,'invalid',text);
  }
});

test('exact stock name SQL is allowlisted and parameterized, never fuzzy or writing',()=>{
  assert.equal(isApprovedStockReadQuery(STOCK_NAME_SQL),true);
  assert.match(STOCK_NAME_SQL,/BTRIM\(stock_name\) = \$1/u);
  assert.match(STOCK_NAME_SQL,/LIMIT 6/u);
  assert.doesNotMatch(STOCK_NAME_SQL,/ILIKE|LIKE|INSERT|UPDATE|DELETE|line_messages/iu);
  assert.equal(isApprovedStockReadQuery(STOCK_NAME_SQL+'; DROP TABLE x'),false);
});

test('stock 6213 and name 聯茂 resolve to same complete database analysis',async()=>{
  const fromCode=await buildReplyText('6213',async(sql,args)=>stubQuery(sql,args));
  const fromName=await buildReplyText('聯茂',async(sql,args)=>stubQuery(sql,args));
  const prefixed=await buildReplyText('分析 聯茂',async(sql,args)=>stubQuery(sql,args));
  assert.equal(fromName.replace('名稱查詢｜',''),fromCode);
  assert.equal(prefixed,fromName);
  for(const indicator of ['6213 聯茂','2026-11-19','395.00','MA240',
     'RSI14','ATR14','SMC','空方','總分：32.3','32.3','籌碼資料不足',
     '短中期偏弱','偏超賣','波動','20 交易日實際低／高']) {
    assert.match(fromName,new RegExp(indicator,'u'),indicator);
  }
  assert.match(fromName,/非買賣指令/u);
  assert.ok(fromName.length<4900);
});

test('English-name stocks M31 and AES-KY need exact DB membership',async()=>{
  const equities={
    M31:{market:'tpex',stock_id:'6643',stock_name:'M31'},
    'AES-KY':{market:'twse',stock_id:'6781',stock_name:'AES-KY'}
  };
  for(const name of Object.keys(equities)){
    const r=await buildReplyText(name,async(sql,params)=>{
      if(sql===STOCK_NAME_SQL) return {rows:[equities[params[0]]]};
      assert.equal(sql,ANALYSIS_SQL);
      assert.deepEqual(params,[equities[name].stock_id]);
      return {rows:[{...stockRow,...equities[name]}]};
    });
    assert.ok(r.includes(name));
    assert.match(r,new RegExp(equities[name].stock_id,'u'));
  }
});

test('missing, repeated and excluded stock names fail closed',async()=>{
  const missing=await buildReplyText('不存在公司',async(sql,params)=>{
    assert.equal(sql,STOCK_NAME_SQL);
    assert.deepEqual(params,['不存在公司']);
    return {rows:[]};
  });
  assert.match(missing,/找不到/u);
  const multi=await buildReplyText('分析 重名公司',async(sql)=>({
    rows:[{market:'twse',stock_id:'1234'},{market:'tpex',stock_id:'5678'}]
  }));
  assert.match(multi,/對應多筆股票/u);
  assert.match(multi,/1234/u);
  const excluded=await buildReplyText('分析 排除股',async()=>({
    rows:[{market:'twse',stock_id:'1808'}]
  }));
  assert.match(excluded,/已依設定排除/u);
});

test('stale stock and missing score are explicitly marked; no fake data',()=>{
  const stale=formatStockAnalysis({...stockRow,price_date:'2026-11-18',
    market_latest_date:'2026-11-19',score_date:'2026-11-17'});
  assert.match(stale,/落後市場最新交易日/u);
  assert.match(stale,/指標日期與收盤交易日不同/u);
  const noData=formatStockAnalysis({...stockRow,close:null});
  assert.match(noData,/無法產生分析/u);
  const noIndicators=formatStockAnalysis({...stockRow,
    technical_date:null,smc_date:null,score_date:null,total_score:null,
    low20:null,high20:null});
  assert.match(noIndicators,/尚無技術指標/u);
  assert.match(noIndicators,/尚無 SMC/u);
  assert.match(noIndicators,/尚無達可用條件/u);
});

test('verified bare names route to stock, normal chat and group stay legacy',async()=>{
  const calls=[],replies=[],legacy=[],nameQueries=[];
  const store={
    async recordInbound(x){calls.push(x);},
    async claimReply(id){return {acquired:true,attemptKey:'fake-claim'};},
    async completeReply(){},async failReply(){}
  };
  const lookupExactStockName=async name=>{
    nameQueries.push(name);
    return name==='聯茂';
  };
  const stockHandler=createSingleAccountCandidate({
    query:async(sql,params)=>stubQuery(sql,params),
    lookupExactStockName,store,channelSecret:SECRET,
    now:()=>NOW,sendReply:async(token,message)=>replies.push({token,message})
  });
  const gateway=createSingleAccountGateway({
    channelSecret:SECRET,stockHandler,lookupExactStockName,
    forwardLegacy:async(body,signature)=>{
      assert.equal(verifyLineSignature(body,signature,SECRET),true);
      legacy.push(JSON.parse(body).events.map(x=>x.message?.text||x.type));
      return {status:200};
    }
  });
  const mixed=[event('聯茂','stock1'),event('分析 聯茂','stock2'),
    event('你好','chat1'),event('不存在','chat2'),
    {...event('聯茂','group1'),source:{type:'group',groupId:'G-test'}}];
  const res=await gateway(signed(mixed));
  assert.equal(res.status,200);
  assert.equal(replies.length,2);
  assert.equal(calls.length,2);
  assert.match(replies[0].message,/名稱查詢｜台股資料分析/u);
  assert.match(replies[1].message,/6213 聯茂/u);
  assert.deepEqual(legacy,[['你好','不存在','聯茂']]);
  assert.ok(nameQueries.includes('聯茂'));
  assert.ok(nameQueries.includes('你好'));
  assert.equal(isStockCommandEvent(event('分析 聯茂')),true);
  assert.equal(isStockCommandEvent(event('聯茂')),false);
  assert.equal(isStockCommandEvent(event('你好')),false);
});

test('bare-name query failure is retryable; invalid signature never hits DB',async()=>{
  let lookups=0,stocks=0,legacy=0;
  const gateway=createSingleAccountGateway({
    channelSecret:SECRET,
    lookupExactStockName:async()=>{lookups++;throw Error('secret database detail');},
    stockHandler:async()=>{stocks++;return new Response('ok');},
    forwardLegacy:async()=>{legacy++;return {status:200}}
  });
  const unknown=await gateway(signed([event('聯茂')]));
  assert.equal(unknown.status,502);
  assert.doesNotMatch(await unknown.text(),/secret database detail/u);
  assert.equal(stocks+legacy,0);
  const bad=await gateway(signed([event('聯茂')],'tampered'));
  assert.equal(bad.status,401);
  assert.equal(lookups,1);
  assert.equal(stocks+legacy,0);
});
