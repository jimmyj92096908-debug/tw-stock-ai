import { createHmac, timingSafeEqual } from 'node:crypto';
import { formatResearchModelStatus } from './research-model-status.mjs';

// The current stock_master table is a candidate universe, not a verified
// common-share classification. Keep user-requested exclusions in force.
export const EXCLUDED_CODES = new Set(['1808']);
export const HELP_TEXT = [
  '台股分析查詢',
  '輸入股票代碼或中文全名，例如：6213、聯茂、台積電',
  '也可輸入：分析 6213、分析 聯茂、股票 6488',
  '輸入「清單」看最新可用評分前 10 名；傳送 1～10 或「編號 1」可查詢序號。',
  '輸入「資料狀態」查看資料覆蓋率與最新日期。',
  '輸入「模型狀態」或「研究報告」查看已訓練模型的驗收與唯讀研究報告入口。',
  '輸入「說明」可查看使用方式。',
  '目前僅查詢資料庫已有資料；不提供即時報價或交易指令。'
].join('\n');

export function parseStockCode(input) {
  if (typeof input !== 'string') return { kind: 'help' };
  const normalized = input.replace(/\u3000/g, ' ').trim();
  if (/^(說明|幫助|help|\?|使用方式)$/iu.test(normalized)) return { kind: 'help' };
  if (/^(資料狀態|資料庫狀態|更新狀態|資料更新)$/u.test(normalized)) return { kind: 'status' };
  if (/^(模型狀態|研究報告|研究模型|AI模型)$/iu.test(normalized)) return { kind: 'research' };
  if (/^(清單|排行|排名|觀察清單)$/u.test(normalized)) return { kind: 'list' };
  const rank = /^(?:編號\s*|第\s*)?([1-9]|10)(?:\s*名)?$/u.exec(normalized);
  if (rank) return { kind: 'rank', rank: Number(rank[1]) };
  const match = /^(?:(?:分析|查詢|查股票|股票|代碼|編號|查股|查)\s*)?([0-9]{4})$/u.exec(normalized);
  if (match) {
    if (match[1][0] === '0') return { kind: 'invalid' };
    if (EXCLUDED_CODES.has(match[1])) return { kind: 'excluded', code: match[1] };
    return { kind: 'stock', code: match[1] };
  }

  // Explicit name requests are safe stock commands. Bare Han names must be
  // checked against stock_master BEFORE routing to the new gateway; ordinary
  // messages such as 「你好」 still belong to the original LINE webhook.
  const named = /^(?:分析|查詢|查股票|股票|查股|查)\s*([\p{Script=Han}A-Za-z0-9&－（）()·.-]{2,30})$/u.exec(normalized);
  // Many valid TWSE/TPEx company names are Chinese; a few are English
  // tickers such as M31 and AES-KY. Permit these only when unmistakably
  // stock-like, then confirm exact membership in stock_master.
  const plausibleName = value =>
    /^[\p{Script=Han}]{2,12}$/u.test(value) ||
    (/^[A-Z][A-Z0-9-]{1,16}$/u.test(value) && /[0-9-]/u.test(value)) ||
    (/\p{Script=Han}/u.test(value) &&
      /^[\p{Script=Han}A-Za-z0-9&－（）()·.-]{2,30}$/u.test(value));
  if (named && plausibleName(named[1])) {
    return { kind: 'name', name: named[1], explicit: true };
  }
  if (plausibleName(normalized)) {
    return { kind: 'name', name: normalized, explicit: false };
  }
  return { kind: 'invalid' };
}

export function verifyLineSignature(rawBody, signature, channelSecret) {
  if (typeof rawBody !== 'string' || typeof signature !== 'string' ||
      !signature || typeof channelSecret !== 'string' || !channelSecret) return false;
  const actual = Buffer.from(signature, 'base64');
  const expected = createHmac('sha256', channelSecret).update(rawBody, 'utf8').digest();
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}

