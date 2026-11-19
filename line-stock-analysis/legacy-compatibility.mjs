// Proposed compatibility contract only — NOT imported by the deployed function.
// Current LINE daily-report job discovers recipients from public.line_messages
// where message_type='text'. This module prepares records; it performs NO SQL
// and sends NO LINE replies. Legacy behaviors must be audited before cutover.
import { parseStockCode } from './handler.mjs';

const STOCK_KINDS = new Set(['stock', 'rank', 'list', 'excluded']);

export function planLineEvent(event) {
  if (!event || event.type !== 'message' || event.message?.type !== 'text') {
    // Existing handler may have follow/non-text behavior; never silently replace it.
    return { route: 'legacy', record: null };
  }

  const rawText = event.message.text;
  if (typeof rawText !== 'string') return { route: 'legacy', record: null };
  const parsed = parseStockCode(rawText);

  // The future integrated handler must avoid capturing arbitrary group IDs as
  // private daily-report recipients. Do not store/send them during this dry run.
  const directUser = event.source?.type === 'user' &&
    typeof event.source.userId === 'string' && event.source.userId.length > 0;
  const eventId = event.webhookEventId;
  const hasEventId = typeof eventId === 'string' && eventId.length > 0;

  const record = directUser && hasEventId
    ? Object.freeze({
        event_id: eventId,
        line_user_id: event.source.userId,
        message_type: 'text',
        message_text: rawText
      })
    : null;

  // Never invent an old webhook fallback response. Legacy source is unavailable.
  return {
    route: STOCK_KINDS.has(parsed.kind) ? 'stock' : 'legacy',
    record
  };
}

// Future SQL contract for authorized implementation, NOT executed here:
// INSERT INTO public.line_messages
//   (event_id, line_user_id, message_type, message_text)
// VALUES ($1, $2, 'text', $3)
// ON CONFLICT (event_id) DO NOTHING
