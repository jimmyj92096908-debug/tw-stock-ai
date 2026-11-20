// Integration test runs ONLY against disposable CI PostgreSQL on localhost.
// Never point it at a Neon or other production database.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import pg from 'pg';
import { createDeliveryStore } from '../delivery-state.mjs';

const testUrl = process.env.LINE_CI_POSTGRES_URL;

test('PostgreSQL preserves inbound recipient and safely retries reply claims', {
  skip: !testUrl && 'Requires a disposable local CI PostgreSQL service'
}, async () => {
  const url = new URL(testUrl);
  if (!['localhost','127.0.0.1'].includes(url.hostname) ||
      url.pathname !== '/line_ci_test' ||
      !['postgres:', 'postgresql:'].includes(url.protocol)) {
    throw Error('Refusing to run writes outside disposable local CI database');
  }

  const pool = new pg.Pool({connectionString:testUrl,max:5,connectionTimeoutMillis:5000});
  try {
    // Existing production line_messages is never touched. This is a local
    // reproduction of only the columns relevant to the integration.
    await pool.query(`
      CREATE TABLE IF NOT EXISTS public.line_messages (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        event_id TEXT UNIQUE,
        line_user_id TEXT,
        message_type TEXT NOT NULL,
        message_text TEXT,
        received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
      )
    `);
    const migration = await readFile(
      new URL('../../sql/line_reply_delivery_schema.sql',import.meta.url),'utf8'
    );
    await pool.query(migration);
    await pool.query('TRUNCATE TABLE public.line_messages, public.line_reply_delivery');

    const store=createDeliveryStore((sql,params)=>pool.query(sql,params));
    const sample={
      event_id:'evt-local-1',line_user_id:'U-fake-test-id',
      message_type:'text',message_text:'2330'
    };
    await store.recordInbound(sample);
    await store.recordInbound({...sample,message_text:'different duplicate payload'});

    const inbound=await pool.query(`
      SELECT line_user_id,message_type,message_text
      FROM public.line_messages WHERE event_id=$1
    `,['evt-local-1']);
    assert.equal(inbound.rows.length,1);
    assert.deepEqual(inbound.rows[0],{
      line_user_id:'U-fake-test-id',message_type:'text',message_text:'2330'
    });
    const recipients=await pool.query(`
      SELECT COUNT(DISTINCT line_user_id)::int AS count
      FROM public.line_messages WHERE message_type='text'
    `);
    assert.equal(recipients.rows[0].count,1);

    const simultaneous=await Promise.all([
      store.claimReply('evt-local-1'),
      store.claimReply('evt-local-1'),
      store.claimReply('evt-local-1')
    ]);
    assert.equal(simultaneous.filter(x=>x.acquired).length,1);
    assert.equal(simultaneous.filter(x=>x.reason==='busy').length,2);
    const first=simultaneous.find(x=>x.acquired);
    await store.failReply('evt-local-1',first.attemptKey);
    const retry=await store.claimReply('evt-local-1');
    assert.equal(retry.acquired,true);
    await store.completeReply('evt-local-1',retry.attemptKey);
    assert.deepEqual(await store.claimReply('evt-local-1'),{
      acquired:false,reason:'sent'
    });

    const row=await pool.query(`
      SELECT state,attempts FROM public.line_reply_delivery
      WHERE event_id=$1
    `,['evt-local-1']);
    assert.deepEqual(row.rows[0],{state:'sent',attempts:2});

    // A crashed invocation can release its lease after 30 seconds.
    const other=await store.claimReply('evt-local-2');
    assert.equal(other.acquired,true);
    await pool.query(`
      UPDATE public.line_reply_delivery
      SET lease_until=NOW()-INTERVAL '1 second' WHERE event_id=$1
    `,['evt-local-2']);
    const reclaimed=await store.claimReply('evt-local-2');
    assert.equal(reclaimed.acquired,true);
    assert.notEqual(reclaimed.attemptKey,other.attemptKey);
    await assert.rejects(
      store.completeReply('evt-local-2',other.attemptKey),
      /Could not confirm reply completion/
    );
    await store.failReply('evt-local-2',reclaimed.attemptKey);

    // Repeated permanent errors cannot produce unbounded reply attempts.
    let final;
    for(let i=0;i<3;i++){
      final=await store.claimReply('evt-local-3');
      assert.equal(final.acquired,true);
      await store.failReply('evt-local-3',final.attemptKey);
    }
    assert.deepEqual(await store.claimReply('evt-local-3'),{
      acquired:false,reason:'exhausted'
    });
  } finally {
    await pool.end();
  }
});