// Exact-match, bound-name lookup. Never use ILIKE or partial matches:
// those could route unrelated LINE chat text to the stock feature.
export const STOCK_NAME_SQL = [
  'SELECT market, stock_id, stock_name FROM public.stock_master',
  'WHERE BTRIM(stock_name) = $1',
  "AND market IN ('twse', 'tpex')",
  "AND stock_id ~ '^[1-9][0-9]{3}$'",
  'ORDER BY market, stock_id LIMIT 6'
].join('\n');

// All lookups use a bound stock code. LATERAL joins fetch the most recent
// available date per component instead of pretending every source is current.
// Read-only summary shown by the LINE 「資料狀態」 command.
export const DATA_STATUS_SQL = [
  'SELECT',
  ' (SELECT COUNT(*)::int FROM public.stock_master) AS universe,',
  ' (SELECT COUNT(*)::int FROM (',
  '  SELECT market,stock_id FROM public.daily_prices',
  '  WHERE close IS NOT NULL GROUP BY market,stock_id',
  ' ) z) AS priced,',
  ' (SELECT MAX(trade_date) FROM public.daily_prices',
  '  WHERE close IS NOT NULL) AS price_date,',
  ' (SELECT COUNT(*)::int FROM (',
  '  SELECT market,stock_id,MAX(trade_date) AS last_date',
  '  FROM public.daily_prices WHERE close IS NOT NULL',
  '  GROUP BY market,stock_id',
  ' ) s WHERE s.last_date=(',
  '  SELECT MAX(trade_date) FROM public.daily_prices',
  '  WHERE close IS NOT NULL)) AS priced_latest,',
  ' (SELECT COUNT(*)::int FROM (',
  '  SELECT market,stock_id,MAX(trade_date) AS last_date',
  '  FROM public.daily_prices WHERE close IS NOT NULL',
  '  GROUP BY market,stock_id',
  ' ) s WHERE s.last_date < (',
  '  SELECT MAX(trade_date) FROM public.daily_prices',
  '  WHERE close IS NOT NULL) - INTERVAL \'7 days\') AS stale_over_7_days,',
  ' (SELECT MAX(as_of_date) FROM public.daily_composite_scores',
  '  WHERE total_score IS NOT NULL) AS score_date,',
  ' (SELECT COUNT(*)::int FROM public.daily_composite_scores',
  '  WHERE total_score IS NOT NULL AND as_of_date=(',
  '   SELECT MAX(as_of_date) FROM public.daily_composite_scores',
  '   WHERE total_score IS NOT NULL)) AS scored_latest,',
  ' (SELECT COUNT(*)::int FROM (',
  '  SELECT market,stock_id FROM public.daily_prices',
  '  WHERE close IS NOT NULL GROUP BY market,stock_id',
  '  HAVING COUNT(*) >= 60',
  ' ) d) AS history_60d,',
  ' (SELECT COUNT(*)::int FROM (',
  '  SELECT market,stock_id FROM public.daily_prices',
  '  WHERE close IS NOT NULL GROUP BY market,stock_id',
  '  HAVING COUNT(*) >= 120',
  ' ) d) AS history_120d,',
  ' (SELECT COUNT(*)::int FROM (',
  '  SELECT market,stock_id FROM public.daily_prices',
  '  WHERE close IS NOT NULL GROUP BY market,stock_id',
  '  HAVING COUNT(*) >= 240',
  ' ) d) AS history_240d,',
  ' (SELECT COUNT(DISTINCT (market,stock_id))::int',
  '  FROM public.daily_technicals) AS technical_stocks,',
  ' (SELECT COUNT(DISTINCT (market,stock_id))::int',
  '  FROM public.daily_smc) AS smc_stocks,',
  ' (SELECT COUNT(DISTINCT (market,stock_id))::int',
  '  FROM public.daily_composite_scores',
  '  WHERE total_score IS NOT NULL) AS scored_stocks'
].join('\n');

