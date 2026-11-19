import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import {
  ANALYSIS_SQL, EXCLUDED_CODES, HELP_TEXT, parseStockCode,
  verifyLineSignature, formatStockAnalysis, buildReplyText, createWebhookHandler
} from '../handler.mjs';

function lineRequest(payload, secret = 'test-channel-secret', signatureOverride) {
  const body = typeof payload === 'string' ? payload : JSON.stringify(payload);
  const signature = signatureOverride ??
    createHmac('sha256', secret).update(body).digest('base64');
  return new Request('https://example.com/webhook', {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'x-line-signature': signature
    },
    body
  });
}

function stock(overrides = {}) {
  return {
    market: 'twse', stock_id: '2330', stock_name: '台積電',
    price_date: '2026-11-19', close: '1500.50', price_change: '10',
    volume: '42000000', technical_date: '2026-11-18',
    ma5: '1490', ma10: '1480', ma13: '1470', ma20: '1460',
    ma34: '1450', ma55: '1440', ma60: '1430',
    ma120: '1420', ma240: '1410', rsi14: '62.5', atr14: '30.4',
    smc_date: '2026-11-18', trend_direction: 1, bos_bullish: true,
    bos_bearish: false, choch_bullish: false, choch_bearish: false,
    liquidity_sweep_high: false, liquidity_sweep_low: true,
    order_block_type: 'bullish', fvg_type: 'bullish',
    score_date: '2026-11-18', total_score: '75',
    coverage_weight: '0.65', short_term_score: '80',
    swing_score: '73', long_term_score: '68', chip_score: null,
    ...overrides
  };
}

test('support bare 4-digit codes and Chinese command prefixes', () => {
  for (const input of ['2330', '分析 2330', '股票2330', '查詢 2330', '　2330　']) {
    assert.deepEqual(parseStockCode(input), { kind: 'stock', code: '2330' });
  }
  assert.equal(parseStockCode('help').kind, 'help');
  assert.equal(parseStockCode('說明').kind, 'help');
});

test('reject arbitrary SQL, multi-code messages and unsupported instruments', () => {
  for (const input of ['2330 OR 1=1', '2330; DROP TABLE', '2330 6488', '0050ETF', '123', '12345']) {
    assert.equal(parseStockCode(input).kind, 'invalid');
  }
  assert.ok(EXCLUDED_CODES.has('1808'));
  assert.deepEqual(parseStockCode('1808'), { kind: 'excluded', code: '1808' });
});

test('verify LINE HMAC over raw request body with strict secret and signature', () => {
  const raw = '{"events":[]}';
  const signature = createHmac('sha256', 'secret').update(raw).digest('base64');
  assert.equal(verifyLineSignature(raw, signature, 'secret'), true);
  assert.equal(verifyLineSignature(raw + ' ', signature, 'secret'), false);
  assert.equal(verifyLineSignature(raw, signature, 'other'), false);
  assert.equal(verifyLineSignature(raw, 'bad', 'secret'), false);
  assert.equal(verifyLineSignature(raw, signature, ''), false);
});

test('read-only SQL uses positional parameters and no direct interpolation', () => {
  assert.match(ANALYSIS_SQL, /sm.stock_id = \$1/u);
  assert.match(ANALYSIS_SQL, /FROM public\.stock_master/u);
  assert.doesNotMatch(ANALYSIS_SQL, /\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|CREATE)\b/iu);
});

test('format includes dates, nine averages, SMC, score, coverage and stale warning', () => {
  const result = formatStockAnalysis(stock());
  assert.match(result, /2330 台積電/u);
  assert.match(result, /收盤交易日：2026-11-19/u);
  assert.match(result, /MA240/u);
  assert.match(result, /RSI14/u);
  assert.match(result, /ATR14/u);
  assert.match(result, /BOS 多方/u);
  assert.match(result, /總分/u);
  assert.match(result, /65%/u);
  assert.match(result, /日期與收盤交易日不同/u);
  assert.match(result, /分類尚待核驗/u);
  assert.ok(result.length < 5000);
});

