// DEPLOYMENT CANDIDATE ONLY: never referenced by build.mjs or current index.mjs.
// Do not deploy until old webhook parity, DB migration, privacy and rollback
// are approved. Disabled by default even if accidentally bundled.
import pg from 'pg';
import { createSingleAccountCandidate } from './single-account-candidate.mjs';
import { createSingleAccountGateway } from './single-account-gateway.mjs';
import { createDeliveryStore } from './delivery-state.mjs';
import { ANALYSIS_SQL, RANKING_SQL } from './handler.mjs';

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

function reader() {
  if (!readerPool) {
    readerPool = new Pool({
      connectionString: scopedStockUrl(process.env.LINE_STOCK_READ_DATABASE_URL),
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
      connectionString: scopedStockUrl(process.env.LINE_LOG_WRITE_DATABASE_URL),
      max:3, connectionTimeoutMillis:5000, query_timeout:7000,
      idleTimeoutMillis:30000, application_name:'line_stock_single_account_delivery'
    });
    writerPool.on('error',()=>console.error('Write pool connection unavailable'));
  }
  return writerPool;
}

async function queryStock(sql,params) {
  if (sql!==ANALYSIS_SQL && sql!==RANKING_SQL) {
    throw new Error('Only vetted stock SELECT queries are permitted');
  }
  return reader().query(sql,params);
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

async function relayLegacy(targetUrl,body,signature) {
  const result=await fetch(targetUrl,{
    method:'POST',
    headers:{
      'content-type':'application/json',
      'x-line-signature':signature
    },
    body,
    signal:AbortSignal.timeout(8000)
  });
  // Never expose upstream body, which may contain private data.
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
    const enabled = process.env.LINE_SINGLE_ACCOUNT_ENABLED === 'true' &&
      Boolean(secret && process.env.LINE_CHANNEL_ACCESS_TOKEN &&
        process.env.LINE_STOCK_READ_DATABASE_URL &&
        process.env.LINE_LOG_WRITE_DATABASE_URL && legacyUrl);

    const stockHandler=createSingleAccountCandidate({
      query:queryStock,store,sendReply:replyLine,
      channelSecret:secret,enabled
    });
    const gateway=createSingleAccountGateway({
      channelSecret:secret,stockHandler,
      forwardLegacy:(body,signature)=>relayLegacy(legacyUrl,body,signature),
      enabled
    });
    return gateway(request);
  }
};