export const ANALYSIS_SQL = [
  'SELECT sm.market, sm.stock_id, sm.stock_name,',
  ' p.trade_date AS price_date, p.open, p.high, p.low, p.close, p.price_change, p.volume,',
  ' (SELECT MAX(trade_date) FROM public.daily_prices WHERE close IS NOT NULL)',
  '  AS market_latest_date,',
  ' levels.high20, levels.low20, levels.high60, levels.low60,',
  ' t.trade_date AS technical_date, t.ma5, t.ma10, t.ma13, t.ma20,',
  ' t.ma34, t.ma55, t.ma60, t.ma120, t.ma240, t.rsi14, t.atr14,',
  ' t.volume_ma5, t.volume_ma20,',
  ' s.trade_date AS smc_date, s.trend_direction, s.bos_bullish,',
  ' s.bos_bearish, s.choch_bullish, s.choch_bearish,',
  ' s.liquidity_sweep_high, s.liquidity_sweep_low,',
  ' s.order_block_type, s.order_block_high, s.order_block_low,',
  ' s.fvg_type, s.fvg_high, s.fvg_low,',
  ' c.as_of_date AS score_date, c.total_score, c.coverage_weight,',
  ' c.short_term_score, c.swing_score, c.long_term_score, c.chip_score,',
  ' c.technical_score, c.smc_score',
  'FROM public.stock_master sm',
  'LEFT JOIN LATERAL (',
  ' SELECT trade_date, open, high, low, close, price_change, volume FROM public.daily_prices',
  ' WHERE market=sm.market AND stock_id=sm.stock_id AND close IS NOT NULL',
  ' ORDER BY trade_date DESC LIMIT 1',
  ') p ON TRUE',
  'LEFT JOIN LATERAL (',
  ' SELECT MAX(high) FILTER (WHERE rn<=20) AS high20,',
  ' MIN(low) FILTER (WHERE rn<=20) AS low20,',
  ' MAX(high) FILTER (WHERE rn<=60) AS high60,',
  ' MIN(low) FILTER (WHERE rn<=60) AS low60',
  ' FROM (SELECT high,low,ROW_NUMBER() OVER(ORDER BY trade_date DESC) rn',
  '  FROM (SELECT trade_date,high,low FROM public.daily_prices',
  '   WHERE market=sm.market AND stock_id=sm.stock_id AND close IS NOT NULL',
  '   ORDER BY trade_date DESC LIMIT 60) recent) q',
  ') levels ON TRUE',
  'LEFT JOIN LATERAL (',
  ' SELECT trade_date, ma5, ma10, ma13, ma20, ma34, ma55, ma60,',
  ' ma120, ma240, rsi14, atr14, volume_ma5, volume_ma20',
  ' FROM public.daily_technicals',
  ' WHERE market=sm.market AND stock_id=sm.stock_id',
  ' AND trade_date <= COALESCE(p.trade_date, CURRENT_DATE)',
  ' ORDER BY trade_date DESC LIMIT 1',
  ') t ON TRUE',
  'LEFT JOIN LATERAL (',
  ' SELECT trade_date, trend_direction, bos_bullish, bos_bearish,',
  ' choch_bullish, choch_bearish, liquidity_sweep_high,',
  ' liquidity_sweep_low, order_block_type, order_block_high,',
  ' order_block_low, fvg_type, fvg_high, fvg_low FROM public.daily_smc',
  ' WHERE market=sm.market AND stock_id=sm.stock_id',
  ' AND trade_date <= COALESCE(p.trade_date, CURRENT_DATE)',
  ' ORDER BY trade_date DESC LIMIT 1',
  ') s ON TRUE',
  'LEFT JOIN LATERAL (',
  ' SELECT as_of_date, total_score, coverage_weight, short_term_score,',
  ' swing_score, long_term_score, chip_score, technical_score, smc_score',
  ' FROM public.daily_composite_scores',
  ' WHERE market=sm.market AND stock_id=sm.stock_id',
  ' AND as_of_date <= COALESCE(p.trade_date, CURRENT_DATE)',
  ' ORDER BY as_of_date DESC LIMIT 1',
  ') c ON TRUE',
  "WHERE sm.stock_id = $1 AND sm.market IN ('twse', 'tpex')",
  'ORDER BY sm.market LIMIT 3'
].join('\n');


