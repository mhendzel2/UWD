"""Add correlation runs table.

Revision ID: 0007_correlations
Revises: 0006_outlier_outcomes
Create Date: 2026-01-10

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0007_correlations"
down_revision = "0006_outlier_outcomes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "correlation_runs",
        sa.Column("run_id", sa.dialects.postgresql.UUID(), nullable=False),
        sa.Column("session_id", sa.dialects.postgresql.UUID(), nullable=False),
        sa.Column("asof_date", sa.Date(), nullable=False),
        sa.Column("version", sa.String(length=16), nullable=False, server_default="v1"),
        sa.Column("computed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("results", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id"),
        sa.UniqueConstraint("session_id", "asof_date", "version", name="uq_correlation_run"),
    )
    op.create_index("ix_correlation_runs_session", "correlation_runs", ["session_id"])
    op.create_index("ix_correlation_runs_date", "correlation_runs", ["asof_date"])


def downgrade() -> None:
    op.drop_index("ix_correlation_runs_date", table_name="correlation_runs")
    op.drop_index("ix_correlation_runs_session", table_name="correlation_runs")
    op.drop_table("correlation_runs")
