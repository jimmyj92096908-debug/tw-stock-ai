// Executes the EXACT proposed production grant and rollback SQL, but only
// against a NEW database inside GitHub's disposable local PostgreSQL service.
// No Neon credential, endpoint, or real LINE user is ever accessed.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import pg from 'pg';
import { STANDALONE_CHIP_SQL } from '../handler.mjs';

const ciUrl = process.env.LINE_CI_POSTGRES_URL;
const adminUrl = ciUrl && new URL(ciUrl);
const localOnly = adminUrl &&
  ['localhost','127.0.0.1'].includes(adminUrl.hostname) &&
  ['postgres:','postgresql:'].includes(adminUrl.protocol) &&
  adminUrl.pathname === '/line_ci_test';
const targetDb = 'twstock';
const readerRole = 'line_stock_reader';
const required = [
  'market','stock_id','as_of_date','total_score','coverage_weight',
  'institutional_score','margin_score'
];

test('exact 7-column migration grants, verifies and safely rolls back on isolated PostgreSQL', {
  skip: !ciUrl && 'Only runnable in disposable local CI PostgreSQL'
}, async () => {
  if (!localOnly) throw Error('Refusing to test SQL migrations outside local disposable CI');
  const admin = new pg.Client({ connectionString: ciUrl });
  let target = null, madeDb = false, madeRole = false;
  const targetUrl = new URL(ciUrl);
  targetUrl.pathname = '/' + targetDb;
  const grantSql = await readFile(
    new URL('../../sql/line_chip_reader_column_grant.sql', import.meta.url), 'utf8'
  );
  const rollbackSql = await readFile(
    new URL('../../sql/line_chip_reader_column_rollback.sql', import.meta.url), 'utf8'
  );
  assert.match(grantSql, /GRANT SELECT \(/u);
  assert.match(rollbackSql, /REVOKE SELECT \(/u);
  for (const text of [grantSql, rollbackSql]) {
    assert.match(text, /current_database\(\) <> 'twstock'/u);
    assert.doesNotMatch(text,/\b(?:INSERT INTO|UPDATE public\.|DELETE FROM|DROP TABLE|ALTER ROLE)\b/iu);
  }
  const asReader = async (sql, args = []) => {
    await target.query('BEGIN');
    try {
      await target.query('SET LOCAL ROLE ' + readerRole);
      const result = await target.query(sql, args);
      return result;
    } finally {
      await target.query('ROLLBACK');
    }
  };
  const canRead = async (col) => {
    const r = await target.query(
      "SELECT has_column_privilege($1,'public.daily_chip_scores',$2,'SELECT') AS ok",
      [readerRole, col]
    );
    return r.rows[0].ok;
  };
  const privateUnreadable = async () => {
    const r = await target.query(
      "SELECT has_any_column_privilege($1,'public.line_messages','SELECT') AS can_read",
      [readerRole]
    );
    return !r.rows[0].can_read;
  };

  try {
    await admin.connect();
    // Ephemeral CI only: create a fresh database with production's expected name.
    await admin.query('CREATE DATABASE ' + targetDb);
    madeDb = true;
    await admin.query('CREATE ROLE ' + readerRole + ' LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS');
    madeRole = true;
    target = new pg.Client({connectionString: targetUrl.toString()});
    await target.connect();
    await target.query(`CREATE TABLE public.daily_chip_scores (
      market TEXT NOT NULL, stock_id TEXT NOT NULL, as_of_date DATE NOT NULL,
      total_score NUMERIC, coverage_weight NUMERIC,
      institutional_score NUMERIC, margin_score NUMERIC,
      private_raw JSONB,
      PRIMARY KEY (market,stock_id,as_of_date)
    )`);
    await target.query(`CREATE TABLE public.line_messages (
      event_id TEXT, line_user_id TEXT, message_text TEXT
    )`);
    await target.query(`INSERT INTO public.daily_chip_scores
      (market,stock_id,as_of_date,total_score,coverage_weight,
       institutional_score,margin_score,private_raw)
      VALUES('twse','2330','2026-11-20',40.65,0.65,29.05,59.21,'{"private":true}')`);
    await target.query("INSERT INTO public.line_messages VALUES('evt','fake-private-user','fake-private-text')");
    await target.query('GRANT USAGE ON SCHEMA public TO ' + readerRole);
    for (const col of required) assert.equal(await canRead(col), false, col);
    assert.equal(await privateUnreadable(), true);

    await assert.rejects(
      asReader(STANDALONE_CHIP_SQL,['twse','2330','2026-11-20']),
      err => err.code === '42501'
    );
    // The migration is the exact reviewed SQL, not a fixture copy of its GRANT.
    await target.query(grantSql);
    const chip = await asReader(
      STANDALONE_CHIP_SQL,['twse','2330','2026-11-20']
    );
    assert.equal(chip.rows.length,1);
    assert.equal(Number(chip.rows[0].standalone_chip_score),40.65);
    assert.equal(Number(chip.rows[0].standalone_chip_coverage),0.65);
    for (const col of required) assert.equal(await canRead(col), true, col);
    assert.equal(await canRead('private_raw'), false);
    assert.equal(await privateUnreadable(), true);
    await assert.rejects(
      asReader('SELECT * FROM public.daily_chip_scores'),
      err => err.code === '42501'
    );
    await assert.rejects(
      asReader('SELECT message_text FROM public.line_messages'),
      err => err.code === '42501'
    );
    await assert.rejects(
      asReader("UPDATE public.daily_chip_scores SET total_score=99 WHERE stock_id='2330'"),
      err => err.code === '42501'
    );

    // Re-running a grant against baseline drift is rejected (no hidden widening).
    await assert.rejects(target.query(grantSql),
      err => err.message.includes('drifted from approved baseline'));
    await target.query('ROLLBACK'); // Reset failed SQL's explicit BEGIN.
    assert.equal(await canRead('private_raw'), false);

    await target.query(rollbackSql);
    for (const col of required) assert.equal(await canRead(col), false, col);
    assert.equal(await privateUnreadable(), true);
    await assert.rejects(
      asReader(STANDALONE_CHIP_SQL,['twse','2330','2026-11-20']),
      err => err.code === '42501'
    );
    // Unexpected additional sensitive columns block a future grant.
    await target.query('GRANT SELECT(private_raw) ON public.daily_chip_scores TO ' + readerRole);
    await assert.rejects(target.query(grantSql),
      err => err.message.includes('too broad'));
    await target.query('ROLLBACK');
    for (const col of required) assert.equal(await canRead(col), false, col);
  } finally {
    if (target) await target.end().catch(() => {});
    if (madeDb) {
      // Only a freshly created local CI database can be destroyed here.
      await admin.query('DROP DATABASE ' + targetDb).catch(() => {});
    }
    if (madeRole) await admin.query('DROP ROLE IF EXISTS ' + readerRole).catch(() => {});
    await admin.end().catch(() => {});
  }
});
