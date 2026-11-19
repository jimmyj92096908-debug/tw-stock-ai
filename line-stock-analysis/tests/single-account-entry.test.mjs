import test from 'node:test';
import assert from 'node:assert/strict';
import candidate, { scopedStockUrl } from '../single-account-entry.mjs';

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
