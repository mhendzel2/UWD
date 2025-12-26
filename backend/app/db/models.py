import uuid
from datetime import date, datetime
from enum import Enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum as PgEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class StrategyMode(str, Enum):
    INDEX_EOD = "INDEX_EOD"
    EQUITY_THU_EOD = "EQUITY_THU_EOD"


class RawSource(str, Enum):
    OI_DIFF = "OI_DIFF"
    BOT_EOD = "BOT_EOD"
    HOT_CHAINS = "HOT_CHAINS"
    DARKPOOL_EOD = "DARKPOOL_EOD"
    STOCK_SCREENER = "STOCK_SCREENER"


class ParseStatus(str, Enum):
    OK = "OK"
    ERROR = "ERROR"


class RegimeLabel(str, Enum):
    PIN_RANGE = "PIN_RANGE"
    TREND_RISK = "TREND_RISK"
    MIXED_NO_TRADE = "MIXED_NO_TRADE"


class ConfidenceTier(str, Enum):
    LOW = "LOW"
    MED = "MED"
    HIGH = "HIGH"


class PlanType(str, Enum):
    NO_TRADE = "NO_TRADE"
    PIN_WALL_CONDITIONAL = "PIN_WALL_CONDITIONAL"
    TREND_BREACH_CONDITIONAL = "TREND_BREACH_CONDITIONAL"


class LogLevel(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


class OutcomeLabel(str, Enum):
    PIN_RANGE = "PIN_RANGE"
    TREND = "TREND"
    MIXED = "MIXED"


class BriefType(str, Enum):
    FLOW_SHORT_TERM = "FLOW_SHORT_TERM"
    VOL_SELL_PREMIUM = "VOL_SELL_PREMIUM"
    VOL_BUY_PREMIUM = "VOL_BUY_PREMIUM"


class UnderlyingUniverse(str, Enum):
    INDEX = "INDEX"
    EQUITY = "EQUITY"
    MIXED = "MIXED"


class DominantHorizonHint(str, Enum):
    SHORT = "SHORT"
    MEDIUM = "MEDIUM"
    LONG = "LONG"
    MIXED = "MIXED"


class Session(Base):
    __tablename__ = "sessions"

    session_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date = Column(Date, nullable=False)
    strategy_mode = Column(PgEnum(StrategyMode, name="strategy_mode"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    data_window = Column(JSONB, nullable=True)
    notes = Column(Text, nullable=True)

    raw_files = relationship("RawFile", back_populates="session", cascade="all, delete-orphan")
    features = relationship("FeaturesUnderlyingDay", back_populates="session", cascade="all, delete-orphan")
    regimes = relationship("RegimeDecision", back_populates="session", cascade="all, delete-orphan")
    plans = relationship("Plan", back_populates="session", cascade="all, delete-orphan")
    logs = relationship("LogMessage", back_populates="session", cascade="all, delete-orphan")
    daily_briefs = relationship("DailyBrief", back_populates="session", cascade="all, delete-orphan")
    ensembles = relationship("EnsembleDecision", back_populates="session", cascade="all, delete-orphan")


class RawFile(Base):
    __tablename__ = "raw_files"

    file_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False)
    source = Column(PgEnum(RawSource, name="raw_source"), nullable=False)
    filename = Column(String(255), nullable=False)
    sha256 = Column(String(128), nullable=False)
    rows = Column(Integer, nullable=False, default=0)
    imported_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    parse_status = Column(PgEnum(ParseStatus, name="parse_status"), nullable=False, default=ParseStatus.OK)
    error_message = Column(Text, nullable=True)
    extras = Column(JSONB, nullable=True)

    session = relationship("Session", back_populates="raw_files")


class FeaturesUnderlyingDay(Base):
    __tablename__ = "features_underlying_day"
    __table_args__ = (
        UniqueConstraint("session_id", "underlying", "asof_date", name="uq_features_day"),
    )

    feature_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False)
    underlying = Column(String(32), nullable=False)
    asof_date = Column(Date, nullable=False)
    feature_version = Column(String(16), nullable=False, default="v0")
    computed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Boolean features
    oi_concentrated = Column(Boolean, default=False)
    oi_symmetric = Column(Boolean, default=False)
    oi_one_sided = Column(Boolean, default=False)
    oi_multileg_dominant = Column(Boolean, default=False)
    hc_high_turnover = Column(Boolean, default=False)
    hc_balanced_flow = Column(Boolean, default=False)
    hc_sweep_dominant = Column(Boolean, default=False)
    hc_multileg_dominant = Column(Boolean, default=False)
    hc_liquidity_churn = Column(Boolean, default=False)
    bot_overpay_present = Column(Boolean, default=False)
    bot_aggressive_present = Column(Boolean, default=False)
    bot_gamma_concentrated = Column(Boolean, default=False)
    ss_implied_move_high = Column(Boolean, default=False)
    ss_directional_skew = Column(Boolean, default=False)
    ss_iv_high = Column(Boolean, default=False)
    dp_meaningful = Column(Boolean, default=False)
    dp_accumulation_bias = Column(Boolean, default=False)
    dp_distribution_bias = Column(Boolean, default=False)

    # Numeric support payload
    numeric_context = Column(JSONB, nullable=True)
    oi_persistence_3d = Column(Numeric(10, 4), nullable=True)
    hot_chain_persistence_3d = Column(Numeric(10, 4), nullable=True)
    intent_persistence_3d = Column(Numeric(10, 4), nullable=True)
    regime_last = Column(PgEnum(RegimeLabel, name="regime_label"), nullable=True)
    regime_switch_rate_10d = Column(Numeric(10, 4), nullable=True)
    range_pct_5d_mean = Column(Numeric(12, 6), nullable=True)
    range_pct_5d_std = Column(Numeric(12, 6), nullable=True)
    volume_to_avg30 = Column(Numeric(12, 6), nullable=True)

    session = relationship("Session", back_populates="features")
    regime = relationship("RegimeDecision", back_populates="feature", uselist=False)


class RegimeDecision(Base):
    __tablename__ = "regime_decisions"
    __table_args__ = (
        UniqueConstraint("session_id", "underlying", "asof_date", name="uq_regime_day"),
    )

    decision_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False)
    underlying = Column(String(32), nullable=False)
    asof_date = Column(Date, nullable=False)
    regime_label = Column(PgEnum(RegimeLabel, name="regime_label"), nullable=False)
    confidence_tier = Column(PgEnum(ConfidenceTier, name="confidence_tier"), nullable=False)
    reasons = Column(JSONB, nullable=False)
    conflicts = Column(JSONB, nullable=True)
    decision_version = Column(String(16), nullable=False, default="v0")
    computed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    dominant_horizon_hint = Column(PgEnum(DominantHorizonHint, name="dominant_horizon_hint"), nullable=True)
    ecology_state = Column(JSONB, nullable=True)
    ecology_version = Column(String(16), nullable=False, default="v0")

    feature_id = Column(UUID(as_uuid=True), ForeignKey("features_underlying_day.feature_id", ondelete="CASCADE"), nullable=True)

    session = relationship("Session", back_populates="regimes")
    feature = relationship("FeaturesUnderlyingDay", back_populates="regime")
    plan = relationship("Plan", back_populates="regime", uselist=False)


