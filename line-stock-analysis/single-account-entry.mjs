// DEPLOYMENT CANDIDATE ONLY: never referenced by build.mjs or current index.mjs.
// Do not deploy until old webhook parity, DB migration, privacy and rollback
// are approved. Disabled by default even if accidentally bundled.
import pg from 'pg';
import { createSingleAccountCandidate } from './single-account-candidate.mjs';
import { createSingleAccountGateway } from './single-account-gateway.mjs';
import { createDeliveryStore } from './delivery-state.mjs';
import { ANALYSIS_SQL, RANKING_SQL, DATA_STATUS_SQL, STOCK_NAME_SQL, STANDALONE_CHIP_SQL } from './handler.mjs';

const { Pool } = pg;
let readerPool;
let writerPool;

export function scopedStockUrl(rawUrl) {
  if (!rawUrl) throw new Error('Dedicated database URL is missing');
  const u = new URL(rawUrl);
  if (!['postgres:', 'postgresql:'].includes(u.protocol)) {
    throw new Error('Expected a PostgreSQL connection URL');
  }
  // Keep user, password, SSL, host, port unchanged. Never default to neondb.
  u.pathname = '/twstock';
  return u.toString();
}

// Do not trust the caller to put credentials in the correct environment var.
// A mistakenly supplied owner/admin URL could make an otherwise allowlisted
// SELECT execute with more privileges than the LINE reader should hold.
const FORBIDDEN_CONNECTION_OVERRIDES = new Set([
  'user', 'password', 'host', 'port', 'database', 'dbname', 'role',
  'options', 'service', 'passfile'
]);

function checkedRoleUrl(rawUrl, role) {
  const url = new URL(scopedStockUrl(rawUrl));
  if (decodeURIComponent(url.username) !== role || !url.password ||
      !url.hostname || [...url.searchParams.keys()].some(
        key => FORBIDDEN_CONNECTION_OVERRIDES.has(key.toLowerCase()))) {
    // Never echo the supplied connection string: it may contain a secret.
    throw new Error('LINE candidate requires dedicated role credentials with no overrides');
  }
  return url.toString();
}

export function candidateDatabaseUrls(readUrl, deliveryUrl) {
  return {
    read: checkedRoleUrl(readUrl, 'line_stock_reader'),
    delivery: checkedRoleUrl(deliveryUrl, 'line_stock_delivery')
  };
}

function reader() {
  if (!readerPool) {
    readerPool = new Pool({
      connectionString: candidateDatabaseUrls(
        process.env.LINE_STOCK_READ_DATABASE_URL,
        process.env.LINE_LOG_WRITE_DATABASE_URL
      ).read,
      // Additional defense even if future code bypasses the SQL allowlist.
      options: '-c default_transaction_read_only=on',
      max:3, connectionTimeoutMillis:5000, query_timeout:7000,
      idleTimeoutMillis:30000, application_name:'line_stock_single_account_read'
    });
    readerPool.on('error',()=>console.error('Read pool connection unavailable'));
  }
  return readerPool;
}

function writer() {
  if (!writerPool) {
    writerPool = new Pool({
      connectionString: candidateDatabaseUrls(
        process.env.LINE_STOCK_READ_DATABASE_URL,
        process.env.LINE_LOG_WRITE_DATABASE_URL
      ).delivery,
      max:3, connectionTimeoutMillis:5000, query_timeout:7000,
      idleTimeoutMillis:30000, application_name:'line_stock_single_account_delivery'
    });
    writerPool.on('error',()=>console.error('Write pool connection unavailable'));
  }
  return writerPool;
}

export function isApprovedStockReadQuery(sql) {
  return sql===ANALYSIS_SQL || sql===RANKING_SQL || sql===DATA_STATUS_SQL ||
    sql===STOCK_NAME_SQL || sql===STANDALONE_CHIP_SQL;
}

async function queryStock(sql,params) {
  if (!isApprovedStockReadQuery(sql)) {
    throw new Error('Only vetted stock SELECT queries are permitted');
  }
  return reader().query(sql,params);
}

// The only bare-name routing read uses a vetted exact match, no ILIKE,
// no stock data leaks or logging of message text / user identifiers.
async function lookupExactStockName(name) {
  const result=await queryStock(STOCK_NAME_SQL,[name]);
  return Array.isArray(result?.rows) && result.rows.length>0;
}

