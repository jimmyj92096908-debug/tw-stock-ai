import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import candidate, {
  scopedStockUrl, candidateDatabaseUrls, isApprovedStockReadQuery, relayLegacy
} from '../single-account-entry.mjs';
import { ANALYSIS_SQL, RANKING_SQL, DATA_STATUS_SQL, STOCK_NAME_SQL, STANDALONE_CHIP_SQL } from '../handler.mjs';

test('separate read/write database URLs are forced to twstock without dropping TLS params',()=>{
  const url=new URL(scopedStockUrl(
    'postgresql://reader:opaque%21secret@db.example.test/neondb?sslmode=require&application_name=tests'
  ));
  assert.equal(url.pathname,'/twstock');
  assert.equal(url.searchParams.get('sslmode'),'require');
  assert.equal(url.username,'reader');
  assert.equal(url.host,'db.example.test');
  assert.throws(()=>scopedStockUrl(''),/Dedicated database URL/u);
  assert.throws(()=>scopedStockUrl('https://example.test'),/PostgreSQL/u);
});

test('LINE candidate requires exact separate reader and delivery PostgreSQL users',()=>{
  const make=(user)=>'postgresql://'+user+':opaque%21password@db.example.test/postgres?sslmode=require&channel_binding=require';
  const configured=candidateDatabaseUrls(
    make('line_stock_reader'),make('line_stock_delivery')
  );
  const read=new URL(configured.read), delivery=new URL(configured.delivery);
  assert.equal(read.username,'line_stock_reader');
  assert.equal(delivery.username,'line_stock_delivery');
  assert.equal(read.pathname,'/twstock');
  assert.equal(delivery.pathname,'/twstock');
  assert.equal(read.searchParams.get('sslmode'),'require');
  assert.equal(delivery.searchParams.get('channel_binding'),'require');
  assert.equal(read.password,'opaque%21password');

  for (const [readUrl,writeUrl] of [
    [make('postgres'),make('line_stock_delivery')],
    [make('line_stock_delivery'),make('line_stock_reader')],
    [make('line_stock_reader'),make('neondb_owner')],
    [make('line_stock_reader').replace(':opaque%21password',''),make('line_stock_delivery')],
    [make('line_stock_reader'),make('line_stock_delivery')+'&user=postgres'],
    [make('line_stock_reader')+'&options=-c%20role%3Dpostgres',make('line_stock_delivery')],
    [make('line_stock_reader')+'&dbname=postgres',make('line_stock_delivery')],
    [make('line_stock_reader').replace('?sslmode=require&channel_binding=require',''),make('line_stock_delivery')],
    [make('line_stock_reader').replace('sslmode=require','sslmode=disable'),make('line_stock_delivery')],
    [make('line_stock_reader')+'&sslmode=disable',make('line_stock_delivery')],
    [make('line_stock_reader'),make('line_stock_delivery').replace('sslmode=require','sslmode=prefer')],
    ['https://fake.example.test/postgres',make('line_stock_delivery')]
  ]) {
    assert.throws(
      ()=>candidateDatabaseUrls(readUrl,writeUrl),
      /dedicated role credentials|PostgreSQL/u
    );
  }
});

test('enabled candidate rejects admin/swapped database URLs before reading or sending',async()=>{
  const prev={};
  const env={
    LINE_SINGLE_ACCOUNT_ENABLED:'true',
    LINE_CHANNEL_SECRET:'fake-test-secret',
    LINE_CHANNEL_ACCESS_TOKEN:'fake-not-valid-line-token',
    LINE_LEGACY_WEBHOOK_URL:
      'https://br-purple-smoke-a1t9dmzz-linewebhook.compute.c-1.ap-southeast-1.aws.neon.tech/',
    LINE_STOCK_READ_DATABASE_URL:
      'postgresql://postgres:test@db.example.test/twstock?sslmode=require',
    LINE_LOG_WRITE_DATABASE_URL:
      'postgresql://line_stock_delivery:test@db.example.test/twstock?sslmode=require'
  };
  for(const [key,val] of Object.entries(env)){
    prev[key]=process.env[key];
    process.env[key]=val;
  }
  try {
    const raw=JSON.stringify({events:[{
      type:'message',webhookEventId:'fake-event',
      source:{type:'user',userId:'U-synthetic'},
      replyToken:'fake-reply-token',message:{type:'text',text:'2330'}
    }]});
    const signature=createHmac('sha256',env.LINE_CHANNEL_SECRET).update(raw).digest('base64');
    const request=new Request('https://test.invalid/webhook',{
      method:'POST',headers:{
        'content-type':'application/json',
        'x-line-signature':signature
      },body:raw
    });
    const reply=await candidate.fetch(request);
    assert.equal(reply.status,503);
    assert.doesNotMatch(await reply.text(),/postgres|password|fake-test-secret/u);
  } finally {
    for(const [key,original] of Object.entries(prev)){
      if(original===undefined) delete process.env[key];
      else process.env[key]=original;
    }
  }
});

