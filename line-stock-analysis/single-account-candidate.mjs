// UNDEPLOYED candidate for one existing LINE account.
// This file is NOT imported by index.mjs and is not deployed to any Neon function.
// Legacy follow/non-text functionality remains unknown and is a cutover blocker.
import { verifyLineSignature, buildReplyText, parseStockCode } from './handler.mjs';
import { planLineEvent } from './legacy-compatibility.mjs';

const MAX_WEBHOOK_BYTES = 256000;
const REDELIVERY_MAX_EVENT_AGE_MS = 19 * 60 * 1000;
const MAX_PROCESSING_AGE_MS = 50 * 1000; // reply token: within 1 minute of receiving webhook.

export function isReplyTokenEligible(event, receivedAtMs, nowMs) {
  if (!Number.isFinite(receivedAtMs) || !Number.isFinite(nowMs) ||
      nowMs - receivedAtMs >= MAX_PROCESSING_AGE_MS) return false;

  // The original reply token remains usable for about a minute after
  // receiving the webhook, not a minute after event.timestamp.
  if (event?.deliveryContext?.isRedelivery !== true) return true;

  // A redelivered webhook keeps the same token. LINE also caps it to
  // 20 minutes from the event's occurrence, independent of receipt time.
  const eventTime = Number(event.timestamp);
  const age = nowMs - eventTime;
  return Number.isFinite(eventTime) && eventTime > 0 &&
    age >= -60000 && age < REDELIVERY_MAX_EVENT_AGE_MS;
}

export function observedLegacyReply(messageText) {
  // Only the basic echo has been observed in the user's screenshot.
  return ('收到你的訊息：' + String(messageText).slice(0, 4700) +
    '\nAI 台股投資系統正在建置中。').slice(0, 4900);
}

function response(text, status) {
  return new Response(text, {
    status, headers: { 'content-type': 'text/plain; charset=utf-8' }
  });
}

// Store methods: recordInbound(record), claimReply(eventId),
// completeReply(eventId, attemptKey), failReply(eventId, attemptKey).
// The store may be a fake for tests; do not connect it to production until
// the SQL migration and least-privilege role are separately approved.
export function createSingleAccountCandidate({
  query, store, sendReply, lookupExactStockName, channelSecret,
  enabled = true, standaloneChipEnabled = false, now = Date.now
}) {
  return async function fetchHandler(request) {
    const path = new URL(request.url).pathname;
    if (request.method === 'GET' && path === '/health') return response('ok', 200);
    if (path !== '/' && path !== '/webhook') return response('Not found', 404);
    if (request.method !== 'POST') return response('Method not allowed', 405);
    if (!enabled || !channelSecret) return response('Service unavailable', 503);
    if (!store || !['recordInbound', 'claimReply', 'completeReply', 'failReply']
      .every(method => typeof store[method] === 'function')) {
      return response('Reply storage unavailable', 503);
    }

    const size = Number(request.headers.get('content-length'));
    if (Number.isFinite(size) && size > MAX_WEBHOOK_BYTES) {
      return response('Payload too large', 413);
    }
    const rawBody = await request.text();
    if (Buffer.byteLength(rawBody, 'utf8') > MAX_WEBHOOK_BYTES) {
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

    const receivedAtMs = now();
    for (const event of payload.events) {
      // Unknown legacy events are NOT presumed to be compatible.
      if (event?.type !== 'message' || event.mode === 'standby' ||
          event.source?.type !== 'user' || event.message?.type !== 'text' ||
          typeof event.message.text !== 'string' ||
          typeof event.replyToken !== 'string' || !event.replyToken) continue;
      if (typeof event.webhookEventId !== 'string' || !event.webhookEventId) {
        return response('Missing event ID', 400);
      }

      const parsed = parseStockCode(event.message.text);
      let matchedBareName = false;
      if (parsed.kind === 'name' && !parsed.explicit &&
          typeof lookupExactStockName === 'function') {
        try { matchedBareName = await lookupExactStockName(parsed.name) === true; }
        catch { return response('Stock name lookup temporarily unavailable', 502); }
      }
      const plan = planLineEvent(event, { matchedBareName });
      if (!plan.record) return response('Invalid event record', 400);

      // Inbound log is idempotent and distinct from reply outcome.
      // A duplicate log must NOT suppress retry of a failed reply.
      try {
        await store.recordInbound(plan.record);
      } catch {
        return response('Temporary record failure', 502);
      }

      // The original reply is time-limited relative to webhook receipt.
      // Redelivered tokens additionally expire 20 minutes after the event.
      // Skip unsafe attempts while keeping the existing report recipient log.
      if (!isReplyTokenEligible(event, receivedAtMs, now())) continue;

      let claim;
      try { claim = await store.claimReply(event.webhookEventId); }
      catch { return response('Temporary claim failure', 502); }

      if (!claim.acquired) {
        if (claim.reason === 'busy') return response('Reply in progress', 503);
        // 'sent' or 'exhausted': never send a second reply on this delivery.
        continue;
      }

      const id = event.webhookEventId;
      const key = claim.attemptKey;
      let answer;
      if (plan.route === 'stock') {
        try { answer = await buildReplyText(event.message.text, query,
          { standaloneChipEnabled }); }
        catch { answer = '目前無法讀取分析資料，請稍後再試。'; }
      } else {
        answer = observedLegacyReply(event.message.text);
      }

      // An expensive DB query or prior event can use up the reply window.
      if (!isReplyTokenEligible(event, receivedAtMs, now())) {
        try { await store.failReply(id, key); } catch { /* retry remains bounded */ }
        return response('Reply window exceeded', 503);
      }

      try {
        await sendReply(event.replyToken, answer.slice(0, 4900));
      } catch {
        // LINE may have accepted a reply even if HTTP acknowledgement was
        // lost. Reusing the same reply token cannot send a second successful
        // reply if it has already been consumed, but it may return an error.
        try { await store.failReply(id, key); } catch { /* surface 502 */ }
        return response('Temporary reply failure', 502);
      }

      try {
        await store.completeReply(id, key);
      } catch {
        // Reply might have been sent; avoid claiming exact-once guarantees.
        return response('Reply outcome unconfirmed', 502);
      }
    }
    return response('OK', 200);
  };
}
