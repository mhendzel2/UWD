"""Add OPTIONS_FLOW raw source

Revision ID: 0005_add_options_flow_source
Revises: 0004_anomalies
Create Date: 2026-01-04
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0005_add_options_flow_source"
down_revision = "0004_anomalies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Postgres enum ALTER TYPE ADD VALUE may require autocommit depending on DB settings.
    # Alembic runs migrations in a transaction by default; explicitly commit first.
    op.execute("COMMIT")
    op.execute("ALTER TYPE raw_source ADD VALUE IF NOT EXISTS 'OPTIONS_FLOW'")


def downgrade() -> None:
    # Enum value removal is not supported in Postgres without recreating the type.
    pass
