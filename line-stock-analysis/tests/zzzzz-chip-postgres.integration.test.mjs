// Reproduce the optional LINE chip-score query with real column grants against
// CI's disposable PostgreSQL 17 service. No connection to Neon or real LINE.
// LINE_CI_POSTGRES_URL is created by line-stock-analysis-tests.yml.
import test from 'node:test';
import assert from 'node:assert/strict';
import pg from 'pg';
import {
  ANALYSIS_SQL, STANDALONE_CHIP_SQL, buildReplyText
} from '../handler.mjs';

const connectionString = process.env.LINE_CI_POSTGRES_URL;
const schema = 'ci_chip_details_e2e';
const readRole = 'ci_chip_details_reader';
const localOnly = (value) => {
  if (!value) return false;
  const parsed = new URL(value);
  return ['127.0.0.1', 'localhost'].includes(parsed.hostname) &&
    parsed.pathname === '/line_ci_test' &&
    ['postgres:', 'postgresql:'].includes(parsed.protocol);
};

test('only the seven chip columns are readable, and LINE keeps score dates separate', {
  skip: !connectionString && 'Requires disconnected CI-only local PostgreSQL'
}, async () => {
  if (!localOnly(connectionString)) throw Error('Refusing a non-disposable test DB');
  const pool = new pg.Pool({connectionString, max: 2});
  const admin = await pool.connect();
  let createdRole = false;
  let createdSchema = false;
  const readAsRole = async (sql, args = []) => {
    const client = await pool.connect();
    try {
      await client.query('BEGIN');
      await client.query('SET LOCAL ROLE ' + readRole);
      const result = await client.query(sql, args);
      await client.query('ROLLBACK');
      return result;
    } catch (error) {
      await client.query('ROLLBACK');
      throw error;
    } finally {
      client.release();
    }
  };

  try {
    await admin.query('CREATE SCHEMA ' + schema);
    createdSchema = true;
    await admin.query('CREATE ROLE ' + readRole + ' NOLOGIN');
    createdRole = true;
    await admin.query(`CREATE TABLE ${schema}.daily_chip_scores (
      market TEXT NOT NULL, stock_id TEXT NOT NULL, as_of_date DATE NOT NULL,
      total_score NUMERIC, coverage_weight NUMERIC,
      institutional_score NUMERIC, margin_score NUMERIC,
      private_source_json JSONB,
      PRIMARY KEY(market, stock_id, as_of_date)
    )`);
    await admin.query(`CREATE TABLE ${schema}.line_messages (
      id INT PRIMARY KEY, line_user_id TEXT NOT NULL, message_text TEXT NOT NULL
    )`);
    await admin.query(`INSERT INTO ${schema}.line_messages
      (id,line_user_id,message_text)
      VALUES(1,'test-private-user','test-private-message')`);
    await admin.query(`INSERT INTO ${schema}.daily_chip_scores
      (market,stock_id,as_of_date,total_score,coverage_weight,
       institutional_score,margin_score,private_source_json) VALUES
      ('twse','2330','2026-10-30',NULL,0,NULL,NULL,'{}'),
      ('twse','2330','2026-11-20',40.65,0.65,29.05,59.21,'{"no":"private"}'),
      ('twse','2330','2026-11-21',99.99,1,99,99,'{}'),
      ('twse','2330','2026-11-22',NULL,0,NULL,NULL,'{}'),
      ('twse','6213','2026-11-20',77.77,0.75,70,65,'{}')`);
    await admin.query('GRANT USAGE ON SCHEMA ' + schema + ' TO ' + readRole);
    await admin.query(`GRANT SELECT
      (market,stock_id,as_of_date,total_score,coverage_weight,
       institutional_score,margin_score)
      ON TABLE ${schema}.daily_chip_scores TO ${readRole}`);

    const verifiedQuery = STANDALONE_CHIP_SQL.replaceAll(
      'public.daily_chip_scores', schema + '.daily_chip_scores'
    );
    const rows = (await readAsRole(verifiedQuery,
      ['twse','2330','2026-11-20'])).rows;
    assert.equal(rows.length, 1);
    assert.equal(rows[0].standalone_chip_date.toISOString().slice(0, 10),
      '2026-11-20');
    assert.equal(Number(rows[0].standalone_chip_score), 40.65);
    assert.equal(Number(rows[0].standalone_chip_coverage), 0.65);
    assert.equal(Number(rows[0].standalone_institutional_score), 29.05);
    assert.equal(Number(rows[0].standalone_margin_score), 59.21);

    // A newer date may not be borrowed for an older close or composite day.
    const older = (await readAsRole(verifiedQuery,
      ['twse','2330','2026-11-19'])).rows;
    // A stored invalid result must never look like a usable factor.
    assert.equal(older.length, 0);
    const newestValid = (await readAsRole(verifiedQuery,
      ['twse','2330','2026-11-22'])).rows;
    assert.equal(newestValid.length, 1);
    assert.equal(newestValid[0].standalone_chip_date.toISOString().slice(0,10),
      '2026-11-21');
    assert.equal(Number(newestValid[0].standalone_chip_score),99.99);

    // Exact bound symbol prevents accidental cross-stock score borrowing.
    const other = (await readAsRole(verifiedQuery,
      ['twse','6213','2026-11-20'])).rows;
    assert.equal(other.length, 1);
    assert.equal(Number(other[0].standalone_chip_score), 77.77);
    assert.equal((await readAsRole(verifiedQuery,
      ['tpex','2330','2026-11-20'])).rows.length, 0);

    // Do not need SELECT * or access to non-required private source data.
    await assert.rejects(
      readAsRole('SELECT * FROM ' + schema + '.daily_chip_scores'),
      err => err.code === '42501'
    );
    await assert.rejects(
      readAsRole('SELECT private_source_json FROM ' +
        schema + '.daily_chip_scores'),
      err => err.code === '42501'
    );
    await assert.rejects(
      readAsRole('SELECT * FROM ' + schema + '.line_messages'),
      err => err.code === '42501'
    );
    await assert.rejects(
      readAsRole('INSERT INTO ' + schema +
        ".daily_chip_scores(market,stock_id,as_of_date) VALUES('twse','2330','2026-11-19')"),
      err => err.code === '42501'
    );

    const output = await buildReplyText('2330', async (sql, args) => {
      if (sql === ANALYSIS_SQL) {
        return {rows:[{
          market:'twse', stock_id:'2330', stock_name:'台積電',
          price_date:'2026-11-20',close:'1500',
          score_date:'2026-11-19',total_score:'26.98',
          coverage_weight:'0.60',chip_score:null,
        }]};
      }
      assert.equal(sql, STANDALONE_CHIP_SQL);
      return readAsRole(verifiedQuery, args);
    }, {standaloneChipEnabled:true});
    assert.match(output, /綜合評分｜2026-11-19/u);
    assert.match(output, /獨立籌碼評分｜2026-11-20/u);
    assert.match(output, /40\.65/u);
    assert.match(output, /65%/u);
    assert.match(output, /尚未納入上方較舊日期的綜合評分/u);
    assert.doesNotMatch(output, /test-private-user|private_source_json/u);
  } finally {
    // Cleanup is local CI only; no production schema or roles touched.
    if (createdSchema) {
      await admin.query('DROP SCHEMA IF EXISTS ' + schema + ' CASCADE');
    }
    if (createdRole) {
      await admin.query('DROP ROLE IF EXISTS ' + readRole);
    }
    admin.release();
    await pool.end();
  }
});


test('reader pool forces PostgreSQL default_transaction_read_only to on', {
  skip: !connectionString && 'Requires disposable local PostgreSQL'
}, async () => {
  if (!localOnly(connectionString)) throw Error('Refusing a non-disposable test DB');
  const reader = new pg.Pool({
    connectionString, max: 1,
    options: '-c default_transaction_read_only=on'
  });
  try {
    const status=await reader.query('SHOW default_transaction_read_only');
    assert.equal(status.rows[0].default_transaction_read_only,'on');
    await assert.rejects(
      reader.query('CREATE TABLE ci_reader_must_not_write (id integer)'),
      error => error.code === '25006'
    );
    const stillReadOnly=await reader.query('SHOW transaction_read_only');
    assert.equal(stillReadOnly.rows[0].transaction_read_only,'on');
  } finally {
    await reader.end();
  }
});
