// The same login (NOT SET ROLE impersonation) that a future Neon candidate
// uses is exercised against a fresh localhost-only PostgreSQL CI database.
// No real Neon, LINE endpoint, or customer message is contacted.
import test from 'node:test';
import assert from 'node:assert/strict';
import pg from 'pg';
import { readFile } from 'node:fs/promises';
import { checkedLineReaderUrl } from '../single-account-entry.mjs';
import { verifyActualReader } from '../reader-role-acceptance.mjs';

const url = process.env.LINE_CI_POSTGRES_URL;
const localOnly = (raw) => {
  if (!raw) return false;
  const parsed = new URL(raw);
  return ['localhost','127.0.0.1'].includes(parsed.hostname) &&
    ['postgres:','postgresql:'].includes(parsed.protocol) &&
    parsed.pathname === '/line_ci_test';
};
const ciDb = 'twstock';
const ciRole = 'line_stock_reader';
const ciPassword = 'ci-restricted-reader-only';

test('genuine restricted reader login accepts only exact grants and refuses private data after rollback', {
  skip: !url && 'Disposable local PostgreSQL only'
}, async () => {
  if (!localOnly(url)) throw Error('Refusing a non-disposable test database');
  const admin = new pg.Client({connectionString:url});
  const dbUrl = new URL(url);
  dbUrl.pathname='/' + ciDb;
  const ciReaderUrl = new URL(dbUrl);
  ciReaderUrl.username=ciRole;
  ciReaderUrl.password=ciPassword;
  const restricted = new pg.Client({
    connectionString:ciReaderUrl.toString(),
    connectionTimeoutMillis:3000,
    options:'-c default_transaction_read_only=on'
  });
  let createdDb=false,createdRole=false,hasAdminDb=false,hasReader=false;
  const grant = await readFile(
    new URL('../../sql/line_chip_reader_column_grant.sql',import.meta.url),'utf8'
  );
  const rollback = await readFile(
    new URL('../../sql/line_chip_reader_column_rollback.sql',import.meta.url),'utf8'
  );
  const fixture = new pg.Client({connectionString:dbUrl.toString()});
  try {
    await admin.connect();
    await admin.query('CREATE DATABASE ' + ciDb);
    createdDb=true;
    await admin.query(
      "CREATE ROLE line_stock_reader LOGIN PASSWORD '" + ciPassword +
      "' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS"
    );
    createdRole=true;
    await fixture.connect();
    hasAdminDb=true;
    await fixture.query(`CREATE TABLE public.daily_chip_scores (
      market TEXT NOT NULL,stock_id TEXT NOT NULL,as_of_date DATE NOT NULL,
      total_score NUMERIC,coverage_weight NUMERIC,
      institutional_score NUMERIC,margin_score NUMERIC,
      sensitive_source_json JSONB,
      PRIMARY KEY(market,stock_id,as_of_date)
    )`);
    await fixture.query(`CREATE TABLE public.daily_prices (
      market TEXT NOT NULL,stock_id TEXT NOT NULL,trade_date DATE NOT NULL,
      close NUMERIC,
      PRIMARY KEY(market,stock_id,trade_date)
    )`);
    await fixture.query(`CREATE TABLE public.line_messages (
      id BIGSERIAL PRIMARY KEY,line_user_id TEXT,message_text TEXT
    )`);
    await fixture.query(`INSERT INTO public.daily_prices
      VALUES('twse','2330','2026-11-20',1550)`);
    await fixture.query(`INSERT INTO public.daily_chip_scores
      VALUES('twse','2330','2026-11-20',40.65,.65,29.05,59.21,'{"private":"ci"}')`);
    await fixture.query(`INSERT INTO public.line_messages
      (line_user_id,message_text) VALUES ('U-synthetic','private-test')`);
    await fixture.query('GRANT USAGE ON SCHEMA public TO ' + ciRole);
    await fixture.query('GRANT SELECT ON public.daily_prices TO ' + ciRole);
    await restricted.connect();
    hasReader=true;

    // The future tool must reject accidentally configured owner credentials,
    // and the strict candidate URL validator must reject swapped roles.
    const sample=checkedLineReaderUrl(
      'postgresql://line_stock_reader:fake@db.example.test/twstock?sslmode=require'
    );
    assert.equal(new URL(sample).username,'line_stock_reader');
    assert.throws(
      ()=>checkedLineReaderUrl(
        'postgresql://postgres:fake@db.example.test/twstock?sslmode=require'
      ),/dedicated role credentials/);

    // The actual PostgreSQL session identity is checked, not SET LOCAL ROLE.
    const pre = await verifyActualReader(restricted);
    assert.equal(pre.login,'line_stock_reader');
    assert.equal(pre.database,'twstock');
    assert.equal(pre.acceptance,'blocked');
    assert.equal(pre.missing_chip_columns.length,7);
    assert.equal(pre.table_wide_chip_select,false);
    assert.equal(pre.private_line_message_privilege,false);
    assert.equal(pre.database_write_performed,false);

    // The exact migration is executed only on the isolated CI fixture.
    await fixture.query(grant);
    const ready=await verifyActualReader(restricted);
    assert.equal(ready.acceptance,'chip_reader_query_pass');
    assert.equal(ready.chip_score,40.65);
    assert.equal(ready.chip_coverage,0.65);
    assert.equal(ready.price_date,'2026-11-20');
    assert.equal(ready.chip_date,'2026-11-20');
    assert.equal(ready.source_age_calendar_days,0);
    assert.deepEqual(ready.missing_chip_columns,[]);
    assert.deepEqual(ready.unexpected_chip_columns,[]);
    assert.equal(ready.table_wide_chip_select,false);
    assert.equal(ready.chip_write_privilege,false);
    assert.equal(ready.private_line_message_privilege,false);
    assert.equal(ready.line_message_sent,false);
    assert.equal(ready.webhook_cutover_approved,false);

    // Verify true connection-level enforcement (no role impersonation).
    await assert.rejects(restricted.query(
      'SELECT message_text FROM public.line_messages LIMIT 0'
    ),e=>e.code==='42501');
    await assert.rejects(restricted.query(
      'SELECT sensitive_source_json FROM public.daily_chip_scores LIMIT 0'
    ),e=>e.code==='42501');
    await assert.rejects(restricted.query(
      "UPDATE public.daily_chip_scores SET total_score=1 WHERE stock_id='2330'"
    ),e=>e.code==='25006' || e.code==='42501');

    await fixture.query(rollback);
    const reverted=await verifyActualReader(restricted);
    assert.equal(reverted.acceptance,'blocked');
    assert.equal(reverted.missing_chip_columns.length,7);
    assert.equal(reverted.private_line_message_privilege,false);

    // Accidental broader privileges are never mistaken for an approved grant.
    await fixture.query(
      'GRANT SELECT(sensitive_source_json) ON public.daily_chip_scores TO ' + ciRole
    );
    const drift=await verifyActualReader(restricted);
    assert.equal(drift.acceptance,'blocked');
    assert.deepEqual(drift.unexpected_chip_columns,['sensitive_source_json']);
  } finally {
    if (hasReader) await restricted.end().catch(()=>{});
    if (hasAdminDb) await fixture.end().catch(()=>{});
    if (createdDb) await admin.query('DROP DATABASE ' + ciDb).catch(()=>{});
    if (createdRole) await admin.query('DROP ROLE IF EXISTS ' + ciRole).catch(()=>{});
    await admin.end().catch(()=>{});
  }
});