export const RANKING_SQL = [
  'SELECT c.market, c.stock_id, sm.stock_name, c.total_score, c.as_of_date',
  'FROM public.daily_composite_scores c',
  'JOIN public.stock_master sm ON sm.market=c.market AND sm.stock_id=c.stock_id',
  'JOIN public.daily_prices p ON p.market=c.market AND p.stock_id=c.stock_id',
  ' AND p.trade_date=c.as_of_date AND p.close IS NOT NULL',
  'WHERE c.as_of_date=(SELECT MAX(as_of_date) FROM public.daily_composite_scores',
  ' WHERE total_score IS NOT NULL)',
  'AND c.total_score IS NOT NULL',
  "AND c.stock_id <> '1808'",
  "AND c.stock_id ~ '^[1-9][0-9]{3}$'",
  'ORDER BY c.total_score DESC, c.market, c.stock_id',
  'LIMIT 10'
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

function percent(value, digits = 1) {
  return Number.isFinite(value) ? number(value, digits) + '%' : '—';
}

function stockInterpretation(row, priceDate) {
  const close = Number(row.close);
  if (!Number.isFinite(close) || close <= 0) return [];
  const lines = ['', '【技術判讀／風險】'];
  const available = [row.ma5, row.ma20, row.ma60].map(Number)
    .filter(v => Number.isFinite(v) && v > 0);
  if (row.technical_date && displayDate(row.technical_date) === priceDate && available.length) {
    const below = available.filter(v => close < v).length;
    const trend = below === available.length ? '短中期偏弱' :
      below === 0 ? '價格位於主要短中期均線之上' : '均線訊號分歧';
    lines.push('均線：' + trend + '（低於 ' + below + '/' + available.length + ' 條有效短中期均線）');
  }
  const rsi = Number(row.rsi14);
  if (row.rsi14 != null && Number.isFinite(rsi) && row.technical_date &&
      displayDate(row.technical_date) === priceDate) {
    lines.push('動能：' + (rsi < 30 ? 'RSI 低於 30，偏超賣；不代表已止跌' :
      rsi > 70 ? 'RSI 高於 70，偏過熱；不代表必然下跌' :
      'RSI 屬中間區間，須搭配價格結構判斷'));
  }
  const atr = Number(row.atr14);
  if (row.atr14 != null && Number.isFinite(atr) && atr > 0 &&
      displayDate(row.technical_date) === priceDate) {
    const risk = 100 * atr / close;
    lines.push('波動：ATR 約占收盤 ' + percent(risk) +
      (risk >= 7 ? '，日常波動風險偏高' : '；僅是歷史波動尺度'));
  }
  if (row.smc_date && displayDate(row.smc_date) === priceDate) {
    if (row.trend_direction === -1 || Number(row.trend_direction) === -1) {
      lines.push('結構：SMC 偏空；尚須觀察能否出現新的多方結構轉向');
    } else if (Number(row.trend_direction) === 1) {
      lines.push('結構：SMC 偏多；仍有向下反轉風險');
    }
  }
  const low = Number(row.low20), high = Number(row.high20);
  if (row.low20 != null && row.high20 != null && Number.isFinite(low) &&
      Number.isFinite(high) && low > 0 && high >= low) {
    lines.push('近 20 交易日實際低／高：' + number(low) + '／' + number(high) +
      ' 元（歷史區間，非保證支撐或目標價）');
  }
  const vol = Number(row.volume), avg = Number(row.volume_ma20);
  if (Number.isFinite(vol) && Number.isFinite(avg) && avg > 0 &&
      displayDate(row.technical_date) === priceDate) {
    lines.push('量能：當日量約為 20 日均量 ' + percent(100*vol/avg,0));
  }
  lines.push('此為既有行情的規則式研究判讀；無法保證後續走勢。');
  return lines;
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
    lines.push('技術／SMC：' + number(row.technical_score, 1) + '／' +
      number(row.smc_score, 1));
    lines.push('籌碼分數：' + number(row.chip_score, 1));
    if (row.chip_score == null) lines.push('籌碼資料不足，未納入完整評分。');
  }

  lines.push(...stockInterpretation(row, priceDate));
  if (row.market_latest_date && displayDate(row.market_latest_date) !== priceDate) {
    lines.push('', '注意：這檔股票資料日落後市場最新交易日 ' +
      displayDate(row.market_latest_date) + '，不能當作最新行情。');
  }
  const observationTime = Date.parse(priceDate + 'T00:00:00Z');
  if (Number.isFinite(observationTime) && Date.now() - observationTime > 7 * 86400000) {
    lines.push('', '注意：最新可用行情距今已超過 7 日，請確認資料是否更新。');
  }
  const mismatched = [
    row.technical_date, row.smc_date, row.score_date
  ].filter(Boolean).some(value => displayDate(value) !== priceDate);
  if (mismatched) lines.push('', '注意：部分指標日期與收盤交易日不同，請勿視為當日訊號。');
  lines.push('', '僅呈現資料庫已有的歷史資料；並非即時報價。');
  lines.push('商品分類尚待核驗；非買賣指令，不保證獲利。');
  return lines.join('\n').slice(0, 4900);
}

