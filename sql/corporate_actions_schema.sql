-- Corporate actions and split/dividend-adjusted daily bars.
-- Factors are sourced from official exchange/MOPS announcements and apply to bars
-- strictly BEFORE ex_date. Raw daily_prices are never modified.
CREATE TABLE IF NOT EXISTS corporate_actions (
  market TEXT NOT NULL CHECK (market IN ('twse','tpex')),
  stock_id VARCHAR(6) NOT NULL,
  ex_date DATE NOT NULL,
  action_type TEXT NOT NULL CHECK (action_type IN
    ('STOCK_SPLIT','REVERSE_SPLIT','STOCK_DIVIDEND','CASH_DIVIDEND','CAPITAL_REDUCTION','FACE_VALUE_CHANGE','OTHER')),
  price_factor NUMERIC(24,12) NOT NULL CHECK (price_factor > 0),
  share_factor NUMERIC(24,12) NOT NULL CHECK (share_factor > 0),
  cash_amount NUMERIC(18,6),
  stock_amount NUMERIC(18,6),
  source TEXT NOT NULL,
  source_event_id TEXT NOT NULL,
  verified BOOLEAN NOT NULL DEFAULT FALSE,
  notes TEXT NOT NULL DEFAULT '',
  raw_data JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (market, stock_id, ex_date, source_event_id),
  FOREIGN KEY (market,stock_id) REFERENCES stock_master(market,stock_id)
    ON UPDATE CASCADE ON DELETE RESTRICT
);
-- Idempotent constraint migration for databases created before FACE_VALUE_CHANGE.
ALTER TABLE corporate_actions DROP CONSTRAINT IF EXISTS corporate_actions_action_type_check;
ALTER TABLE corporate_actions ADD CONSTRAINT corporate_actions_action_type_check
  CHECK (action_type IN
    ('STOCK_SPLIT','REVERSE_SPLIT','STOCK_DIVIDEND','CASH_DIVIDEND','CAPITAL_REDUCTION','FACE_VALUE_CHANGE','OTHER'));
CREATE INDEX IF NOT EXISTS idx_corporate_actions_stock_date
  ON corporate_actions(market,stock_id,ex_date);

CREATE TABLE IF NOT EXISTS daily_adjusted_prices (
  market TEXT NOT NULL CHECK (market IN ('twse','tpex')),
  stock_id VARCHAR(6) NOT NULL,
  trade_date DATE NOT NULL,
  open NUMERIC(24,10), high NUMERIC(24,10), low NUMERIC(24,10), close NUMERIC(24,10),
  volume NUMERIC(30,4), turnover NUMERIC(24,2), price_change NUMERIC(24,10),
  transactions BIGINT,
  price_adjustment_factor NUMERIC(24,12) NOT NULL,
  share_adjustment_factor NUMERIC(24,12) NOT NULL,
  adjustment_status TEXT NOT NULL CHECK (adjustment_status IN ('ADJUSTED','UNADJUSTED')),
  calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (market,stock_id,trade_date),
  FOREIGN KEY (market,stock_id,trade_date)
    REFERENCES daily_prices(market,stock_id,trade_date) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_daily_adjusted_prices_stock_date
  ON daily_adjusted_prices(market,stock_id,trade_date DESC);

ALTER TABLE corporate_actions ADD COLUMN IF NOT EXISTS raw_data JSONB NOT NULL DEFAULT '{}'::jsonb;