test('unapproved entrypoint is disabled by default, without reading DB or sending messages',async()=>{
  const original=process.env.LINE_SINGLE_ACCOUNT_ENABLED;
  process.env.LINE_SINGLE_ACCOUNT_ENABLED='false';
  try{
    const health=await candidate.fetch(new Request('https://example.test/health'));
    assert.equal(health.status,200);
    const request=new Request('https://example.test/webhook',{
      method:'POST',headers:{'content-type':'application/json'},body:'{"events":[]}'
    });
    const result=await candidate.fetch(request);
    assert.equal(result.status,503);
  }finally{
    if(original===undefined)delete process.env.LINE_SINGLE_ACCOUNT_ENABLED;
    else process.env.LINE_SINGLE_ACCOUNT_ENABLED=original;
  }
});

test('readonly gateway accepts only five reviewed SELECT statements',()=>{
  for (const sql of [ANALYSIS_SQL, RANKING_SQL, DATA_STATUS_SQL, STOCK_NAME_SQL, STANDALONE_CHIP_SQL]) {
    assert.equal(isApprovedStockReadQuery(sql),true);
    assert.ok(sql.trimStart().startsWith('SELECT'));
  }
  for (const sql of [
    "INSERT INTO public.line_messages VALUES ('bad')",
    "DROP TABLE public.daily_prices",
    "SELECT * FROM public.line_messages",
    "SELECT * FROM public.daily_prices",
    "",
    DATA_STATUS_SQL+";"
  ]) {
    assert.equal(isApprovedStockReadQuery(sql),false);
  }
});

test('legacy relay refuses redirects without forwarding LINE event to another host',async()=>{
  const target='https://br-purple-smoke-a1t9dmzz-linewebhook.compute.c-1.ap-southeast-1.aws.neon.tech/';
  const body='{"events":[{"type":"message","replyToken":"fake-secret-reply-token"}]}';
  const signature='fake-hmac-signature';
  const calls=[];
  const transport=async(url,options)=>{
    calls.push({url,options});
    return new Response('',{status:307,headers:{location:'https://attacker.invalid/steal'}});
  };
  const reply=await relayLegacy(target,body,signature,transport);
  assert.deepEqual(reply,{status:307});
  assert.equal(calls.length,1);
  assert.equal(calls[0].url,target);
  assert.equal(calls[0].options.redirect,'manual');
  assert.equal(calls[0].options.cache,'no-store');
  assert.equal(calls[0].options.body,body);
  assert.equal(calls[0].options.headers['x-line-signature'],signature);
});

test('legacy relay never makes HTTP requests to non-pinned targets',async()=>{
  const requests=[];
  const transport=async(url)=>{requests.push(url);return new Response('ok');};
  for(const invalid of ['https://evil.invalid/','http://br-purple-smoke-a1t9dmzz-linewebhook.compute.c-1.ap-southeast-1.aws.neon.tech/']){
    await assert.rejects(relayLegacy(invalid,'{}','signature',transport),/Legacy webhook URL/u);
  }
  assert.equal(requests.length,0);
});

test('legacy relay fails closed on transport errors and does not copy response bodies',async()=>{
  const target='https://br-purple-smoke-a1t9dmzz-linewebhook.compute.c-1.ap-southeast-1.aws.neon.tech/';
  const fail=async()=>{throw Error('mock connection failure')};
  await assert.rejects(relayLegacy(target,'{}','sig',fail),/mock connection failure/u);
  const result=await relayLegacy(target,'{}','sig',async()=>new Response('private upstream body',{status:502}));
  assert.deepEqual(result,{status:502});
  assert.equal(Object.hasOwn(result,'body'),false);
});
