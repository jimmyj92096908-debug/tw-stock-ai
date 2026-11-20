-- FUTURE MIGRATION ONLY: NEVER executed by the LINE test workflows.
-- The existing line_messages is the daily report recipient source.
-- This separate table tracks only webhookEventId, not user identifiers or text.
-- Review, back up, and authorize DB writes before applying.
CREATE TABLE IF NOT EXISTS public.line_reply_delivery (
    event_id TEXT PRIMARY KEY,
    state TEXT NOT NULL CHECK (state IN ('sending', 'retryable', 'sent')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),
    attempt_key UUID,
    lease_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (
        (state = 'sending' AND attempt_key IS NOT NULL AND lease_until IS NOT NULL)
        OR
        (state IN ('retryable', 'sent') AND lease_until IS NULL)
    )
);

COMMENT ON TABLE public.line_reply_delivery IS
  'Proposed LINE reply attempt tracker; requires separate approval before use.';
