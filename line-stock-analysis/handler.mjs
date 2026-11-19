import { createHmac, timingSafeEqual } from 'node:crypto';

// The current stock_master table is a candidate universe, not a verified
// common-share classification. Keep user-requested exclusions in force.
export const EXCLUDED_CODES = new Set(['1808']);
export const HELP_TEXT = [
  '台股分析查詢',
  '請輸入 4 位數股票代碼，例如：2330',
  '也可輸入：分析 2330、股票 6488',
  '輸入「說明」可查看使用方式。',
  '目前僅查詢資料庫已有資料；不提供即時報價或交易指令。'
].join('\n');

export function parseStockCode(input) {
  if (typeof input !== 'string') return { kind: 'help' };
  const normalized = input.replace(/\u3000/g, ' ').trim();
  if (/^(說明|幫助|help|\?|使用方式)$/iu.test(normalized)) return { kind: 'help' };
  const match = /^(?:(?:分析|查詢|查股票|股票|查)\s*)?([0-9]{4})$/u.exec(normalized);
  if (!match) return { kind: 'invalid' };
  if (EXCLUDED_CODES.has(match[1])) return { kind: 'excluded', code: match[1] };
  return { kind: 'stock', code: match[1] };
}

export function verifyLineSignature(rawBody, signature, channelSecret) {
  if (typeof rawBody !== 'string' || typeof signature !== 'string' ||
      !signature || typeof channelSecret !== 'string' || !channelSecret) return false;
  const actual = Buffer.from(signature, 'base64');
  const expected = createHmac('sha256', channelSecret).update(rawBody, 'utf8').digest();
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}

// All lookups use a bound stock code. LATERAL joins fetch the most recent
// available date per component instead of pretending every source is current.
export const ANALYSIS_SQL = [
  'SELECT sm.market, sm.stock_id, sm.stock_name,',
  ' p.trade_date AS price_date, p.close, p.price_change, p.volume,',
  ' t.trade_date AS technical_date, t.ma5, t.ma10, t.ma13, t.ma20,',
  ' t.ma34, t.ma55, t.ma60, t.ma120, t.ma240, t.rsi14, t.atr14,',
  ' s.trade_date AS smc_date, s.trend_direction, s.bos_bullish,',
  ' s.bos_bearish, s.choch_bullish, s.choch_bearish,',
  ' s.liquidity_sweep_high, s.liquidity_sweep_low,',
  ' s.order_block_type, s.fvg_type,',
  ' c.as_of_date AS score_date, c.total_score, c.coverage_weight,',
  ' c.short_term_score, c.swing_score, c.long_term_score, c.chip_score',
  'FROM public.stock_master sm',
  'LEFT JOIN LATERAL (',
  ' SELECT trade_date, close, price_change, volume FROM public.daily_prices',
  ' WHERE market=sm.market AND stock_id=sm.stock_id AND close IS NOT NULL',
  ' ORDER BY trade_date DESC LIMIT 1',
  ') p ON TRUE',
  'LEFT JOIN LATERAL (',
  ' SELECT trade_date, ma5, ma10, ma13, ma20, ma34, ma55, ma60,',
  ' ma120, ma240, rsi14, atr14 FROM public.daily_technicals',
  ' WHERE market=sm.market AND stock_id=sm.stock_id',
  ' AND trade_date <= COALESCE(p.trade_date, CURRENT_DATE)',
  ' ORDER BY trade_date DESC LIMIT 1',
  ') t ON TRUE',
  'LEFT JOIN LATERAL (',
  ' SELECT trade_date, trend_direction, bos_bullish, bos_bearish,',
  ' choch_bullish, choch_bearish, liquidity_sweep_high,',
  ' liquidity_sweep_low, order_block_type, fvg_type FROM public.daily_smc',
  ' WHERE market=sm.market AND stock_id=sm.stock_id',
  ' AND trade_date <= COALESCE(p.trade_date, CURRENT_DATE)',
  ' ORDER BY trade_date DESC LIMIT 1',
  ') s ON TRUE',
  'LEFT JOIN LATERAL (',
  ' SELECT as_of_date, total_score, coverage_weight, short_term_score,',
  ' swing_score, long_term_score, chip_score FROM public.daily_composite_scores',
  ' WHERE market=sm.market AND stock_id=sm.stock_id',
  ' AND as_of_date <= COALESCE(p.trade_date, CURRENT_DATE)',
  ' ORDER BY as_of_date DESC LIMIT 1',
  ') c ON TRUE',
  "WHERE sm.stock_id = $1 AND sm.market IN ('twse', 'tpex')",
  'ORDER BY sm.market LIMIT 3'
].join('\n');