export function formatDataStatus(row) {
  if (!row) return '目前無法讀取資料庫更新狀態，請稍後再試。';
  const universe = Number(row.universe);
  const priced = Number(row.priced);
  const scored = Number(row.scored_latest);
  if (![universe, priced, scored].every(Number.isFinite) ||
      universe < 0 || priced < 0 || scored < 0 || priced > universe) {
    return '目前無法讀取有效的資料庫統計，請稍後再試。';
  }
  const fresh = row.priced_latest == null ? null : Number(row.priced_latest);
  const stale = row.stale_over_7_days == null ? null : Number(row.stale_over_7_days);
  if ((fresh !== null && (!Number.isInteger(fresh) || fresh < 0 || fresh > priced)) ||
      (stale !== null && (!Number.isInteger(stale) || stale < 0 || stale > priced))) {
    return '目前無法讀取有效的資料庫統計，請稍後再試。';
  }
  const readinessKeys = [
    'history_60d', 'history_120d', 'history_240d',
    'technical_stocks', 'smc_stocks', 'scored_stocks'
  ];
  const provided = readinessKeys.filter(key => row[key] !== null && row[key] !== undefined);
  if (provided.length !== 0 && provided.length !== readinessKeys.length) {
    return '目前無法讀取有效的資料庫統計，請稍後再試。';
  }
  const readiness = provided.length ? Object.fromEntries(
    readinessKeys.map(key => [key, Number(row[key])])
  ) : null;
  if (readiness && (
    readinessKeys.some(key =>
      !Number.isInteger(readiness[key]) || readiness[key] < 0 ||
      readiness[key] > universe
    ) ||
    readiness.history_240d > readiness.history_120d ||
    readiness.history_120d > readiness.history_60d ||
    readiness.history_60d > priced ||
    readiness.scored_stocks < scored
  )) return '目前無法讀取有效的資料庫統計，請稍後再試。';
  const coverage = universe ? (100 * priced / universe).toFixed(1) : '0.0';
  const lines = [
    '台股資料庫更新狀態',
    '最新收盤行情：' + displayDate(row.price_date),
    '最新綜合評分：' + displayDate(row.score_date),
    '候選股票：' + number(universe, 0) + ' 檔',
    '已有行情：' + number(priced, 0) + ' 檔（' + coverage + '%）',
    '尚無行情：' + number(universe - priced, 0) + ' 檔',
    '最新評分資料筆數：' + number(scored, 0),
    '注意：資料覆蓋率不是交易所完整股票數；不提供即時報價。',
    '未覆蓋或資料過期的股票，不應視為當日有效分析。'
  ];
  if (fresh !== null) {
    lines.splice(5, 0, '最新行情交易日有資料：' + number(fresh, 0) + ' 檔');
  }
  if (stale !== null) {
    lines.splice(fresh !== null ? 6 : 5, 0,
      '最後行情落後超過 7 日：' + number(stale, 0) + ' 檔');
  }
  if (readiness) {
    lines.splice(7 + (fresh !== null ? 1 : 0) + (stale !== null ? 1 : 0), 0,
      '歷史行情 ≥60／120／240 日：' +
      number(readiness.history_60d, 0) + '／' +
      number(readiness.history_120d, 0) + '／' +
      number(readiness.history_240d, 0) + ' 檔',
      '技術指標／SMC：' + number(readiness.technical_stocks, 0) + '／' +
      number(readiness.smc_stocks, 0) + ' 檔',
      '已有有效評分：' + number(readiness.scored_stocks, 0) + ' 檔',
      '有收盤行情不等於完整分析；長週期指標需更多有效交易日。'
    );
  }
  return lines.join('\n');
}

