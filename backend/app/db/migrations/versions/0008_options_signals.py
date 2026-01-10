"""Add options signals tables.

Revision ID: 0008_options_signals
Revises: 0007_correlations
Create Date: 2026-01-12
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_options_signals"
down_revision = "0007_correlations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "opt_trades_raw",
        sa.Column("trade_id", sa.String(length=64), nullable=False),
        sa.Column("executed_at_utc", sa.DateTime(), nullable=False),
        sa.Column("executed_at_market", sa.DateTime(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("underlying_symbol", sa.String(length=32), nullable=False),
        sa.Column("option_chain_id", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=True),
        sa.Column("strike", sa.Numeric(12, 4), nullable=True),
        sa.Column("option_type", sa.String(length=8), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("underlying_price", sa.Numeric(12, 4), nullable=True),
        sa.Column("nbbo_bid", sa.Numeric(12, 4), nullable=True),
        sa.Column("nbbo_ask", sa.Numeric(12, 4), nullable=True),
        sa.Column("ewma_nbbo_bid", sa.Numeric(12, 4), nullable=True),
        sa.Column("ewma_nbbo_ask", sa.Numeric(12, 4), nullable=True),
        sa.Column("price", sa.Numeric(12, 4), nullable=True),
        sa.Column("size", sa.Integer(), nullable=True),
        sa.Column("premium", sa.Numeric(14, 2), nullable=True),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.Column("open_interest", sa.Integer(), nullable=True),
        sa.Column("implied_volatility", sa.Numeric(10, 6), nullable=True),
        sa.Column("delta", sa.Numeric(12, 6), nullable=True),
        sa.Column("theta", sa.Numeric(12, 6), nullable=True),
        sa.Column("gamma", sa.Numeric(12, 6), nullable=True),
        sa.Column("vega", sa.Numeric(12, 6), nullable=True),
        sa.Column("rho", sa.Numeric(12, 6), nullable=True),
        sa.Column("theo", sa.Numeric(12, 6), nullable=True),
        sa.Column("sector", sa.String(length=64), nullable=True),
        sa.Column("exchange", sa.String(length=32), nullable=True),
        sa.Column("report_flags", sa.String(length=64), nullable=True),
        sa.Column("canceled", sa.Boolean(), nullable=True),
        sa.Column("upstream_condition_detail", sa.Text(), nullable=True),
        sa.Column("equity_type", sa.String(length=32), nullable=True),
        sa.Column("trade_direction", sa.String(length=24), nullable=True),
        sa.Column("nbbo_valid", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("excluded_reason", sa.String(length=64), nullable=True),
        sa.Column("is_excluded", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("trade_id"),
    )
    op.create_index("ix_opt_trades_raw_date_underlying", "opt_trades_raw", ["trade_date", "underlying_symbol"])
    op.create_index("ix_opt_trades_raw_chain", "opt_trades_raw", ["option_chain_id"])

    op.create_table(
        "eq_ohlcv_daily",
        sa.Column("ohlcv_id", sa.dialects.postgresql.UUID(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("underlying_symbol", sa.String(length=32), nullable=False),
        sa.Column("open", sa.Numeric(12, 4), nullable=True),
        sa.Column("high", sa.Numeric(12, 4), nullable=True),
        sa.Column("low", sa.Numeric(12, 4), nullable=True),
        sa.Column("close", sa.Numeric(12, 4), nullable=True),
        sa.Column("adj_close", sa.Numeric(12, 4), nullable=True),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("ohlcv_id"),
        sa.UniqueConstraint("trade_date", "underlying_symbol", name="uq_eq_ohlcv_daily"),
    )
    op.create_index("ix_eq_ohlcv_daily_symbol", "eq_ohlcv_daily", ["underlying_symbol"])

    op.create_table(
        "mkt_context_daily",
        sa.Column("context_id", sa.dialects.postgresql.UUID(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("spx_close", sa.Numeric(12, 4), nullable=True),
        sa.Column("spx_return_1d", sa.Numeric(12, 6), nullable=True),
        sa.Column("spx_return_5d", sa.Numeric(12, 6), nullable=True),
        sa.Column("vix_close", sa.Numeric(12, 4), nullable=True),
        sa.Column("vix_change_1d", sa.Numeric(12, 6), nullable=True),
        sa.Column("vix_change_5d", sa.Numeric(12, 6), nullable=True),
        sa.Column("t10y_yield", sa.Numeric(12, 6), nullable=True),
        sa.Column("t10y_change_1d", sa.Numeric(12, 6), nullable=True),
        sa.Column("t10y_change_5d", sa.Numeric(12, 6), nullable=True),
        sa.Column("credit_spread", sa.Numeric(12, 6), nullable=True),
        sa.Column("wti_close", sa.Numeric(12, 4), nullable=True),
        sa.Column("wti_ret_1d", sa.Numeric(12, 6), nullable=True),
        sa.PrimaryKeyConstraint("context_id"),
        sa.UniqueConstraint("trade_date", name="uq_mkt_context_daily"),
    )

    op.create_table(
        "sector_context_daily",
        sa.Column("context_id", sa.dialects.postgresql.UUID(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("sector_or_etf", sa.String(length=64), nullable=False),
        sa.Column("close", sa.Numeric(12, 4), nullable=True),
        sa.Column("return_1d", sa.Numeric(12, 6), nullable=True),
        sa.Column("return_5d", sa.Numeric(12, 6), nullable=True),
        sa.Column("realized_vol_20d", sa.Numeric(12, 6), nullable=True),
        sa.PrimaryKeyConstraint("context_id"),
        sa.UniqueConstraint("trade_date", "sector_or_etf", name="uq_sector_context_daily"),
    )
    op.create_index("ix_sector_context_sector", "sector_context_daily", ["sector_or_etf"])

    op.create_table(
        "news_sentiment_daily",
        sa.Column("news_id", sa.dialects.postgresql.UUID(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("underlying_symbol", sa.String(length=32), nullable=False),
        sa.Column("article_count_24h", sa.Integer(), nullable=True),
        sa.Column("sentiment_mean", sa.Numeric(10, 6), nullable=True),
        sa.Column("sentiment_std", sa.Numeric(10, 6), nullable=True),
        sa.Column("sentiment_abs_mean", sa.Numeric(10, 6), nullable=True),
        sa.Column("source_count", sa.Integer(), nullable=True),
        sa.Column("news_missing", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.PrimaryKeyConstraint("news_id"),
        sa.UniqueConstraint("trade_date", "underlying_symbol", name="uq_news_sentiment_daily"),
    )
    op.create_index("ix_news_sentiment_symbol", "news_sentiment_daily", ["underlying_symbol"])

    op.create_table(
        "opt_agg_underlying_daily",
        sa.Column("agg_id", sa.dialects.postgresql.UUID(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("underlying_symbol", sa.String(length=32), nullable=False),
        sa.Column("sector", sa.String(length=64), nullable=True),
        sa.Column("call_volume", sa.Numeric(14, 2), nullable=True),
        sa.Column("put_volume", sa.Numeric(14, 2), nullable=True),
        sa.Column("call_premium", sa.Numeric(16, 2), nullable=True),
        sa.Column("put_premium", sa.Numeric(16, 2), nullable=True),
        sa.Column("call_trade_count", sa.Integer(), nullable=True),
        sa.Column("put_trade_count", sa.Integer(), nullable=True),
        sa.Column("avg_iv_call", sa.Numeric(10, 6), nullable=True),
        sa.Column("avg_iv_put", sa.Numeric(10, 6), nullable=True),
        sa.Column("avg_iv_all", sa.Numeric(10, 6), nullable=True),
        sa.Column("oi_call_eod", sa.Numeric(14, 2), nullable=True),
        sa.Column("oi_put_eod", sa.Numeric(14, 2), nullable=True),
        sa.Column("oi_change_call", sa.Numeric(14, 2), nullable=True),
        sa.Column("oi_change_put", sa.Numeric(14, 2), nullable=True),
        sa.Column("pct_trades_missing_nbbo", sa.Numeric(8, 4), nullable=True),
        sa.Column("put_call_vol_ratio", sa.Numeric(12, 6), nullable=True),
        sa.Column("put_call_prem_ratio", sa.Numeric(12, 6), nullable=True),
        sa.Column("call_buy_premium", sa.Numeric(16, 2), nullable=True),
        sa.Column("call_sell_premium", sa.Numeric(16, 2), nullable=True),
        sa.Column("put_buy_premium", sa.Numeric(16, 2), nullable=True),
        sa.Column("put_sell_premium", sa.Numeric(16, 2), nullable=True),
        sa.Column("net_call_premium", sa.Numeric(16, 2), nullable=True),
        sa.Column("net_put_premium", sa.Numeric(16, 2), nullable=True),
        sa.Column("net_premium", sa.Numeric(16, 2), nullable=True),
        sa.Column("net_delta", sa.Numeric(16, 4), nullable=True),
        sa.Column("net_gamma", sa.Numeric(16, 4), nullable=True),
        sa.Column("net_vega", sa.Numeric(16, 4), nullable=True),
        sa.Column("net_premium_atm_calls", sa.Numeric(16, 2), nullable=True),
        sa.Column("net_premium_atm_puts", sa.Numeric(16, 2), nullable=True),
        sa.Column("net_premium_otm_calls", sa.Numeric(16, 2), nullable=True),
        sa.Column("net_premium_otm_puts", sa.Numeric(16, 2), nullable=True),
        sa.Column("net_premium_deep_otm_calls", sa.Numeric(16, 2), nullable=True),
        sa.Column("net_premium_deep_otm_puts", sa.Numeric(16, 2), nullable=True),
        sa.PrimaryKeyConstraint("agg_id"),
        sa.UniqueConstraint("trade_date", "underlying_symbol", name="uq_opt_agg_underlying_daily"),
    )
    op.create_index("ix_opt_agg_underlying_symbol", "opt_agg_underlying_daily", ["underlying_symbol"])

    op.create_table(
        "opt_agg_contract_daily",
        sa.Column("agg_id", sa.dialects.postgresql.UUID(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("option_chain_id", sa.String(length=64), nullable=False),
        sa.Column("underlying_symbol", sa.String(length=32), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("option_type", sa.String(length=8), nullable=True),
        sa.Column("strike", sa.Numeric(12, 4), nullable=True),
        sa.Column("contract_volume", sa.Numeric(14, 2), nullable=True),
        sa.Column("contract_premium", sa.Numeric(16, 2), nullable=True),
        sa.Column("contract_trade_count", sa.Integer(), nullable=True),
        sa.Column("iv_last", sa.Numeric(10, 6), nullable=True),
        sa.Column("iv_vwap", sa.Numeric(10, 6), nullable=True),
        sa.Column("delta_last", sa.Numeric(12, 6), nullable=True),
        sa.Column("gamma_last", sa.Numeric(12, 6), nullable=True),
        sa.Column("vega_last", sa.Numeric(12, 6), nullable=True),
        sa.Column("oi_eod", sa.Numeric(14, 2), nullable=True),
        sa.Column("uoa_volume_z", sa.Numeric(12, 6), nullable=True),
        sa.Column("uoa_premium_z", sa.Numeric(12, 6), nullable=True),
        sa.Column("uoa_vo_i", sa.Numeric(12, 6), nullable=True),
        sa.Column("is_uoa", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.PrimaryKeyConstraint("agg_id"),
        sa.UniqueConstraint("trade_date", "option_chain_id", name="uq_opt_agg_contract_daily"),
    )
    op.create_index("ix_opt_agg_contract_chain", "opt_agg_contract_daily", ["option_chain_id"])

    op.create_table(
        "features_underlying_daily",
        sa.Column("feature_id", sa.dialects.postgresql.UUID(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("underlying_symbol", sa.String(length=32), nullable=False),
        sa.Column("sector", sa.String(length=64), nullable=True),
        sa.Column("computed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("call_volume", sa.Numeric(14, 2), nullable=True),
        sa.Column("put_volume", sa.Numeric(14, 2), nullable=True),
        sa.Column("call_premium", sa.Numeric(16, 2), nullable=True),
        sa.Column("put_premium", sa.Numeric(16, 2), nullable=True),
        sa.Column("put_call_vol_ratio", sa.Numeric(12, 6), nullable=True),
        sa.Column("put_call_prem_ratio", sa.Numeric(12, 6), nullable=True),
        sa.Column("call_buy_premium", sa.Numeric(16, 2), nullable=True),
        sa.Column("call_sell_premium", sa.Numeric(16, 2), nullable=True),
        sa.Column("put_buy_premium", sa.Numeric(16, 2), nullable=True),
        sa.Column("put_sell_premium", sa.Numeric(16, 2), nullable=True),
        sa.Column("net_call_premium", sa.Numeric(16, 2), nullable=True),
        sa.Column("net_put_premium", sa.Numeric(16, 2), nullable=True),
        sa.Column("net_premium", sa.Numeric(16, 2), nullable=True),
        sa.Column("net_delta", sa.Numeric(16, 4), nullable=True),
        sa.Column("net_gamma", sa.Numeric(16, 4), nullable=True),
        sa.Column("net_vega", sa.Numeric(16, 4), nullable=True),
        sa.Column("iv_vwap_all", sa.Numeric(10, 6), nullable=True),
        sa.Column("iv_vwap_call", sa.Numeric(10, 6), nullable=True),
        sa.Column("iv_vwap_put", sa.Numeric(10, 6), nullable=True),
        sa.Column("net_premium_atm_calls", sa.Numeric(16, 2), nullable=True),
        sa.Column("net_premium_atm_puts", sa.Numeric(16, 2), nullable=True),
        sa.Column("net_premium_otm_calls", sa.Numeric(16, 2), nullable=True),
        sa.Column("net_premium_otm_puts", sa.Numeric(16, 2), nullable=True),
        sa.Column("net_premium_deep_otm_calls", sa.Numeric(16, 2), nullable=True),
        sa.Column("net_premium_deep_otm_puts", sa.Numeric(16, 2), nullable=True),
        sa.Column("uoa_contract_count", sa.Integer(), nullable=True),
        sa.Column("uoa_max_volume_z", sa.Numeric(12, 6), nullable=True),
        sa.Column("uoa_max_vo_i", sa.Numeric(12, 6), nullable=True),
        sa.Column("uoa_total_premium", sa.Numeric(16, 2), nullable=True),
        sa.Column("iv_25d_call", sa.Numeric(10, 6), nullable=True),
        sa.Column("iv_25d_put", sa.Numeric(10, 6), nullable=True),
        sa.Column("skew_25d", sa.Numeric(10, 6), nullable=True),
        sa.Column("iv_front", sa.Numeric(10, 6), nullable=True),
        sa.Column("iv_back", sa.Numeric(10, 6), nullable=True),
        sa.Column("term_structure", sa.Numeric(10, 6), nullable=True),
        sa.Column("close", sa.Numeric(12, 4), nullable=True),
        sa.Column("ret_1d", sa.Numeric(12, 6), nullable=True),
        sa.Column("ret_5d", sa.Numeric(12, 6), nullable=True),
        sa.Column("ret_10d", sa.Numeric(12, 6), nullable=True),
        sa.Column("ret_20d", sa.Numeric(12, 6), nullable=True),
        sa.Column("sma_20", sa.Numeric(12, 6), nullable=True),
        sa.Column("sma_50", sa.Numeric(12, 6), nullable=True),
        sa.Column("ema_12", sa.Numeric(12, 6), nullable=True),
        sa.Column("ema_26", sa.Numeric(12, 6), nullable=True),
        sa.Column("rsi_14", sa.Numeric(12, 6), nullable=True),
        sa.Column("macd", sa.Numeric(12, 6), nullable=True),
        sa.Column("macd_signal", sa.Numeric(12, 6), nullable=True),
        sa.Column("macd_hist", sa.Numeric(12, 6), nullable=True),
        sa.Column("bb_mid", sa.Numeric(12, 6), nullable=True),
        sa.Column("bb_std", sa.Numeric(12, 6), nullable=True),
        sa.Column("bb_upper", sa.Numeric(12, 6), nullable=True),
        sa.Column("bb_lower", sa.Numeric(12, 6), nullable=True),
        sa.Column("bb_width", sa.Numeric(12, 6), nullable=True),
        sa.Column("bb_pct", sa.Numeric(12, 6), nullable=True),
        sa.Column("rv_10", sa.Numeric(12, 6), nullable=True),
        sa.Column("rv_20", sa.Numeric(12, 6), nullable=True),
        sa.Column("is_new_20d_high", sa.Boolean(), nullable=True),
        sa.Column("is_new_20d_low", sa.Boolean(), nullable=True),
        sa.Column("iv_atm_proxy", sa.Numeric(10, 6), nullable=True),
        sa.Column("iv_minus_rv20", sa.Numeric(12, 6), nullable=True),
        sa.Column("iv_to_rv20_ratio", sa.Numeric(12, 6), nullable=True),
        sa.Column("iv_rank_252", sa.Numeric(12, 6), nullable=True),
        sa.Column("rv20_z", sa.Numeric(12, 6), nullable=True),
        sa.Column("iv_atm_proxy_change_1d", sa.Numeric(12, 6), nullable=True),
        sa.Column("iv_atm_proxy_change_5d", sa.Numeric(12, 6), nullable=True),
        sa.Column("rv_10_change_5d", sa.Numeric(12, 6), nullable=True),
        sa.Column("news_count", sa.Integer(), nullable=True),
        sa.Column("sentiment_mean", sa.Numeric(10, 6), nullable=True),
        sa.Column("sentiment_abs", sa.Numeric(10, 6), nullable=True),
        sa.Column("sentiment_change_1d", sa.Numeric(10, 6), nullable=True),
        sa.Column("news_count_z_60", sa.Numeric(12, 6), nullable=True),
        sa.Column("news_missing", sa.Boolean(), nullable=True),
        sa.Column("spx_ret_1d", sa.Numeric(12, 6), nullable=True),
        sa.Column("spx_ret_5d", sa.Numeric(12, 6), nullable=True),
        sa.Column("vix_level", sa.Numeric(12, 6), nullable=True),
        sa.Column("vix_change_1d", sa.Numeric(12, 6), nullable=True),
        sa.Column("vix_change_5d", sa.Numeric(12, 6), nullable=True),
        sa.Column("t10y_change_1d", sa.Numeric(12, 6), nullable=True),
        sa.Column("t10y_change_5d", sa.Numeric(12, 6), nullable=True),
        sa.Column("wti_ret_1d", sa.Numeric(12, 6), nullable=True),
        sa.Column("sector_ret_1d", sa.Numeric(12, 6), nullable=True),
        sa.Column("sector_ret_5d", sa.Numeric(12, 6), nullable=True),
        sa.Column("sector_rv_20", sa.Numeric(12, 6), nullable=True),
        sa.Column("pct_trades_missing_nbbo", sa.Numeric(8, 4), nullable=True),
        sa.PrimaryKeyConstraint("feature_id"),
        sa.UniqueConstraint("trade_date", "underlying_symbol", name="uq_features_underlying_daily"),
    )
    op.create_index("ix_features_underlying_symbol", "features_underlying_daily", ["underlying_symbol"])

    op.create_table(
        "signals_underlying_daily",
        sa.Column("signal_id", sa.dialects.postgresql.UUID(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("underlying_symbol", sa.String(length=32), nullable=False),
        sa.Column("signal_name", sa.String(length=32), nullable=False),
        sa.Column("score", sa.Numeric(14, 6), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("explanation_json", sa.JSON(), nullable=True),
        sa.Column("thresholds_triggered", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("signal_id"),
        sa.UniqueConstraint("trade_date", "underlying_symbol", "signal_name", name="uq_signals_underlying_daily"),
    )
    op.create_index("ix_signals_underlying_date_signal", "signals_underlying_daily", ["trade_date", "signal_name"])
    op.create_index("ix_signals_underlying_score", "signals_underlying_daily", ["signal_name", "score"])

    op.create_table(
        "alerts_event_log",
        sa.Column("event_id", sa.dialects.postgresql.UUID(), nullable=False),
        sa.Column("event_ts", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("underlying_symbol", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_alerts_event_date", "alerts_event_log", ["trade_date"])
    op.create_index("ix_alerts_event_symbol", "alerts_event_log", ["underlying_symbol"])

    op.create_table(
        "options_signals_data_quality_daily",
        sa.Column("quality_id", sa.dialects.postgresql.UUID(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("total_trades", sa.Integer(), nullable=True),
        sa.Column("canceled_filtered", sa.Integer(), nullable=True),
        sa.Column("trades_missing_nbbo", sa.Integer(), nullable=True),
        sa.Column("symbols_missing_ohlcv", sa.Integer(), nullable=True),
        sa.Column("symbols_missing_news", sa.Integer(), nullable=True),
        sa.Column("freshness_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("quality_id"),
        sa.UniqueConstraint("trade_date", name="uq_options_signals_quality_daily"),
    )


def downgrade() -> None:
    op.drop_table("options_signals_data_quality_daily")
    op.drop_index("ix_alerts_event_symbol", table_name="alerts_event_log")
    op.drop_index("ix_alerts_event_date", table_name="alerts_event_log")
    op.drop_table("alerts_event_log")
    op.drop_index("ix_signals_underlying_score", table_name="signals_underlying_daily")
    op.drop_index("ix_signals_underlying_date_signal", table_name="signals_underlying_daily")
    op.drop_table("signals_underlying_daily")
    op.drop_index("ix_features_underlying_symbol", table_name="features_underlying_daily")
    op.drop_table("features_underlying_daily")
    op.drop_index("ix_opt_agg_contract_chain", table_name="opt_agg_contract_daily")
    op.drop_table("opt_agg_contract_daily")
    op.drop_index("ix_opt_agg_underlying_symbol", table_name="opt_agg_underlying_daily")
    op.drop_table("opt_agg_underlying_daily")
    op.drop_index("ix_news_sentiment_symbol", table_name="news_sentiment_daily")
    op.drop_table("news_sentiment_daily")
    op.drop_index("ix_sector_context_sector", table_name="sector_context_daily")
    op.drop_table("sector_context_daily")
    op.drop_table("mkt_context_daily")
    op.drop_index("ix_eq_ohlcv_daily_symbol", table_name="eq_ohlcv_daily")
    op.drop_table("eq_ohlcv_daily")
    op.drop_index("ix_opt_trades_raw_chain", table_name="opt_trades_raw")
    op.drop_index("ix_opt_trades_raw_date_underlying", table_name="opt_trades_raw")
    op.drop_table("opt_trades_raw")