function displayDate(value) {
  if (value == null) return '尚無';
  if (value instanceof Date && !Number.isNaN(value.getTime())) {
    return value.toISOString().slice(0, 10);
  }
  const raw = String(value);
  return /^\d{4}-\d{2}-\d{2}/u.test(raw) ? raw.slice(0, 10) : '日期未知';
}

function number(value, digits = 2) {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString('zh-TW', {
    minimumFractionDigits: digits, maximumFractionDigits: digits
  }) : '—';
}

function nameText(value) {
  return String(value || '名稱未提供').replace(/[\x00-\x1f\x7f]/gu, ' ').slice(0, 35);
}

function smcEvents(row) {
  const flags = [
    ['bos_bullish', 'BOS 多方'], ['bos_bearish', 'BOS 空方'],
    ['choch_bullish', 'CHOCH 多方'], ['choch_bearish', 'CHOCH 空方'],
    ['liquidity_sweep_high', '掃過高點流動性'],
    ['liquidity_sweep_low', '掃過低點流動性']
  ];
  const found = flags.filter(([key]) => row[key] === true).map(([, label]) => label);
  return found.length ? found.join('、') : '無已標記事件';
}

export function formatStockAnalysis(row) {
  const market = row.market === 'twse' ? '上市' : '上櫃';
  const id = String(row.stock_id || '');
  const head = id + ' ' + nameText(row.stock_name) + '（' + market + '）';
  const priceDate = displayDate(row.price_date);
  if (row.close === null || row.close === undefined) {
    return [
      '台股資料分析｜' + head,
      '目前資料庫沒有可用的收盤行情，無法產生分析。',
      '資料庫股票名單仍為候選，普通股分類尚待完整驗證。',
      '非即時報價或投資建議。'
    ].join('\n');
  }

  const change = row.price_change == null ? '—' :
    ((Number(row.price_change) > 0 ? '+' : '') + number(row.price_change));
  const lines = [
    '台股資料分析｜' + head,
    '收盤交易日：' + priceDate,
    '收盤：' + number(row.close) + '｜漲跌：' + change + ' 元',
    '成交量：' + number(row.volume, 0) + ' 股',
    '',
    '【技術指標｜' + displayDate(row.technical_date) + '】'
  ];

  if (row.technical_date == null) {
    lines.push('尚無技術指標資料');
  } else {
    const mas = [5, 10, 13, 20, 34, 55, 60, 120, 240]
      .map(n => 'MA' + n + ' ' + number(row['ma' + n]));
    lines.push(mas.slice(0, 3).join('｜'));
    lines.push(mas.slice(3, 6).join('｜'));
    lines.push(mas.slice(6, 9).join('｜'));
    lines.push('RSI14：' + number(row.rsi14, 1) +
               '｜ATR14：' + number(row.atr14));
  }

  lines.push('', '【SMC｜' + displayDate(row.smc_date) + '】');
  if (row.smc_date == null) {
    lines.push('尚無 SMC 分析資料');
  } else {
    const trend = Number(row.trend_direction) === 1 ? '多方' :
      Number(row.trend_direction) === -1 ? '空方' : '中性／不明';
    lines.push('趨勢：' + trend);
    lines.push('事件：' + smcEvents(row));
    lines.push('Order Block：' + (row.order_block_type || '尚無'));
    lines.push('FVG：' + (row.fvg_type || '尚無'));
  }

  lines.push('', '【綜合評分｜' + displayDate(row.score_date) + '】');
  if (row.score_date == null || row.total_score == null) {
    lines.push('尚無達可用條件的綜合評分');
  } else {
    const coverage = row.coverage_weight == null ? '—' :
      number(Number(row.coverage_weight) * 100, 0) + '%';
    lines.push('總分：' + number(row.total_score, 1) + '｜因子覆蓋：' + coverage);
    lines.push('短／波／長：' + number(row.short_term_score, 1) + '／' +
      number(row.swing_score, 1) + '／' + number(row.long_term_score, 1));
    lines.push('籌碼分數：' + number(row.chip_score, 1));
  }

  const mismatched = [
    row.technical_date, row.smc_date, row.score_date
  ].filter(Boolean).some(value => displayDate(value) !== priceDate);
  if (mismatched) lines.push('', '注意：部分指標日期與收盤交易日不同，請勿視為當日訊號。');
  lines.push('', '僅呈現資料庫已有的歷史資料；並非即時報價。');
  lines.push('商品分類尚待核驗；非買賣指令，不保證獲利。');
  return lines.join('\n').slice(0, 4900);
}