export async function buildReplyText(text, query) {
  const parsed = parseStockCode(text);
  if (parsed.kind === 'help') return HELP_TEXT;
  if (parsed.kind === 'research') return formatResearchModelStatus();
  if (parsed.kind === 'invalid') return '無法辨識股票代碼或清單編號。\n' + HELP_TEXT;
  if (parsed.kind === 'excluded') return '代碼 1808 已依設定排除，不提供分析。';
  if (parsed.kind === 'status') {
    const result = await query(DATA_STATUS_SQL, []);
    return formatDataStatus(Array.isArray(result?.rows) ? result.rows[0] : null);
  }

  let code = parsed.code;
  let selectedMarket = null;
  let queriedByName = false;
  if (parsed.kind === 'name') {
    const resolved = await query(STOCK_NAME_SQL, [parsed.name]);
    const matches = Array.isArray(resolved?.rows) ? resolved.rows : [];
    if (!matches.length) {
      return '找不到「' + nameText(parsed.name) +
        '」的完整股票名稱；請輸入四位數代碼或正確的股票名稱（例如：聯茂）。';
    }
    if (matches.length !== 1) {
      return '「' + nameText(parsed.name) + '」對應多筆股票：\n' +
        matches.slice(0, 5).map(r => String(r.stock_id) + '（' +
        (r.market === 'twse' ? '上市' : '上櫃') + '）').join('、') +
        '\n請用四位數股票代碼查詢，避免分析錯誤。';
    }
    code = String(matches[0].stock_id);
    selectedMarket = String(matches[0].market);
    queriedByName = true;
    if (EXCLUDED_CODES.has(code)) return '代碼 1808 已依設定排除，不提供分析。';
  }
  if (parsed.kind === 'rank' || parsed.kind === 'list') {
    const ranking = await query(RANKING_SQL, []);
    const list = Array.isArray(ranking?.rows) ? ranking.rows : [];
    const date = list.length ? displayDate(list[0].as_of_date) : '尚無';
    if (!list.length) return '目前沒有可用的觀察清單評分，請改用四位數股票代碼。';
    if (parsed.kind === 'list') {
      const items = list.map((row, i) =>
        (i + 1) + '. ' + row.stock_id + ' ' + nameText(row.stock_name) +
        '｜' + number(row.total_score, 1) + ' 分'
      );
      return [
        '評分觀察清單｜資料日：' + date,
        ...items,
        '',
        '回傳 1～10 的序號即可查詢（例如：1、編號 2）。',
        '清單僅列評分當日有收盤價的候選股票；可能與先前報告不同。',
        '候選股票分類未完全確認；非即時報價或買賣建議。'
      ].join('\n').slice(0, 4900);
    }
    const selected = list[parsed.rank - 1];
    if (!selected) return '最新清單只有 ' + list.length +
      ' 檔；請傳送「清單」查看目前可查的序號。';
    code = String(selected.stock_id);
    selectedMarket = String(selected.market);
    if (EXCLUDED_CODES.has(code)) return '此股票已排除，無法分析。';
  }

  const result = await query(ANALYSIS_SQL, [code]);
  let rows = Array.isArray(result?.rows) ? result.rows : [];
  if (selectedMarket) rows = rows.filter(r => r.market === selectedMarket);
  if (rows.length === 0) {
    return '找不到 ' + code + ' 的可用上市／上櫃候選資料。\n' +
      '請確認代碼或資料是否已建立。';
  }
  if (rows.length > 1) {
    return code + ' 在不同市場有重複代碼，暫不自動選擇，避免分析錯誤。';
  }
  return (parsed.kind === 'rank' ? '清單編號 ' + parsed.rank + '｜' :
    queriedByName ? '名稱查詢｜' : '') + formatStockAnalysis(rows[0]);
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