const store = createDeliveryStore((sql,params)=>writer().query(sql,params));

async function replyLine(replyToken,text) {
  const token=process.env.LINE_CHANNEL_ACCESS_TOKEN;
  if (!token) throw new Error('LINE transport is unavailable');
  const result = await fetch('https://api.line.me/v2/bot/message/reply',{
    method:'POST',
    headers:{
      'content-type':'application/json',
      authorization:'Bearer '+token
    },
    body:JSON.stringify({replyToken,messages:[{type:'text',text}]}),
    redirect:'manual',
    cache:'no-store',
    signal:AbortSignal.timeout(8000)
  });
  if (!result.ok) {
    // Never print LINE response body, token, personal identifiers or messages.
    throw new Error('LINE Reply API status '+result.status);
  }
}

// Require the exact pre-existing webhook host. An env var is needed only to
// select its original path; never allow this gateway to proxy arbitrary URLs.
const LEGACY_HOSTNAME =
  'br-purple-smoke-a1t9dmzz-linewebhook.compute.c-1.ap-southeast-1.aws.neon.tech';

export function validateLegacyWebhookUrl(rawUrl) {
  if (!rawUrl) throw new Error('Legacy webhook URL is unavailable');
  const url=new URL(rawUrl);
  if (url.protocol!=='https:' || url.hostname!==LEGACY_HOSTNAME ||
      url.username || url.password || url.port || url.search || url.hash ||
      !['/','/webhook'].includes(url.pathname)) {
    throw new Error('Legacy webhook URL must be the pre-existing Neon function');
  }
  return url.toString();
}

// Revalidate the fixed destination every time, not only on application boot.
// Never follow 301/302/307/308 redirects: they could forward signed private
// LINE events or existing reply tokens to a different host.
export async function relayLegacy(targetUrl,body,signature,transport=fetch) {
  const validated=validateLegacyWebhookUrl(targetUrl);
  if (typeof body!=='string' || typeof signature!=='string') {
    throw new TypeError('Invalid signed LINE payload');
  }
  const result=await transport(validated,{
    method:'POST',
    headers:{
      'content-type':'application/json',
      'x-line-signature':signature
    },
    body,
    redirect:'manual',
    cache:'no-store',
    signal:AbortSignal.timeout(8000)
  });
  // Never expose upstream body, which may contain private data.
  // Any redirection is treated as an upstream failure by the gateway.
  return {status:result.status};
}

export default {
  fetch(request) {
    const secret = process.env.LINE_CHANNEL_SECRET || '';
    let legacyUrl;
    try {
      legacyUrl=validateLegacyWebhookUrl(process.env.LINE_LEGACY_WEBHOOK_URL);
    } catch {
      // Fail closed if the original destination has not been reviewed.
      legacyUrl=null;
    }
    let dedicatedRolesReady = false;
    try {
      // Never accept a stock reader configured as a DB owner, or a swapped
      // delivery/reader secret, even if the feature flag was enabled.
      candidateDatabaseUrls(
        process.env.LINE_STOCK_READ_DATABASE_URL,
        process.env.LINE_LOG_WRITE_DATABASE_URL
      );
      dedicatedRolesReady = true;
    } catch {
      // A disabled/misconfigured candidate cannot route or relay user events.
    }
    const enabled = process.env.LINE_SINGLE_ACCOUNT_ENABLED === 'true' &&
      Boolean(secret && process.env.LINE_CHANNEL_ACCESS_TOKEN &&
        legacyUrl && dedicatedRolesReady);

    const stockHandler=createSingleAccountCandidate({
      query:queryStock,store,sendReply:replyLine,lookupExactStockName,
      channelSecret:secret,enabled,
      standaloneChipEnabled: process.env.LINE_CHIP_SCORE_DETAILS_ENABLED === 'true'
    });
    const gateway=createSingleAccountGateway({
      channelSecret:secret,stockHandler,lookupExactStockName,
      forwardLegacy:(body,signature)=>relayLegacy(legacyUrl,body,signature),
      enabled
    });
    return gateway(request);
  }
};
