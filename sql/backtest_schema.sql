CREATE TABLE IF NOT EXISTS backtest_runs (
 run_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 config JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS backtest_summary (
 run_id BIGINT NOT NULL REFERENCES backtest_runs(run_id) ON DELETE CASCADE,
 market TEXT NOT NULL,
 stock_id VARCHAR(6) NOT NULL,
 horizon TEXT NOT NULL CHECK(horizon IN ('short','swing','long')),
 trades INTEGER NOT NULL,
 wins INTEGER NOT NULL,
 losses INTEGER NOT NULL,
 win_rate NUMERIC(8,3),
 net_profit NUMERIC(18,2) NOT NULL,
 total_return_pct NUMERIC(12,4) NOT NULL,
 cagr_pct NUMERIC(12,4),
 profit_factor NUMERIC(12,4),
 max_drawdown_pct NUMERIC(12,4) NOT NULL,
 ending_equity NUMERIC(18,2) NOT NULL,
 avg_trade_pct NUMERIC(12,4),
 data_start DATE,
 data_end DATE,
 metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
 PRIMARY KEY(run_id,market,stock_id,horizon)
);
CREATE TABLE IF NOT EXISTS backtest_trades (
 trade_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 run_id BIGINT NOT NULL REFERENCES backtest_runs(run_id) ON DELETE CASCADE,
 market TEXT NOT NULL,
 stock_id VARCHAR(6) NOT NULL,
 horizon TEXT NOT NULL CHECK(horizon IN ('short','swing','long')),
 entry_date DATE NOT NULL,
 exit_date DATE NOT NULL,
 entry_price NUMERIC(18,6) NOT NULL,
 exit_price NUMERIC(18,6) NOT NULL,
 shares BIGINT NOT NULL,
 pnl NUMERIC(18,2) NOT NULL,
 return_pct NUMERIC(12,4) NOT NULL,
 holding_days INTEGER NOT NULL,
 entry_score NUMERIC(6,2) NOT NULL,
 exit_reason TEXT NOT NULL,
 planned_risk NUMERIC(18,2) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_backtest_summary_run ON backtest_summary(run_id,horizon);
CREATE INDEX IF NOT EXISTS idx_backtest_trades_run ON backtest_trades(run_id,market,stock_id,horizon);