class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = (
        UniqueConstraint("session_id", "underlying", "trade_date", name="uq_plan_day"),
    )

    plan_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False)
    underlying = Column(String(32), nullable=False)
    trade_date = Column(Date, nullable=False)
    plan_type = Column(PgEnum(PlanType, name="plan_type"), nullable=False)
    staged_contracts = Column(JSONB, nullable=True)
    entry_conditions = Column(JSONB, nullable=True)
    risk_limits = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    regime_id = Column(UUID(as_uuid=True), ForeignKey("regime_decisions.decision_id", ondelete="SET NULL"), nullable=True)

    session = relationship("Session", back_populates="plans")
    regime = relationship("RegimeDecision", back_populates="plan")


class OutcomeDay(Base):
    __tablename__ = "outcomes_day"
    __table_args__ = (UniqueConstraint("trade_date", "underlying", name="uq_outcome_day"),)

    outcome_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trade_date = Column(Date, nullable=False)
    underlying = Column(String(32), nullable=False)
    realized_label_manual = Column(PgEnum(OutcomeLabel, name="outcome_label"), nullable=True)
    range_pct = Column(Numeric(6, 4), nullable=True)
    close_vs_open_pct = Column(Numeric(6, 4), nullable=True)
    breach_events = Column(JSONB, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class LogMessage(Base):
    __tablename__ = "logs"

    log_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False)
    ts = Column(DateTime, default=datetime.utcnow, nullable=False)
    level = Column(PgEnum(LogLevel, name="log_level"), nullable=False, default=LogLevel.INFO)
    message = Column(Text, nullable=False)
    context = Column(JSONB, nullable=True)

    session = relationship("Session", back_populates="logs")


class DailyBrief(Base):
    __tablename__ = "daily_briefs"

    brief_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    brief_type = Column(PgEnum(BriefType, name="brief_type"), nullable=False)
    underlying_universe = Column(PgEnum(UnderlyingUniverse, name="underlying_universe"), nullable=True)
    entries = Column(JSONB, nullable=False)
    generated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    brief_version = Column(Text, nullable=False, default="v1")

    session = relationship("Session", back_populates="daily_briefs")


class EnsembleDecision(Base):
    __tablename__ = "ensemble_decisions"
    __table_args__ = (
        UniqueConstraint("session_id", "underlying", "asof_date", name="uq_ensemble_day"),
    )

    ensemble_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False)
    underlying = Column(String(32), nullable=False)
    asof_date = Column(Date, nullable=False)
    ensemble_label = Column(PgEnum(RegimeLabel, name="regime_label"), nullable=False)
    ensemble_confidence = Column(Numeric(10, 4), nullable=True)
    horizon_weights = Column(JSONB, nullable=True)
    component_votes = Column(JSONB, nullable=True)
    stability_metrics = Column(JSONB, nullable=True)
    ensemble_version = Column(String(16), nullable=False, default="v1")
    computed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session = relationship("Session", back_populates="ensembles")


class ModelWeights(Base):
    __tablename__ = "model_weights"
    __table_args__ = (UniqueConstraint("asof_date", name="uq_model_weights_date"),)

    weights_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asof_date = Column(Date, nullable=False)
    weights = Column(JSONB, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    version = Column(String(16), nullable=False, default="v1")
