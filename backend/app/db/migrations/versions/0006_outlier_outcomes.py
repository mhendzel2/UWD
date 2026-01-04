"""Add outlier outcomes and method stats tables for feedback loop.

Revision ID: 0006_outlier_outcomes
Revises: 0005_add_options_flow_source
Create Date: 2026-01-04

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0006_outlier_outcomes"
down_revision = "0005_add_options_flow_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the outcome label enum
    outlier_outcome_label = postgresql.ENUM(
        "WIN", "LOSS", "NEUTRAL",
        name="outlier_outcome_label",
        create_type=False,
    )
    outlier_outcome_label.create(op.get_bind(), checkfirst=True)

    # Create outlier_outcomes table
    op.create_table(
        "outlier_outcomes",
        sa.Column("outcome_id", sa.dialects.postgresql.UUID(), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("underlying_symbol", sa.String(32), nullable=False),
        sa.Column("option_symbol", sa.String(64), nullable=True),
        sa.Column("method", sa.String(32), nullable=False),
        sa.Column("score", sa.Numeric(14, 6), nullable=False),
        sa.Column("flow_sentiment", sa.Numeric(10, 6), nullable=True),
        sa.Column("flow_adjusted_score", sa.Numeric(14, 6), nullable=True),
        sa.Column("oi_diff", sa.Numeric(14, 2), nullable=True),
        sa.Column("strike", sa.Numeric(12, 4), nullable=True),
        sa.Column("dte", sa.Integer(), nullable=True),
        sa.Column("sector", sa.String(64), nullable=True),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("entry_price_underlying", sa.Numeric(12, 4), nullable=True),
        sa.Column("entry_price_option", sa.Numeric(12, 4), nullable=True),
        sa.Column("exit_date", sa.Date(), nullable=True),
        sa.Column("exit_price_underlying", sa.Numeric(12, 4), nullable=True),
        sa.Column("exit_price_option", sa.Numeric(12, 4), nullable=True),
        sa.Column("holding_days", sa.Integer(), nullable=True),
        sa.Column("return_1d", sa.Numeric(10, 6), nullable=True),
        sa.Column("return_5d", sa.Numeric(10, 6), nullable=True),
        sa.Column("return_20d", sa.Numeric(10, 6), nullable=True),
        sa.Column(
            "outcome_label",
            postgresql.ENUM("WIN", "LOSS", "NEUTRAL", name="outlier_outcome_label", create_type=False),
            nullable=True,
        ),
        sa.Column("win_threshold_used", sa.Numeric(6, 4), nullable=False, server_default="0.05"),
        sa.Column("loss_threshold_used", sa.Numeric(6, 4), nullable=False, server_default="-0.05"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("outcome_id"),
        sa.UniqueConstraint("event_date", "underlying_symbol", "option_symbol", "method", name="uq_outlier_outcome"),
    )
    op.create_index("ix_outlier_outcomes_date", "outlier_outcomes", ["event_date"])
    op.create_index("ix_outlier_outcomes_underlying", "outlier_outcomes", ["underlying_symbol"])
    op.create_index("ix_outlier_outcomes_method", "outlier_outcomes", ["method"])
    op.create_index("ix_outlier_outcomes_label", "outlier_outcomes", ["outcome_label"])

    # Create outlier_method_stats table
    op.create_table(
        "outlier_method_stats",
        sa.Column("stats_id", sa.dialects.postgresql.UUID(), nullable=False),
        sa.Column("method", sa.String(32), nullable=False),
        sa.Column("underlying_symbol", sa.String(32), nullable=True),
        sa.Column("sector", sa.String(64), nullable=True),
        sa.Column("lookback_days", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("total_signals", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("win_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("loss_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("neutral_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("win_rate", sa.Numeric(6, 4), nullable=True),
        sa.Column("avg_return", sa.Numeric(10, 6), nullable=True),
        sa.Column("median_return", sa.Numeric(10, 6), nullable=True),
        sa.Column("sharpe_ratio", sa.Numeric(10, 6), nullable=True),
        sa.Column("best_return", sa.Numeric(10, 6), nullable=True),
        sa.Column("worst_return", sa.Numeric(10, 6), nullable=True),
        sa.Column("recommended_score_threshold", sa.Numeric(10, 4), nullable=True),
        sa.Column("computed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("stats_id"),
        sa.UniqueConstraint("method", "underlying_symbol", "sector", "lookback_days", name="uq_method_stats"),
    )
    op.create_index("ix_method_stats_method", "outlier_method_stats", ["method"])
    op.create_index("ix_method_stats_underlying", "outlier_method_stats", ["underlying_symbol"])


def downgrade() -> None:
    op.drop_table("outlier_method_stats")
    op.drop_table("outlier_outcomes")
    op.execute("DROP TYPE IF EXISTS outlier_outcome_label")
