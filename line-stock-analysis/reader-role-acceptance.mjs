// Manually operated, post-authorization acceptance checker.
// Reads PUBLIC stock research data with the actual line_stock_reader login.
// Does not grant any privilege, write any data, access private message rows,
// deploy Neon Functions, switch webhooks, or call the LINE network API.
import pg from 'pg';
import { pathToFileURL } from 'node:url';
import { checkedLineReaderUrl } from './single-account-entry.mjs';
import { STANDALONE_CHIP_SQL } from './handler.mjs';

const REQUIRED_CHIP_COLUMNS = Object.freeze([
  'as_of_date', 'coverage_weight', 'institutional_score', 'margin_score',
  'market', 'stock_id', 'total_score'
]);

const ROLE_CHECK_SQL = `
SELECT current_user AS effective_user, session_user AS login_user,
       current_database() AS database_name,
       current_setting('transaction_read_only') AS is_read_only,
       (SELECT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb
               AND NOT rolcreaterole AND NOT rolbypassrls
        FROM pg_roles WHERE rolname=current_user) AS unprivileged_login,
       has_table_privilege(current_user,'public.daily_chip_scores','SELECT')
         AS table_wide_chip_select,
       ARRAY(
         SELECT c.column_name::text FROM information_schema.columns c
         WHERE c.table_schema='public' AND c.table_name='daily_chip_scores'
           AND has_column_privilege(
             current_user,'public.daily_chip_scores',c.column_name,'SELECT'
           )
         ORDER BY c.column_name
       ) AS actual_chip_columns,
       (
         has_any_column_privilege(current_user,'public.daily_chip_scores','INSERT')
         OR has_any_column_privilege(current_user,'public.daily_chip_scores','UPDATE')
         OR has_table_privilege(current_user,'public.daily_chip_scores','DELETE')
         OR has_table_privilege(current_user,'public.daily_chip_scores','TRUNCATE')
       ) AS chip_write_privilege,
       (
         has_any_column_privilege(current_user,'public.line_messages','SELECT')
         OR has_any_column_privilege(current_user,'public.line_messages','INSERT')
         OR has_any_column_privilege(current_user,'public.line_messages','UPDATE')
         OR has_table_privilege(current_user,'public.line_messages','DELETE')
       ) AS private_message_privilege
`;

const PRICE_DATE_SQL = `
SELECT MAX(trade_date)::text AS price_date
FROM public.daily_prices
WHERE market='twse' AND stock_id='2330' AND close IS NOT NULL
`;

function calendarAge(older, newer) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(older || '') ||
      !/^\d{4}-\d{2}-\d{2}$/.test(newer || '')) return null;
  const a = Date.parse(older + 'T00:00:00Z');
  const b = Date.parse(newer + 'T00:00:00Z');
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  return Math.round((b - a) / 86400000);
}

function isoDate(value) {
  if (value instanceof Date) return value.toISOString().slice(0,10);
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value))
    return value;
  return null;
}

export async function verifyActualReader(client) {
  await client.query('BEGIN TRANSACTION READ ONLY');
  try {
    await client.query("SET LOCAL statement_timeout = '10000ms'");
    const roleRows = (await client.query(ROLE_CHECK_SQL)).rows;
    if (roleRows.length !== 1) throw Error('Unable to verify dedicated reader');
    const role = roleRows[0];
    if (role.effective_user !== 'line_stock_reader' ||
        role.login_user !== 'line_stock_reader' ||
        role.database_name !== 'twstock' ||
        role.is_read_only !== 'on' || role.unprivileged_login !== true) {
      throw Error('Connected login, database or read-only mode is not approved');
    }

    if (!Array.isArray(role.actual_chip_columns)) {
      throw Error('Unexpected PostgreSQL ACL array representation');
    }
    const actual = [...new Set(role.actual_chip_columns)].sort();
    const expected = [...REQUIRED_CHIP_COLUMNS].sort();
    const missing = expected.filter(col => !actual.includes(col));
    const extra = actual.filter(col => !expected.includes(col));
    const permissionsSafe = missing.length === 0 && extra.length === 0 &&
      !role.table_wide_chip_select && !role.chip_write_privilege &&
      !role.private_message_privilege;

    const report = {
      mode:'actual-login-read-only',
      login:'line_stock_reader',
      database:'twstock',
      stock:'twse/2330',
      missing_chip_columns:missing,
      unexpected_chip_columns:extra,
      table_wide_chip_select:Boolean(role.table_wide_chip_select),
      chip_write_privilege:Boolean(role.chip_write_privilege),
      private_line_message_privilege:Boolean(role.private_message_privilege),
      chip_score:null,
      chip_coverage:null,
      price_date:null,
      chip_date:null,
      source_age_calendar_days:null,
      acceptance:'blocked',
      line_message_sent:false,
      database_write_performed:false,
      webhook_cutover_approved:false
    };

    // We never probe personal message contents. ACL metadata alone suffices.
    if (!permissionsSafe) return report;

    const price = (await client.query(PRICE_DATE_SQL)).rows[0]?.price_date;
    report.price_date = isoDate(price);
    if (!report.price_date) return report;
    const rows = (await client.query(STANDALONE_CHIP_SQL,
      ['twse','2330',report.price_date])).rows;
    if (rows.length !== 1) return report;
    const row = rows[0];
    report.chip_date = isoDate(row.standalone_chip_date);
    report.chip_score = Number(row.standalone_chip_score);
    report.chip_coverage = Number(row.standalone_chip_coverage);
    report.source_age_calendar_days =
      calendarAge(report.chip_date,report.price_date);

    const age = report.source_age_calendar_days;
    if (age !== null && age >= 0 && age <= 7 &&
        Number.isFinite(report.chip_score) &&
        report.chip_score >= 0 && report.chip_score <= 100 &&
        Number.isFinite(report.chip_coverage) &&
        report.chip_coverage >= .5 && report.chip_coverage <= 1) {
      report.acceptance='chip_reader_query_pass';
    }
    return report;
  } finally {
    await client.query('ROLLBACK').catch(() => {});
  }
}

async function main() {
  if (process.env.LINE_CHIP_READER_ACCEPTANCE !== 'yes') {
    throw Error('Reader acceptance requires explicit opt-in');
  }
  const url = checkedLineReaderUrl(
    process.env.LINE_STOCK_READ_DATABASE_URL
  );
  const client = new pg.Client({
    connectionString:url,connectionTimeoutMillis:8000,
    options:'-c default_transaction_read_only=on',
    application_name:'line_chip_reader_acceptance'
  });
  try {
    await client.connect();
    const report = await verifyActualReader(client);
    console.log(JSON.stringify(report));
    if (report.acceptance !== 'chip_reader_query_pass') process.exitCode=2;
  } finally {
    await client.end().catch(() => {});
  }
}

if (process.argv[1] &&
    import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(() => {
    // Do not leak passwords, host names, tokens, or rejected SQL.
    console.error('Reader acceptance blocked: verify dedicated credentials and grants');
    process.exitCode = 2;
  });
}
