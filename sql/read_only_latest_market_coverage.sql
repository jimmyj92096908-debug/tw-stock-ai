-- Read-only, latest common market-date coverage. No price fabrication or writes.
-- Run via psql with a read-only role, ideally inside REPEATABLE READ READ ONLY.
-- 'history_60/120/240' count valid rows, not guaranteed contiguous sessions.
-- This stricter (close>0, volume>=0) denominator differs from less strict audits.
WITH latest AS (
  SELECT max(trade_date) AS trade_date
  FROM public.daily_prices WHERE close > 0
),
current_prices AS (
  SELECT p.market, p.stock_id
  FROM public.daily_prices p CROSS JOIN latest l
  WHERE p.trade_date=l.trade_date AND p.close>0 AND p.volume>=0
),
history AS (
  SELECT p.market, p.stock_id,
         count(*) FILTER (WHERE p.close>0 AND p.volume>=0)::int AS valid_price_days
  FROM public.daily_prices p
  JOIN current_prices c USING(market,stock_id)
  CROSS JOIN latest l
  WHERE p.trade_date<=l.trade_date
  GROUP BY p.market,p.stock_id
),
flags AS (
  SELECT h.market,h.stock_id,h.valid_price_days,
    EXISTS (
      SELECT 1 FROM public.daily_technicals t CROSS JOIN latest l
      WHERE t.market=h.market AND t.stock_id=h.stock_id AND t.trade_date=l.trade_date
    ) AS technical,
    EXISTS (
      SELECT 1 FROM public.daily_smc s CROSS JOIN latest l
      WHERE s.market=h.market AND s.stock_id=h.stock_id AND s.trade_date=l.trade_date
    ) AS smc,
    EXISTS (
      SELECT 1 FROM public.daily_composite_scores q CROSS JOIN latest l
      WHERE q.market=h.market AND q.stock_id=h.stock_id
        AND q.as_of_date=l.trade_date AND q.total_score IS NOT NULL
    ) AS scored
  FROM history h
)
SELECT market,
  count(*)::int AS priced,
  count(*) FILTER (WHERE valid_price_days>=60)::int AS history_60,
  count(*) FILTER (WHERE valid_price_days>=120)::int AS history_120,
  count(*) FILTER (WHERE valid_price_days>=240)::int AS history_240,
  count(*) FILTER (WHERE technical)::int AS technical,
  count(*) FILTER (WHERE smc)::int AS smc,
  count(*) FILTER (WHERE scored)::int AS scored,
  count(*) FILTER (WHERE technical AND smc AND scored)::int AS matched,
  count(*) FILTER (
    WHERE valid_price_days>=60 AND NOT (technical AND smc)
  )::int AS eligible_missing_indicators,
  count(*) FILTER (WHERE valid_price_days<60)::int AS blocked_by_history
FROM flags
GROUP BY market ORDER BY market;
