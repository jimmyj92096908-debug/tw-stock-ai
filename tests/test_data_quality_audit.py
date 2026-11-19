from data_quality_audit import summarize, render_markdown


def sample():
    return {
        "market_coverage": [
            {"market": "twse", "master_symbols": 100, "symbols_with_prices": 10, "coverage_pct": 10.0},
            {"market": "tpex", "master_symbols": 50, "symbols_with_prices": 5, "coverage_pct": 10.0},
        ],
        "price_integrity": [
            {"market": "twse", "rows": 100, "missing_ohlc": 2, "missing_volume": 1, "nonpositive_prices": 0, "invalid_ohlc": 1, "negative_volume": 0},
            {"market": "tpex", "rows": 50, "missing_ohlc": 0, "missing_volume": 0, "nonpositive_prices": 0, "invalid_ohlc": 0, "negative_volume": 0},
        ],
        "duplicate_keys": [{"market": "twse", "stock_id": "2330", "trade_date": "2026-01-01", "duplicate_count": 2}],
        "stale_symbols": [{"market": "tpex", "stock_id": "9999", "last_trade_date": "2025-01-01"}],
        "history_coverage": [{"market": "twse", "five_year_symbols": 4, "symbols_with_data": 10}, {"market": "tpex", "five_year_symbols": 3, "symbols_with_data": 5}],
        "latest_date_coverage": [{"market": "twse", "latest_trade_date": "2026-11-18", "symbols_on_latest_date": 8}],
    }


def test_summary_aggregates_market_coverage_and_issues():
    result = summarize(sample())
    assert result["master_symbols"] == 150
    assert result["symbols_with_prices"] == 15
    assert result["coverage_pct"] == 10.0
    assert result["bad_price_rows_counted"] == 4
    assert result["duplicate_key_groups"] == 1
    assert result["stale_symbols_listed"] == 1
    assert result["symbols_with_five_year_history"] == 7


def test_markdown_report_includes_market_breakdown_and_read_only_note():
    report = render_markdown(summarize(sample()))
    assert "Coverage by market" in report
    assert "twse" in report
    assert "read-only" in report
