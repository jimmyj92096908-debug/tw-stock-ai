CREATE TABLE IF NOT EXISTS market_index_prices(
 index_code TEXT NOT NULL,
 trade_date DATE NOT NULL,
 close NUMERIC(18,4) NOT NULL CHECK(close>0),
 source TEXT NOT NULL,
 retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 PRIMARY KEY(index_code,trade_date)
);
CREATE INDEX IF NOT EXISTS idx_market_index_prices_date ON market_index_prices(index_code,trade_date);
CREATE TABLE IF NOT EXISTS strategy_backtest_benchmark_summary(
 run_id BIGINT NOT NULL REFERENCES strategy_backtest_runs(run_id) ON DELETE CASCADE,
 market TEXT NOT NULL,
 stock_id VARCHAR(6) NOT NULL,
 horizon TEXT NOT NULL CHECK(horizon IN ('short','swing','long')),
 strategy_return_pct NUMERIC(12,4) NOT NULL,
 stock_buy_hold_return_pct NUMERIC(12,4),
 taiex_return_pct NUMERIC(12,4),
 strategy_excess_vs_stock_pct NUMERIC(12,4),
 strategy_excess_vs_taiex_pct NUMERIC(12,4),
 data_start DATE,
 data_end DATE,
 PRIMARY KEY(run_id,market,stock_id,horizon)
);
CREATE TABLE IF NOT EXISTS strategy_backtest_regime_summary(
 run_id BIGINT NOT NULL REFERENCES strategy_backtest_runs(run_id) ON DELETE CASCADE,
 horizon TEXT NOT NULL CHECK(horizon IN ('short','swing','long')),
 market_regime TEXT NOT NULL CHECK(market_regime IN ('BULL','BEAR','SIDEWAYS','UNKNOWN')),
 trades INTEGER NOT NULL,
 wins INTEGER NOT NULL,
 win_rate NUMERIC(8,3),
 net_profit NUMERIC(18,2) NOT NULL,
 profit_factor NUMERIC(12,4),
 PRIMARY KEY(run_id,horizon,market_regime)
);
