"""Add backtesting tables: backtest_runs, simulated_trades, daily_equity_curve

Revision ID: 0003_backtest_tables
Revises: 0002_v1_upgrade
Create Date: 2025-12-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0003_backtest_tables"
down_revision = "0002_v1_upgrade"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create exit_reason enum
    exit_reason_values = [
        "PROFIT_TARGET",
        "STOP_LOSS",
        "TIME_EXIT",
        "END_OF_DAY",
        "END_OF_BACKTEST",
        "MANUAL"
    ]
    # Explicitly create the type if it doesn't exist
    exit_reason_enum = postgresql.ENUM(*exit_reason_values, name="exit_reason")
    exit_reason_enum.create(op.get_bind(), checkfirst=True)

    # Create backtest_runs table
    op.create_table(
        "backtest_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_timestamp", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("strategy_version", sa.String(64), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("initial_capital", sa.Numeric(14, 2), nullable=False, server_default="100000.00"),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("performance_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="RUNNING"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_backtest_runs_strategy", "backtest_runs", ["strategy_version"])
    op.create_index("ix_backtest_runs_status", "backtest_runs", ["status"])

    # Create simulated_trades table
    op.create_table(
        "simulated_trades",
        sa.Column("trade_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "backtest_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("backtest_runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Timing
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        # Instruments
        sa.Column("underlying_symbol", sa.String(32), nullable=False),
        sa.Column("option_symbol", sa.String(64), nullable=True),
        # Strategy
        sa.Column("strategy_name", sa.String(64), nullable=False),
        sa.Column("entry_reason", sa.Text(), nullable=True),
        # Entry
        sa.Column("entry_timestamp", sa.DateTime(), nullable=False),
        sa.Column("entry_price_stock", sa.Numeric(12, 4), nullable=False),
        sa.Column("entry_price_option", sa.Numeric(12, 4), nullable=True),
        sa.Column("position_size", sa.Integer(), nullable=False),
        sa.Column("capital_at_risk", sa.Numeric(14, 2), nullable=False),
        # Exit
        sa.Column("exit_timestamp", sa.DateTime(), nullable=True),
        sa.Column("exit_price_stock", sa.Numeric(12, 4), nullable=True),
        sa.Column("exit_price_option", sa.Numeric(12, 4), nullable=True),
        sa.Column("exit_reason", postgresql.ENUM(*exit_reason_values, name="exit_reason", create_type=False), nullable=True),
        # P&L
        sa.Column("pnl_absolute", sa.Numeric(14, 2), nullable=True),
        sa.Column("pnl_percentage", sa.Numeric(10, 6), nullable=True),
        # MFE/MAE
        sa.Column("max_favorable_excursion", sa.Numeric(10, 6), nullable=True),
        sa.Column("max_adverse_excursion", sa.Numeric(10, 6), nullable=True),
        # Context
        sa.Column("signal_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("greeks_at_entry", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("holding_minutes", sa.Integer(), nullable=True),
        # Constraint
        sa.CheckConstraint("position_size > 0", name="ck_positive_position"),
    )
    op.create_index("ix_simulated_trades_run", "simulated_trades", ["backtest_run_id"])
    op.create_index("ix_simulated_trades_underlying", "simulated_trades", ["underlying_symbol"])
    op.create_index("ix_simulated_trades_trade_date", "simulated_trades", ["trade_date"])
    op.create_index("ix_simulated_trades_strategy", "simulated_trades", ["strategy_name"])

    # Create daily_equity_curve table
    op.create_table(
        "daily_equity_curve",
        sa.Column("curve_point_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "backtest_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("backtest_runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        # Portfolio state
        sa.Column("portfolio_value", sa.Numeric(14, 2), nullable=False),
        sa.Column("cash_balance", sa.Numeric(14, 2), nullable=False),
        sa.Column("open_positions_value", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("open_positions_count", sa.Integer(), nullable=False, server_default="0"),
        # Daily metrics
        sa.Column("daily_pnl", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("daily_return_pct", sa.Numeric(10, 6), nullable=True),
        # Drawdown
        sa.Column("peak_value", sa.Numeric(14, 2), nullable=False),
        sa.Column("drawdown_pct", sa.Numeric(10, 6), nullable=False, server_default="0"),
        # Trade counts
        sa.Column("trades_opened", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("trades_closed", sa.Integer(), nullable=False, server_default="0"),
        # Unique constraint
        sa.UniqueConstraint("backtest_run_id", "date", name="uq_equity_curve_day"),
    )
    op.create_index("ix_equity_curve_run", "daily_equity_curve", ["backtest_run_id"])
    op.create_index("ix_equity_curve_date", "daily_equity_curve", ["date"])


def downgrade() -> None:
    op.drop_table("daily_equity_curve")
    op.drop_table("simulated_trades")
    op.drop_table("backtest_runs")
    
    # Drop the enum type
    sa.Enum(name="exit_reason").drop(op.get_bind(), checkfirst=True)
