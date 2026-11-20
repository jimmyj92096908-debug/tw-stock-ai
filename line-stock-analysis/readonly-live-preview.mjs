// One-time capable, explicitly opted-in preview. Never sends LINE requests,
// changes webhook settings, or grants privileges. Reads fixed public research
// stock data through an SQL READ ONLY transaction and prints only aggregate
// status, never credentials or message/user identifiers.
import assert from 'node:assert/strict';
import pg from 'pg';
import { ANALYSIS_SQL, STANDALONE_CHIP_SQL, buildReplyText } from './handler.mjs';

if (process.env.LINE_STOCK_READONLY_PREVIEW !== 'yes') {
  throw Error('Read-only preview requires an explicit local opt-in');
}
const rawUrl = process.env.DATABASE_URL;
if (!rawUrl) throw Error('Database preview credential missing');
const scoped = new URL(rawUrl);
if (!['postgres:', 'postgresql:'].includes(scoped.protocol)) {
  throw Error('Expected PostgreSQL connection URL');
}
scoped.pathname = '/twstock';
const client = new pg.Client({
  connectionString: scoped.toString(),
  connectionTimeoutMillis: 10000,
  application_name: 'one_time_readonly_line_chip_preview'
});
const expectedSql = new Set([ANALYSIS_SQL, STANDALONE_CHIP_SQL]);
const queryCount = { analysis: 0, chip: 0 };

try {
  await client.connect();
  await client.query('BEGIN TRANSACTION READ ONLY');
  await client.query("SET LOCAL statement_timeout = '20000ms'");
  const query = async (sql, params) => {
    if (!expectedSql.has(sql)) throw Error('Unapproved read-only SQL');
    if (sql === ANALYSIS_SQL) {
      assert.deepEqual(params, ['2330']);
      queryCount.analysis += 1;
    } else {
      assert.deepEqual(params.slice(0, 2), ['twse', '2330']);
      queryCount.chip += 1;
    }
    return client.query(sql, params);
  };
  const original = await buildReplyText('2330', query);
  assert.equal(queryCount.analysis, 1);
  assert.equal(queryCount.chip, 0);
  const optInPreview = await buildReplyText('2330', query,
    { standaloneChipEnabled: true });
  assert.equal(queryCount.analysis, 2);
  assert.equal(queryCount.chip, 1);
  assert.match(original, /2330 台積電/u);
  assert.doesNotMatch(original, /獨立籌碼評分/u);
  assert.match(optInPreview, /2330 台積電/u);
  assert.match(optInPreview, /獨立籌碼評分｜2026-11-20/u);
  assert.match(optInPreview, /籌碼分數：40\.65/u);
  assert.match(optInPreview, /來源覆蓋：65%/u);
  assert.match(optInPreview, /綜合評分｜2026-11-19/u);
  assert.match(optInPreview, /尚未納入上方較舊日期的綜合評分/u);

  console.log(
    'READONLY_LINE_PREVIEW verified=true stock=twse/2330 ' +
    'chip_date=2026-11-20 chip_score=40.65 coverage=65% ' +
    'composite_date=2026-11-19 original_response_unchanged=true ' +
    'source_dates_separate=true actual_line_message_sent=false ' +
    'reader_privilege_granted=false'
  );
} finally {
  try { await client.query('ROLLBACK'); } catch { /* no active txn or connection */ }
  await client.end().catch(() => {});
}
