"""Add anomaly event and ticker rollup tables

Revision ID: 0004_anomalies
Revises: 0003_backtest_tables
Create Date: 2026-01-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0004_anomalies"
down_revision = "0003_backtest_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    raw_source_enum = sa.Enum(
        "OI_DIFF",
        "BOT_EOD",
        "HOT_CHAINS",
        "DARKPOOL_EOD",
        "STOCK_SCREENER",
        name="raw_source",
        create_type=False,
    )

    op.create_table(
        "anomaly_events",
        sa.Column("anomaly_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", raw_source_enum, nullable=False),
        sa.Column("event_key", sa.String(length=255), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("severity_score", sa.Numeric(14, 6), nullable=False),
        sa.Column("ensemble_score", sa.Numeric(10, 6), nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("feature_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("raw_ref", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("computed_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("session_id", "source", "event_key", name="uq_anomaly_event_key"),
    )
    op.create_index(
        "ix_anomaly_events_session_severity",
        "anomaly_events",
        ["session_id", "severity_score"],
        postgresql_ops={"severity_score": "DESC"},
    )
    op.create_index(
        "ix_anomaly_events_session_ticker",
        "anomaly_events",
        ["session_id", "ticker"],
    )
    op.create_index(
        "ix_anomaly_events_session_source",
        "anomaly_events",
        ["session_id", "source"],
    )

    op.create_table(
        "anomaly_ticker_rollups",
        sa.Column("rollup_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("severity_score", sa.Numeric(14, 6), nullable=False),
        sa.Column("ensemble_score", sa.Numeric(10, 6), nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("feature_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_ref", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("computed_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("session_id", "ticker", name="uq_anomaly_ticker"),
    )
    op.create_index(
        "ix_anomaly_rollups_session_severity",
        "anomaly_ticker_rollups",
        ["session_id", "severity_score"],
        postgresql_ops={"severity_score": "DESC"},
    )
    op.create_index(
        "ix_anomaly_rollups_session_ticker",
        "anomaly_ticker_rollups",
        ["session_id", "ticker"],
    )


def downgrade() -> None:
    op.drop_index("ix_anomaly_rollups_session_ticker", table_name="anomaly_ticker_rollups")
    op.drop_index("ix_anomaly_rollups_session_severity", table_name="anomaly_ticker_rollups")
    op.drop_table("anomaly_ticker_rollups")

    op.drop_index("ix_anomaly_events_session_source", table_name="anomaly_events")
    op.drop_index("ix_anomaly_events_session_ticker", table_name="anomaly_events")
    op.drop_index("ix_anomaly_events_session_severity", table_name="anomaly_events")
    op.drop_table("anomaly_events")