test('missing price or technical data never become fabricated scores', () => {
  assert.match(formatStockAnalysis(stock({close: null})), /無法產生分析/u);
  const incomplete = formatStockAnalysis(stock({
    technical_date: null, smc_date: null, score_date: null, total_score: null
  }));
  assert.match(incomplete, /尚無技術指標資料/u);
  assert.match(incomplete, /尚無 SMC 分析資料/u);
  assert.match(incomplete, /尚無達可用條件/u);
});

test('stock lookup returns no-data, ambiguity and manual exclusion messages', async () => {
  let count = 0;
  const query = async (_sql, params) => {
    count += 1;
    assert.deepEqual(params, ['2330']);
    return { rows: [] };
  };
  assert.match(await buildReplyText('2330', query), /找不到 2330/u);
  assert.equal(count, 1);
  assert.match(await buildReplyText('1808', query), /已依設定排除/u);
  assert.equal(count, 1);
  assert.equal(await buildReplyText('說明', query), HELP_TEXT);
  assert.equal(count, 1);
  assert.match(await buildReplyText('2330', async () => ({ rows: [stock(), stock()] })), /重複代碼/u);
});

test('signed webhook replies with database analysis without persisting messages', async () => {
  const sent = [];
  const query = async (sql, params) => {
    assert.equal(sql, ANALYSIS_SQL);
    assert.deepEqual(params, ['2330']);
    return { rows: [stock()] };
  };
  const handler = createWebhookHandler({
    query, sendReply: async (token, message) => sent.push({ token, message }),
    channelSecret: 'test-channel-secret'
  });
  const payload = {
    events: [
      { type: 'message', replyToken: 'reply-abc',
        message: { type: 'text', text: '分析 2330' } }
    ]
  };
  const response = await handler(lineRequest(payload));
  assert.equal(response.status, 200);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].token, 'reply-abc');
  assert.match(sent[0].message, /台積電/u);
});

test('tampered signatures cannot trigger a query or reply', async () => {
  let calls = 0;
  const handler = createWebhookHandler({
    query: async () => { calls += 1; return { rows: [] }; },
    sendReply: async () => { calls += 1; },
    channelSecret: 'test-channel-secret'
  });
  const res = await handler(lineRequest({ events: [] }, 'test-channel-secret', 'invalid'));
  assert.equal(res.status, 401);
  assert.equal(calls, 0);
});

test('LINE verification handshake, invalid JSON and unavailable service', async () => {
  const handler = createWebhookHandler({
    query: async () => ({ rows: [] }), sendReply: async () => {},
    channelSecret: 'test-channel-secret'
  });
  assert.equal((await handler(lineRequest({ events: [] }))).status, 200);
  assert.equal((await handler(lineRequest('{ broken json'))).status, 400);
  const unavailable = createWebhookHandler({
    query: async () => ({ rows: [] }), sendReply: async () => {},
    channelSecret: '', enabled: false
  });
  assert.equal((await unavailable(lineRequest({ events: [] }))).status, 503);
  assert.equal((await unavailable(new Request('https://example.com/health'))).status, 200);
});

test('unknown messages return help and database exceptions do not leak into LINE', async () => {
  const sent = [];
  const handler = createWebhookHandler({
    query: async () => { throw new Error('private database connection details'); },
    sendReply: async (_token, message) => sent.push(message),
    channelSecret: 'test-channel-secret'
  });
  const payload = {
    events: [
      { type: 'follow', replyToken: 'follow-token' },
      { type: 'message', replyToken: 'msg-token', message: { type: 'text', text: '2330' } }
    ]
  };
  assert.equal((await handler(lineRequest(payload))).status, 200);
  assert.equal(sent[0], HELP_TEXT);
  assert.match(sent[1], /目前無法讀取分析資料/u);
  assert.doesNotMatch(sent[1], /private database/u);
});
