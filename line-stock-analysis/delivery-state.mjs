// NOT DEPLOYED. SQL adapters for the candidate single-account webhook.
// The stock analysis production entrypoint still only uses SELECT.
import { randomUUID } from 'node:crypto';

export const RECORD_INBOUND_SQL = `
INSERT INTO public.line_messages
  (event_id, line_user_id, message_type, message_text)
VALUES ($1, $2, 'text', $3)
ON CONFLICT (event_id) DO NOTHING
RETURNING event_id
`.trim();

export const CLAIM_REPLY_SQL = `
INSERT INTO public.line_reply_delivery
  (event_id, state, attempts, attempt_key, lease_until)
VALUES ($1, 'sending', 1, $2::uuid, NOW() + INTERVAL '30 seconds')
ON CONFLICT (event_id) DO UPDATE
SET state = 'sending',
    attempts = public.line_reply_delivery.attempts + 1,
    attempt_key = EXCLUDED.attempt_key,
    lease_until = EXCLUDED.lease_until,
    updated_at = NOW()
WHERE public.line_reply_delivery.attempts < 3
  AND (
    public.line_reply_delivery.state = 'retryable'
    OR (
      public.line_reply_delivery.state = 'sending'
      AND public.line_reply_delivery.lease_until < NOW()
    )
  )
RETURNING event_id, attempt_key, attempts
`.trim();

export const READ_REPLY_STATE_SQL = `
SELECT state, attempts FROM public.line_reply_delivery WHERE event_id = $1
`.trim();

export const COMPLETE_REPLY_SQL = `
UPDATE public.line_reply_delivery
SET state = 'sent', lease_until = NULL, updated_at = NOW()
WHERE event_id = $1 AND attempt_key = $2::uuid AND state = 'sending'
RETURNING event_id
`.trim();

export const FAIL_REPLY_SQL = `
UPDATE public.line_reply_delivery
SET state = 'retryable', lease_until = NULL, updated_at = NOW()
WHERE event_id = $1 AND attempt_key = $2::uuid AND state = 'sending'
RETURNING event_id
`.trim();

function hasRow(result) {
  return Array.isArray(result?.rows) && result.rows.length > 0;
}

export function createDeliveryStore(runSql, { newAttemptKey = randomUUID } = {}) {
  if (typeof runSql !== 'function') throw new TypeError('SQL executor required');
  return {
    async recordInbound(record) {
      if (!record || !record.event_id || !record.line_user_id ||
          record.message_type !== 'text' || typeof record.message_text !== 'string') {
        throw new TypeError('Invalid direct-user text record');
      }
      // Existing report discovers distinct text senders; conflict is NOT a
      // reason to suppress the LINE reply, because reply state is separate.
      await runSql(RECORD_INBOUND_SQL, [
        record.event_id, record.line_user_id, record.message_text
      ]);
    },

    async claimReply(eventId) {
      if (typeof eventId !== 'string' || !eventId) {
        throw new TypeError('Webhook event ID required');
      }
      const attemptKey = newAttemptKey();
      const claimed = await runSql(CLAIM_REPLY_SQL, [eventId, attemptKey]);
      if (hasRow(claimed)) return { acquired: true, attemptKey };
      const read = await runSql(READ_REPLY_STATE_SQL, [eventId]);
      const state = read.rows?.[0]?.state;
      if (state === 'sent') return { acquired: false, reason: 'sent' };
      if (read.rows?.[0]?.attempts >= 3) {
        return { acquired: false, reason: 'exhausted' };
      }
      return { acquired: false, reason: 'busy' };
    },

    async completeReply(eventId, attemptKey) {
      const result = await runSql(COMPLETE_REPLY_SQL, [eventId, attemptKey]);
      if (!hasRow(result)) throw new Error('Could not confirm reply completion');
    },

    async failReply(eventId, attemptKey) {
      const result = await runSql(FAIL_REPLY_SQL, [eventId, attemptKey]);
      if (!hasRow(result)) throw new Error('Could not release reply claim');
    }
  };
}
