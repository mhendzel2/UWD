"""initial schema"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    strategy_mode = sa.Enum("INDEX_EOD", "EQUITY_THU_EOD", name="strategy_mode")
    raw_source = sa.Enum("OI_DIFF", "BOT_EOD", "HOT_CHAINS", "DARKPOOL_EOD", "STOCK_SCREENER", name="raw_source")
    parse_status = sa.Enum("OK", "ERROR", name="parse_status")
    regime_label = sa.Enum("PIN_RANGE", "TREND_RISK", "MIXED_NO_TRADE", name="regime_label")
    confidence_tier = sa.Enum("LOW", "MED", "HIGH", name="confidence_tier")
    plan_type = sa.Enum("NO_TRADE", "PIN_WALL_CONDITIONAL", "TREND_BREACH_CONDITIONAL", name="plan_type")
    log_level = sa.Enum("INFO", "WARN", "ERROR", name="log_level")
    outcome_label = sa.Enum("PIN_RANGE", "TREND", "MIXED", name="outcome_label")

    op.create_table(
        "sessions",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("strategy_mode", strategy_mode, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("data_window", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )

    op.create_table(
        "raw_files",
        sa.Column("file_id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", raw_source, nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=128), nullable=False),
        sa.Column("rows", sa.Integer(), nullable=False, default=0),
        sa.Column("imported_at", sa.DateTime(), nullable=False),
        sa.Column("parse_status", parse_status, nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("extras", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.create_table(
        "features_underlying_day",
        sa.Column("feature_id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("underlying", sa.String(length=32), nullable=False),
        sa.Column("asof_date", sa.Date(), nullable=False),
        sa.Column("feature_version", sa.String(length=16), nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.Column("oi_concentrated", sa.Boolean(), default=False),
        sa.Column("oi_symmetric", sa.Boolean(), default=False),
        sa.Column("oi_one_sided", sa.Boolean(), default=False),
        sa.Column("oi_multileg_dominant", sa.Boolean(), default=False),
        sa.Column("hc_high_turnover", sa.Boolean(), default=False),
        sa.Column("hc_balanced_flow", sa.Boolean(), default=False),
        sa.Column("hc_sweep_dominant", sa.Boolean(), default=False),
        sa.Column("hc_multileg_dominant", sa.Boolean(), default=False),
        sa.Column("hc_liquidity_churn", sa.Boolean(), default=False),
        sa.Column("bot_overpay_present", sa.Boolean(), default=False),
        sa.Column("bot_aggressive_present", sa.Boolean(), default=False),
        sa.Column("bot_gamma_concentrated", sa.Boolean(), default=False),
        sa.Column("ss_implied_move_high", sa.Boolean(), default=False),
        sa.Column("ss_directional_skew", sa.Boolean(), default=False),
        sa.Column("ss_iv_high", sa.Boolean(), default=False),
        sa.Column("dp_meaningful", sa.Boolean(), default=False),
        sa.Column("dp_accumulation_bias", sa.Boolean(), default=False),
        sa.Column("dp_distribution_bias", sa.Boolean(), default=False),
        sa.Column("numeric_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.UniqueConstraint("session_id", "underlying", "asof_date", name="uq_features_day"),
    )

    op.create_table(
        "regime_decisions",
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("underlying", sa.String(length=32), nullable=False),
        sa.Column("asof_date", sa.Date(), nullable=False),
        sa.Column("regime_label", regime_label, nullable=False),
        sa.Column("confidence_tier", confidence_tier, nullable=False),
        sa.Column("reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("conflicts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("decision_version", sa.String(length=16), nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.Column("feature_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("features_underlying_day.feature_id", ondelete="CASCADE"), nullable=True),
        sa.UniqueConstraint("session_id", "underlying", "asof_date", name="uq_regime_day"),
    )

    op.create_table(
        "plans",
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("underlying", sa.String(length=32), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("plan_type", plan_type, nullable=False),
        sa.Column("staged_contracts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("entry_conditions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("risk_limits", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("regime_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("regime_decisions.decision_id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("session_id", "underlying", "trade_date", name="uq_plan_day"),
    )

    op.create_table(
        "outcomes_day",
        sa.Column("outcome_id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("underlying", sa.String(length=32), nullable=False),
        sa.Column("realized_label_manual", outcome_label, nullable=True),
        sa.Column("range_pct", sa.Numeric(6, 4), nullable=True),
        sa.Column("close_vs_open_pct", sa.Numeric(6, 4), nullable=True),
        sa.Column("breach_events", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("trade_date", "underlying", name="uq_outcome_day"),
    )

    op.create_table(
        "logs",
        sa.Column("log_id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("level", log_level, nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("logs")
    op.drop_table("outcomes_day")
    op.drop_table("plans")
    op.drop_table("regime_decisions")
    op.drop_table("features_underlying_day")
    op.drop_table("raw_files")
    op.drop_table("sessions")
    sa.Enum(name="strategy_mode").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="raw_source").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="parse_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="regime_label").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="confidence_tier").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="plan_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="log_level").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="outcome_label").drop(op.get_bind(), checkfirst=True)