export async function buildReplyText(text, query) {
  const parsed = parseStockCode(text);
  if (parsed.kind === 'help') return HELP_TEXT;
  if (parsed.kind === 'invalid') return '無法辨識股票代碼。\n' + HELP_TEXT;
  if (parsed.kind === 'excluded') {
    return '代碼 1808 已依設定排除，不提供分析。';
  }
  const result = await query(ANALYSIS_SQL, [parsed.code]);
  const rows = Array.isArray(result?.rows) ? result.rows : [];
  if (rows.length === 0) {
    return '找不到 ' + parsed.code + ' 的上市／上櫃候選資料。\n' +
      '請確認 4 位數代碼；本服務不查詢 ETF、權證或其他商品。';
  }
  if (rows.length > 1) {
    return parsed.code + ' 在不同市場有重複代碼，暫不自動選擇，避免分析錯誤。';
  }
  return formatStockAnalysis(rows[0]);
}

function response(text, status) {
  return new Response(text, { status, headers: { 'content-type': 'text/plain; charset=utf-8' } });
}

// The caller injects an explicitly read-only DB query and LINE Reply API transport.
// No webhook events, user identifiers or message bodies are written to Neon.
export function createWebhookHandler({ query, sendReply, channelSecret, enabled = true }) {
  return async function fetchHandler(request) {
    const pathname = new URL(request.url).pathname;
    if (request.method === 'GET' && pathname === '/health') return response('ok', 200);
    if (pathname !== '/' && pathname !== '/webhook') return response('Not found', 404);
    if (request.method !== 'POST') return response('Method not allowed', 405);
    if (!enabled || !channelSecret) return response('Service unavailable', 503);
    const contentLength = Number(request.headers.get('content-length'));
    if (Number.isFinite(contentLength) && contentLength > 256000) return response('Payload too large', 413);
    const rawBody = await request.text();
    if (Buffer.byteLength(rawBody, 'utf8') > 256000) return response('Payload too large', 413);
    if (!verifyLineSignature(rawBody, request.headers.get('x-line-signature'), channelSecret)) {
      return response('Unauthorized', 401);
    }

    let payload;
    try { payload = JSON.parse(rawBody); } catch { return response('Invalid JSON', 400); }
    if (!Array.isArray(payload?.events) || payload.events.length > 20) {
      return response('Invalid events', 400);
    }
    try {
      for (const event of payload.events) {
        if (!event || typeof event.replyToken !== 'string' || !event.replyToken) continue;
        if (event.type !== 'message' && event.type !== 'follow') continue;
        let message = HELP_TEXT;
        if (event.type === 'message' && event.message?.type === 'text') {
          try {
            message = await buildReplyText(event.message.text, query);
          } catch {
            message = '目前無法讀取分析資料，請稍後再試。';
          }
        }
        await sendReply(event.replyToken, message.slice(0, 4900));
      }
    } catch {
      return response('Temporary reply failure', 502);
    }
    return response('OK', 200);
  };
}
