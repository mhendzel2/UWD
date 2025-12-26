"""v1 upgrade: briefs, ecology, ensemble, persistence"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0002_v1_upgrade"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    brief_type = sa.Enum("FLOW_SHORT_TERM", "VOL_SELL_PREMIUM", "VOL_BUY_PREMIUM", name="brief_type")
    underlying_universe = sa.Enum("INDEX", "EQUITY", "MIXED", name="underlying_universe")
    dominant_horizon_hint = sa.Enum("SHORT", "MEDIUM", "LONG", "MIXED", name="dominant_horizon_hint")
    regime_label = sa.Enum("PIN_RANGE", "TREND_RISK", "MIXED_NO_TRADE", name="regime_label", create_type=False)

    brief_type.create(op.get_bind(), checkfirst=True)
    underlying_universe.create(op.get_bind(), checkfirst=True)
    dominant_horizon_hint.create(op.get_bind(), checkfirst=True)

    op.add_column("features_underlying_day", sa.Column("oi_persistence_3d", sa.Numeric(10, 4), nullable=True))
    op.add_column("features_underlying_day", sa.Column("hot_chain_persistence_3d", sa.Numeric(10, 4), nullable=True))
    op.add_column("features_underlying_day", sa.Column("intent_persistence_3d", sa.Numeric(10, 4), nullable=True))
    op.add_column("features_underlying_day", sa.Column("regime_last", regime_label, nullable=True))
    op.add_column("features_underlying_day", sa.Column("regime_switch_rate_10d", sa.Numeric(10, 4), nullable=True))
    op.add_column("features_underlying_day", sa.Column("range_pct_5d_mean", sa.Numeric(12, 6), nullable=True))
    op.add_column("features_underlying_day", sa.Column("range_pct_5d_std", sa.Numeric(12, 6), nullable=True))
    op.add_column("features_underlying_day", sa.Column("volume_to_avg30", sa.Numeric(12, 6), nullable=True))

    op.add_column(
        "regime_decisions",
        sa.Column("dominant_horizon_hint", dominant_horizon_hint, nullable=True),
    )
    op.add_column(
        "regime_decisions",
        sa.Column("ecology_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "regime_decisions",
        sa.Column("ecology_version", sa.String(length=16), nullable=False, server_default="v0"),
    )

    op.create_table(
        "daily_briefs",
        sa.Column("brief_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("brief_type", brief_type, nullable=False),
        sa.Column("underlying_universe", underlying_universe, nullable=True),
        sa.Column("entries", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("brief_version", sa.Text(), nullable=False, server_default="v1"),
    )

    op.create_table(
        "ensemble_decisions",
        sa.Column("ensemble_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("underlying", sa.String(length=32), nullable=False),
        sa.Column("asof_date", sa.Date(), nullable=False),
        sa.Column("ensemble_label", regime_label, nullable=False),
        sa.Column("ensemble_confidence", sa.Numeric(10, 4), nullable=True),
        sa.Column("horizon_weights", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("component_votes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("stability_metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ensemble_version", sa.String(length=16), nullable=False, server_default="v1"),
        sa.Column("computed_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("session_id", "underlying", "asof_date", name="uq_ensemble_day"),
    )

    op.create_table(
        "model_weights",
        sa.Column("weights_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("asof_date", sa.Date(), nullable=False),
        sa.Column("weights", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("version", sa.String(length=16), nullable=False, server_default="v1"),
        sa.UniqueConstraint("asof_date", name="uq_model_weights_date"),
    )


def downgrade() -> None:
    op.drop_table("model_weights")
    op.drop_table("ensemble_decisions")
    op.drop_table("daily_briefs")

    op.drop_column("regime_decisions", "ecology_version")
    op.drop_column("regime_decisions", "ecology_state")
    op.drop_column("regime_decisions", "dominant_horizon_hint")

    op.drop_column("features_underlying_day", "volume_to_avg30")
    op.drop_column("features_underlying_day", "range_pct_5d_std")
    op.drop_column("features_underlying_day", "range_pct_5d_mean")
    op.drop_column("features_underlying_day", "regime_switch_rate_10d")
    op.drop_column("features_underlying_day", "regime_last")
    op.drop_column("features_underlying_day", "intent_persistence_3d")
    op.drop_column("features_underlying_day", "hot_chain_persistence_3d")
    op.drop_column("features_underlying_day", "oi_persistence_3d")

    sa.Enum(name="dominant_horizon_hint").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="underlying_universe").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="brief_type").drop(op.get_bind(), checkfirst=True)
