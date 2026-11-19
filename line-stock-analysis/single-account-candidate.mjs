// UNDEPLOYED candidate for merging the observed legacy text reply and stock lookup.
// It is NOT imported by index.mjs and does not replace the original webhook.
// Unknown legacy follow/non-text behavior remains a cutover blocker.
import { verifyLineSignature, buildReplyText } from './handler.mjs';
import { planLineEvent } from './legacy-compatibility.mjs';

export function observedLegacyReply(messageText) {
  // Observed via a user-provided LINE screenshot for 2330 and 6213.
  // This is an observed fallback, NOT a verified full legacy implementation.
  return ('收到你的訊息：' + String(messageText).slice(0, 4700) +
    '\nAI 台股投資系統正在建置中。').slice(0, 4900);
}

function response(text, status) {
  return new Response(text, {
    status,
    headers: { 'content-type': 'text/plain; charset=utf-8' }
  });
}

// Inject functions during test. Do not construct a live DB writer or LINE
// transport until a reviewed deployment entry and rollback plan exist.
export function createSingleAccountCandidate({
  query, recordMessage, sendReply, channelSecret, enabled = true
}) {
  return async function fetchHandler(request) {
    const path = new URL(request.url).pathname;
    if (request.method === 'GET' && path === '/health') return response('ok', 200);
    if (path !== '/' && path !== '/webhook') return response('Not found', 404);
    if (request.method !== 'POST') return response('Method not allowed', 405);
    if (!enabled || !channelSecret) return response('Service unavailable', 503);

    if (Number(request.headers.get('content-length')) > 256000) {
      return response('Payload too large', 413);
    }
    const rawBody = await request.text();
    if (Buffer.byteLength(rawBody, 'utf8') > 256000) {
      return response('Payload too large', 413);
    }
    if (!verifyLineSignature(rawBody, request.headers.get('x-line-signature'), channelSecret)) {
      return response('Unauthorized', 401);
    }

    let payload;
    try { payload = JSON.parse(rawBody); } catch { return response('Invalid JSON', 400); }
    if (!Array.isArray(payload?.events) || payload.events.length > 20) {
      return response('Invalid events', 400);
    }

    for (const event of payload.events) {
      // We have only observed the old handler's 1:1 text behavior.
      // Do not guess old follow, image, group, or postback semantics.
      if (event?.type !== 'message' ||
          event.source?.type !== 'user' ||
          event.message?.type !== 'text' ||
          typeof event.message.text !== 'string' ||
          !event.replyToken) continue;

      const plan = planLineEvent(event);
      if (plan.record) {
        if (typeof recordMessage !== 'function') return response('Record unavailable', 503);
        try {
          // Contract: returns false if event_id already exists; must use
          // parameterized INSERT ... ON CONFLICT DO NOTHING in a future adapter.
          const recorded = await recordMessage(plan.record);
          if (recorded === false) continue; // Avoid duplicate LINE replies.
        } catch {
          return response('Temporary record failure', 502);
        }
      }

      let answer;
      if (plan.route === 'stock') {
        try { answer = await buildReplyText(event.message.text, query); }
        catch { answer = '目前無法讀取分析資料，請稍後再試。'; }
      } else {
        answer = observedLegacyReply(event.message.text);
      }

      try { await sendReply(event.replyToken, answer); }
      catch { return response('Temporary reply failure', 502); }
    }
    return response('OK', 200);
  };
}
