import pg from 'pg';
import { createWebhookHandler } from './handler.mjs';

const { Pool } = pg;
let pool;

// This project stores stock data in "twstock", while Neon can inject
// DATABASE_URL pointing at its default "postgres" database.
// Only change the database path; preserve credentials, host, and TLS options.
export function stockDatabaseUrl(rawUrl) {
  if (!rawUrl) throw new Error('DATABASE_URL is unavailable');
  const parsed = new URL(rawUrl);
  if (parsed.protocol !== 'postgres:' && parsed.protocol !== 'postgresql:') {
    throw new Error('Expected a PostgreSQL connection URL');
  }
  parsed.pathname = '/twstock';
  return parsed.toString();
}

function getPool() {
  if (!process.env.DATABASE_URL) throw new Error('DATABASE_URL is unavailable');
  if (!pool) {
    pool = new Pool({
      connectionString: stockDatabaseUrl(process.env.DATABASE_URL),
      max: 3,
      connectionTimeoutMillis: 5000,
      query_timeout: 7000,
      idleTimeoutMillis: 30000,
      application_name: 'tw_stock_line_read_only'
    });
    // Neon may close idle connections when scaling down; don't crash the isolate.
    pool.on('error', () => console.error('Database idle connection unavailable'));
  }
  return pool;
}

async function queryReadOnly(sql, params) {
  // No INSERT, UPDATE, DELETE, schema changes, or market-data downloads.
  return getPool().query(sql, params);
}

async function replyLine(replyToken, text) {
  const token = process.env.LINE_CHANNEL_ACCESS_TOKEN;
  if (!token) throw new Error('LINE reply transport is not configured');
  const result = await fetch('https://api.line.me/v2/bot/message/reply', {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'authorization': 'Bearer ' + token
    },
    body: JSON.stringify({
      replyToken,
      messages: [{ type: 'text', text }]
    }),
    signal: AbortSignal.timeout(8000)
  });
  if (!result.ok) {
    // Deliberately omit response bodies: never log user data or credentials.
    throw new Error('LINE Reply API returned HTTP ' + result.status);
  }
}

export default {
  fetch(request) {
    const channelSecret = process.env.LINE_CHANNEL_SECRET || '';
    return createWebhookHandler({
      query: queryReadOnly,
      sendReply: replyLine,
      channelSecret,
      enabled: Boolean(channelSecret && process.env.LINE_CHANNEL_ACCESS_TOKEN)
    })(request);
  }
};
