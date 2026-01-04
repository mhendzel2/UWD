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
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    JSON,
    desc,
)
from sqlalchemy.orm import declarative_base, relationship

from app.db.types import GUID

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
    OPTIONS_FLOW = "OPTIONS_FLOW"


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

    session_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    date = Column(Date, nullable=False)
    strategy_mode = Column(PgEnum(StrategyMode, name="strategy_mode"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    data_window = Column(JSON, nullable=True)
    notes = Column(Text, nullable=True)

    raw_files = relationship("RawFile", back_populates="session", cascade="all, delete-orphan")
    features = relationship("FeaturesUnderlyingDay", back_populates="session", cascade="all, delete-orphan")
    regimes = relationship("RegimeDecision", back_populates="session", cascade="all, delete-orphan")
    plans = relationship("Plan", back_populates="session", cascade="all, delete-orphan")
    logs = relationship("LogMessage", back_populates="session", cascade="all, delete-orphan")
    daily_briefs = relationship("DailyBrief", back_populates="session", cascade="all, delete-orphan")
    ensembles = relationship("EnsembleDecision", back_populates="session", cascade="all, delete-orphan")
    anomaly_events = relationship("AnomalyEvent", back_populates="session", cascade="all, delete-orphan")
    anomaly_rollups = relationship("AnomalyTickerRollup", back_populates="session", cascade="all, delete-orphan")


class RawFile(Base):
    __tablename__ = "raw_files"

    file_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    session_id = Column(GUID(), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False)
    source = Column(PgEnum(RawSource, name="raw_source"), nullable=False)
    filename = Column(String(255), nullable=False)
    sha256 = Column(String(128), nullable=False)
    rows = Column(Integer, nullable=False, default=0)
    imported_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    parse_status = Column(PgEnum(ParseStatus, name="parse_status"), nullable=False, default=ParseStatus.OK)
    error_message = Column(Text, nullable=True)
    extras = Column(JSON, nullable=True)

    session = relationship("Session", back_populates="raw_files")


class FeaturesUnderlyingDay(Base):
    __tablename__ = "features_underlying_day"
    __table_args__ = (
        UniqueConstraint("session_id", "underlying", "asof_date", "feature_version", name="uq_features_day"),
    )

    feature_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    session_id = Column(GUID(), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False)
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
    numeric_context = Column(JSON, nullable=True)
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

    decision_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    session_id = Column(GUID(), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False)
    underlying = Column(String(32), nullable=False)
    asof_date = Column(Date, nullable=False)
    regime_label = Column(PgEnum(RegimeLabel, name="regime_label"), nullable=False)
    confidence_tier = Column(PgEnum(ConfidenceTier, name="confidence_tier"), nullable=False)
    reasons = Column(JSON, nullable=False)
    conflicts = Column(JSON, nullable=True)
    decision_version = Column(String(16), nullable=False, default="v0")
    computed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    dominant_horizon_hint = Column(PgEnum(DominantHorizonHint, name="dominant_horizon_hint"), nullable=True)
    ecology_state = Column(JSON, nullable=True)
    ecology_version = Column(String(16), nullable=False, default="v0")

    feature_id = Column(GUID(), ForeignKey("features_underlying_day.feature_id", ondelete="CASCADE"), nullable=True)

    session = relationship("Session", back_populates="regimes")
    feature = relationship("FeaturesUnderlyingDay", back_populates="regime")
    plan = relationship("Plan", back_populates="regime", uselist=False)


class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = (
        UniqueConstraint("session_id", "underlying", "trade_date", name="uq_plan_day"),
    )

    plan_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    session_id = Column(GUID(), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False)
    underlying = Column(String(32), nullable=False)
    trade_date = Column(Date, nullable=False)
    plan_type = Column(PgEnum(PlanType, name="plan_type"), nullable=False)
    staged_contracts = Column(JSON, nullable=True)
    entry_conditions = Column(JSON, nullable=True)
    risk_limits = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    regime_id = Column(GUID(), ForeignKey("regime_decisions.decision_id", ondelete="SET NULL"), nullable=True)

    session = relationship("Session", back_populates="plans")
    regime = relationship("RegimeDecision", back_populates="plan")


class OutcomeDay(Base):
    __tablename__ = "outcomes_day"
    __table_args__ = (UniqueConstraint("trade_date", "underlying", name="uq_outcome_day"),)

    outcome_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    trade_date = Column(Date, nullable=False)
    underlying = Column(String(32), nullable=False)
    realized_label_manual = Column(PgEnum(OutcomeLabel, name="outcome_label"), nullable=True)
    range_pct = Column(Numeric(6, 4), nullable=True)
    close_vs_open_pct = Column(Numeric(6, 4), nullable=True)
    breach_events = Column(JSON, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class LogMessage(Base):
    __tablename__ = "logs"

    log_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    session_id = Column(GUID(), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False)
    ts = Column(DateTime, default=datetime.utcnow, nullable=False)
    level = Column(PgEnum(LogLevel, name="log_level"), nullable=False, default=LogLevel.INFO)
    message = Column(Text, nullable=False)
    context = Column(JSON, nullable=True)

    session = relationship("Session", back_populates="logs")


class AnomalyEvent(Base):
    __tablename__ = "anomaly_events"
    __table_args__ = (
        UniqueConstraint("session_id", "source", "event_key", name="uq_anomaly_event_key"),
        Index("ix_anomaly_events_session_severity", "session_id", desc("severity_score")),
        Index("ix_anomaly_events_session_ticker", "session_id", "ticker"),
        Index("ix_anomaly_events_session_source", "session_id", "source"),
    )

    anomaly_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    session_id = Column(GUID(), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False)
    source = Column(PgEnum(RawSource, name="raw_source"), nullable=False)
    event_key = Column(String(255), nullable=False)
    ticker = Column(String(32), nullable=False)
    severity_score = Column(Numeric(14, 6), nullable=False)
    ensemble_score = Column(Numeric(10, 6), nullable=False)
    reason_codes = Column(JSON, nullable=False)
    feature_payload = Column(JSON, nullable=False)
    raw_ref = Column(JSON, nullable=True)
    computed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session = relationship("Session", back_populates="anomaly_events")


class AnomalyTickerRollup(Base):
    __tablename__ = "anomaly_ticker_rollups"
    __table_args__ = (
        UniqueConstraint("session_id", "ticker", name="uq_anomaly_ticker"),
        Index("ix_anomaly_rollups_session_severity", "session_id", desc("severity_score")),
        Index("ix_anomaly_rollups_session_ticker", "session_id", "ticker"),
    )

    rollup_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    session_id = Column(GUID(), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False)
    ticker = Column(String(32), nullable=False)
    severity_score = Column(Numeric(14, 6), nullable=False)
    ensemble_score = Column(Numeric(10, 6), nullable=False)
    reason_codes = Column(JSON, nullable=False)
    feature_payload = Column(JSON, nullable=True)
    raw_ref = Column(JSON, nullable=True)
    computed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session = relationship("Session", back_populates="anomaly_rollups")


class DailyBrief(Base):
    __tablename__ = "daily_briefs"

    brief_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    session_id = Column(GUID(), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    brief_type = Column(PgEnum(BriefType, name="brief_type"), nullable=False)
    underlying_universe = Column(PgEnum(UnderlyingUniverse, name="underlying_universe"), nullable=True)
    entries = Column(JSON, nullable=False)
    generated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    brief_version = Column(Text, nullable=False, default="v1")

    session = relationship("Session", back_populates="daily_briefs")


class EnsembleDecision(Base):
    __tablename__ = "ensemble_decisions"
    __table_args__ = (
        UniqueConstraint("session_id", "underlying", "asof_date", name="uq_ensemble_day"),
    )

    ensemble_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    session_id = Column(GUID(), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False)
    underlying = Column(String(32), nullable=False)
    asof_date = Column(Date, nullable=False)
    ensemble_label = Column(PgEnum(RegimeLabel, name="regime_label"), nullable=False)
    ensemble_confidence = Column(Numeric(10, 4), nullable=True)
    horizon_weights = Column(JSON, nullable=True)
    component_votes = Column(JSON, nullable=True)
    stability_metrics = Column(JSON, nullable=True)
    ensemble_version = Column(String(16), nullable=False, default="v1")
    computed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session = relationship("Session", back_populates="ensembles")


class ModelWeights(Base):
    __tablename__ = "model_weights"
    __table_args__ = (UniqueConstraint("asof_date", name="uq_model_weights_date"),)

    weights_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    asof_date = Column(Date, nullable=False)
    weights = Column(JSON, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    version = Column(String(16), nullable=False, default="v1")


# =============================================================================
# Backtesting Tables
# =============================================================================

class ExitReason(str, Enum):
    """Reasons for exiting a simulated trade"""
    PROFIT_TARGET = "PROFIT_TARGET"
    STOP_LOSS = "STOP_LOSS"
    TIME_EXIT = "TIME_EXIT"
    END_OF_DAY = "END_OF_DAY"
    END_OF_BACKTEST = "END_OF_BACKTEST"
    MANUAL = "MANUAL"


class BacktestRun(Base):
    """
    Stores metadata for each complete backtesting run.
    Allows comparison of different strategy versions over time.
    """
    __tablename__ = "backtest_runs"

    run_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    run_timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    strategy_version = Column(String(64), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    initial_capital = Column(Numeric(14, 2), nullable=False, default=100000.0)
    
    # Configuration snapshot
    parameters = Column(JSON, nullable=False, default=dict)
    
    # Performance summary (populated after run completes)
    performance_summary = Column(JSON, nullable=True)
    
    # Status tracking
    status = Column(String(32), nullable=False, default="RUNNING")
    error_message = Column(Text, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # Relationships
    trades = relationship("SimulatedTrade", back_populates="backtest_run", cascade="all, delete-orphan")
    equity_curve = relationship("DailyEquityCurve", back_populates="backtest_run", cascade="all, delete-orphan")


class SimulatedTrade(Base):
    """
    Records every detail of each individual simulated trade.
    Designed for deep analysis of trade performance including MFE/MAE.
    """
    __tablename__ = "simulated_trades"
    __table_args__ = (
        CheckConstraint("position_size > 0", name="ck_positive_position"),
    )

    trade_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    backtest_run_id = Column(GUID(), ForeignKey("backtest_runs.run_id", ondelete="CASCADE"), nullable=False)
    
    # Timing
    signal_date = Column(Date, nullable=False)  # When signal was generated (EOD)
    trade_date = Column(Date, nullable=False)   # When trade was executed
    
    # Instruments
    underlying_symbol = Column(String(32), nullable=False)
    option_symbol = Column(String(64), nullable=True)  # Null for stock-only backtests
    
    # Strategy identification
    strategy_name = Column(String(64), nullable=False)
    entry_reason = Column(Text, nullable=True)
    
    # Entry details
    entry_timestamp = Column(DateTime, nullable=False)
    entry_price_stock = Column(Numeric(12, 4), nullable=False)
    entry_price_option = Column(Numeric(12, 4), nullable=True)
    position_size = Column(Integer, nullable=False)
    capital_at_risk = Column(Numeric(14, 2), nullable=False)
    
    # Exit details
    exit_timestamp = Column(DateTime, nullable=True)
    exit_price_stock = Column(Numeric(12, 4), nullable=True)
    exit_price_option = Column(Numeric(12, 4), nullable=True)
    exit_reason = Column(PgEnum(ExitReason, name="exit_reason"), nullable=True)
    
    # P&L metrics
    pnl_absolute = Column(Numeric(14, 2), nullable=True)
    pnl_percentage = Column(Numeric(10, 6), nullable=True)
    
    # MFE/MAE - Critical for trade analysis
    max_favorable_excursion = Column(Numeric(10, 6), nullable=True)
    max_adverse_excursion = Column(Numeric(10, 6), nullable=True)
    
    # Signal context snapshot (for post-analysis)
    signal_snapshot = Column(JSON, nullable=True)
    
    # Greeks at entry (for options)
    greeks_at_entry = Column(JSON, nullable=True)
    
    # Holding period
    holding_minutes = Column(Integer, nullable=True)
    
    backtest_run = relationship("BacktestRun", back_populates="trades")


class DailyEquityCurve(Base):
    """
    Tracks portfolio value over time for calculating portfolio-level
    statistics and visualizing performance curves.
    """
    __tablename__ = "daily_equity_curve"
    __table_args__ = (
        UniqueConstraint("backtest_run_id", "date", name="uq_equity_curve_day"),
    )

    curve_point_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    backtest_run_id = Column(GUID(), ForeignKey("backtest_runs.run_id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    
    # Portfolio state
    portfolio_value = Column(Numeric(14, 2), nullable=False)
    cash_balance = Column(Numeric(14, 2), nullable=False)
    open_positions_value = Column(Numeric(14, 2), nullable=False, default=0)
    open_positions_count = Column(Integer, nullable=False, default=0)
    
    # Daily metrics
    daily_pnl = Column(Numeric(14, 2), nullable=False, default=0)
    daily_return_pct = Column(Numeric(10, 6), nullable=True)
    
    # Drawdown tracking
    peak_value = Column(Numeric(14, 2), nullable=False)
    drawdown_pct = Column(Numeric(10, 6), nullable=False, default=0)
    
    # Trade counts for the day
    trades_opened = Column(Integer, nullable=False, default=0)
    trades_closed = Column(Integer, nullable=False, default=0)
    
    backtest_run = relationship("BacktestRun", back_populates="equity_curve")


# =============================================================================
# Outlier Outcome Tracking (Phase 2: Feedback Loop)
# =============================================================================

class OutlierOutcomeLabel(str, Enum):
    """Classification of outlier trade outcomes"""
    WIN = "WIN"        # Return >= win_threshold (default 5%)
    LOSS = "LOSS"      # Return <= loss_threshold (default -5%)
    NEUTRAL = "NEUTRAL"  # Return between thresholds


class OutlierOutcome(Base):
    """
    Stores historical outcomes for outlier detection signals.
    Used for:
    - Tracking win rates by method/underlying/sector
    - Training ML models
    - Dynamic threshold adjustment
    """
    __tablename__ = "outlier_outcomes"
    __table_args__ = (
        UniqueConstraint("event_date", "underlying_symbol", "option_symbol", "method", name="uq_outlier_outcome"),
        Index("ix_outlier_outcomes_date", "event_date"),
        Index("ix_outlier_outcomes_underlying", "underlying_symbol"),
        Index("ix_outlier_outcomes_method", "method"),
        Index("ix_outlier_outcomes_label", "outcome_label"),
    )

    outcome_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    
    # Event identification
    event_date = Column(Date, nullable=False)
    underlying_symbol = Column(String(32), nullable=False)
    option_symbol = Column(String(64), nullable=True)
    method = Column(String(32), nullable=False)  # Z-Score, IQR, Pre-Event
    
    # Signal details at time of detection
    score = Column(Numeric(14, 6), nullable=False)
    flow_sentiment = Column(Numeric(10, 6), nullable=True)
    flow_adjusted_score = Column(Numeric(14, 6), nullable=True)
    oi_diff = Column(Numeric(14, 2), nullable=True)
    strike = Column(Numeric(12, 4), nullable=True)
    dte = Column(Integer, nullable=True)
    sector = Column(String(64), nullable=True)
    
    # Entry details
    entry_date = Column(Date, nullable=False)
    entry_price_underlying = Column(Numeric(12, 4), nullable=True)
    entry_price_option = Column(Numeric(12, 4), nullable=True)
    
    # Exit/outcome details
    exit_date = Column(Date, nullable=True)
    exit_price_underlying = Column(Numeric(12, 4), nullable=True)
    exit_price_option = Column(Numeric(12, 4), nullable=True)
    holding_days = Column(Integer, nullable=True)
    
    # Returns at various horizons
    return_1d = Column(Numeric(10, 6), nullable=True)
    return_5d = Column(Numeric(10, 6), nullable=True)
    return_20d = Column(Numeric(10, 6), nullable=True)
    
    # Outcome classification
    outcome_label = Column(PgEnum(OutlierOutcomeLabel, name="outlier_outcome_label"), nullable=True)
    win_threshold_used = Column(Numeric(6, 4), nullable=False, default=0.05)  # 5% default
    loss_threshold_used = Column(Numeric(6, 4), nullable=False, default=-0.05)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class OutlierMethodStats(Base):
    """
    Pre-computed success statistics by method, underlying, and sector.
    Updated periodically to avoid expensive real-time aggregations.
    """
    __tablename__ = "outlier_method_stats"
    __table_args__ = (
        UniqueConstraint("method", "underlying_symbol", "sector", "lookback_days", name="uq_method_stats"),
        Index("ix_method_stats_method", "method"),
        Index("ix_method_stats_underlying", "underlying_symbol"),
    )

    stats_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    
    # Grouping keys
    method = Column(String(32), nullable=False)
    underlying_symbol = Column(String(32), nullable=True)  # NULL = all underlyings
    sector = Column(String(64), nullable=True)  # NULL = all sectors
    lookback_days = Column(Integer, nullable=False, default=90)
    
    # Computed statistics
    total_signals = Column(Integer, nullable=False, default=0)
    win_count = Column(Integer, nullable=False, default=0)
    loss_count = Column(Integer, nullable=False, default=0)
    neutral_count = Column(Integer, nullable=False, default=0)
    
    win_rate = Column(Numeric(6, 4), nullable=True)  # win_count / total_signals
    avg_return = Column(Numeric(10, 6), nullable=True)
    median_return = Column(Numeric(10, 6), nullable=True)
    sharpe_ratio = Column(Numeric(10, 6), nullable=True)
    
    # Best/worst performance
    best_return = Column(Numeric(10, 6), nullable=True)
    worst_return = Column(Numeric(10, 6), nullable=True)
    
    # Dynamic threshold recommendations
    recommended_score_threshold = Column(Numeric(10, 4), nullable=True)
    
    # Metadata
    computed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    as_of_date = Column(Date, nullable=False)
