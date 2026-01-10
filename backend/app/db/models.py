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
    correlation_runs = relationship("CorrelationRun", back_populates="session", cascade="all, delete-orphan")


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


class CorrelationRun(Base):
    """Persisted factor↔future-return correlation snapshots.

    This is a lightweight, JSON-first artifact meant to support dashboards and
    exploration without re-running compute.
    """

    __tablename__ = "correlation_runs"
    __table_args__ = (
        UniqueConstraint("session_id", "asof_date", "version", name="uq_correlation_run"),
        Index("ix_correlation_runs_session", "session_id"),
        Index("ix_correlation_runs_date", "asof_date"),
    )

    run_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    session_id = Column(GUID(), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False)
    asof_date = Column(Date, nullable=False)
    version = Column(String(16), nullable=False, default="v1")
    computed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    params = Column(JSON, nullable=True)
    results = Column(JSON, nullable=True)

    session = relationship("Session", back_populates="correlation_runs")


# =============================================================================
# Options Signals (Options flow, features, and alerts)
# =============================================================================


class OptTradeRaw(Base):
    __tablename__ = "opt_trades_raw"
    __table_args__ = (
        Index("ix_opt_trades_raw_date_underlying", "trade_date", "underlying_symbol"),
        Index("ix_opt_trades_raw_chain", "option_chain_id"),
    )

    trade_id = Column(String(64), primary_key=True)
    executed_at_utc = Column(DateTime, nullable=False)
    executed_at_market = Column(DateTime, nullable=False)
    trade_date = Column(Date, nullable=False)

    underlying_symbol = Column(String(32), nullable=False)
    option_chain_id = Column(String(64), nullable=False)
    side = Column(String(16), nullable=True)
    strike = Column(Numeric(12, 4), nullable=True)
    option_type = Column(String(8), nullable=True)
    expiry_date = Column(Date, nullable=True)
    underlying_price = Column(Numeric(12, 4), nullable=True)

    nbbo_bid = Column(Numeric(12, 4), nullable=True)
    nbbo_ask = Column(Numeric(12, 4), nullable=True)
    ewma_nbbo_bid = Column(Numeric(12, 4), nullable=True)
    ewma_nbbo_ask = Column(Numeric(12, 4), nullable=True)
    price = Column(Numeric(12, 4), nullable=True)
    size = Column(Integer, nullable=True)
    premium = Column(Numeric(14, 2), nullable=True)
    volume = Column(Integer, nullable=True)
    open_interest = Column(Integer, nullable=True)

    implied_volatility = Column(Numeric(10, 6), nullable=True)
    delta = Column(Numeric(12, 6), nullable=True)
    theta = Column(Numeric(12, 6), nullable=True)
    gamma = Column(Numeric(12, 6), nullable=True)
    vega = Column(Numeric(12, 6), nullable=True)
    rho = Column(Numeric(12, 6), nullable=True)
    theo = Column(Numeric(12, 6), nullable=True)

    sector = Column(String(64), nullable=True)
    exchange = Column(String(32), nullable=True)
    report_flags = Column(String(64), nullable=True)
    canceled = Column(Boolean, nullable=True)
    upstream_condition_detail = Column(Text, nullable=True)
    equity_type = Column(String(32), nullable=True)

    trade_direction = Column(String(24), nullable=True)
    nbbo_valid = Column(Boolean, nullable=False, default=False)
    excluded_reason = Column(String(64), nullable=True)
    is_excluded = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class EqOhlcvDaily(Base):
    __tablename__ = "eq_ohlcv_daily"
    __table_args__ = (
        UniqueConstraint("trade_date", "underlying_symbol", name="uq_eq_ohlcv_daily"),
        Index("ix_eq_ohlcv_daily_symbol", "underlying_symbol"),
    )

    ohlcv_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    trade_date = Column(Date, nullable=False)
    underlying_symbol = Column(String(32), nullable=False)
    open = Column(Numeric(12, 4), nullable=True)
    high = Column(Numeric(12, 4), nullable=True)
    low = Column(Numeric(12, 4), nullable=True)
    close = Column(Numeric(12, 4), nullable=True)
    adj_close = Column(Numeric(12, 4), nullable=True)
    volume = Column(Integer, nullable=True)


class MktContextDaily(Base):
    __tablename__ = "mkt_context_daily"
    __table_args__ = (UniqueConstraint("trade_date", name="uq_mkt_context_daily"),)

    context_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    trade_date = Column(Date, nullable=False)
    spx_close = Column(Numeric(12, 4), nullable=True)
    spx_return_1d = Column(Numeric(12, 6), nullable=True)
    spx_return_5d = Column(Numeric(12, 6), nullable=True)
    vix_close = Column(Numeric(12, 4), nullable=True)
    vix_change_1d = Column(Numeric(12, 6), nullable=True)
    vix_change_5d = Column(Numeric(12, 6), nullable=True)
    t10y_yield = Column(Numeric(12, 6), nullable=True)
    t10y_change_1d = Column(Numeric(12, 6), nullable=True)
    t10y_change_5d = Column(Numeric(12, 6), nullable=True)
    credit_spread = Column(Numeric(12, 6), nullable=True)
    wti_close = Column(Numeric(12, 4), nullable=True)
    wti_ret_1d = Column(Numeric(12, 6), nullable=True)


class SectorContextDaily(Base):
    __tablename__ = "sector_context_daily"
    __table_args__ = (
        UniqueConstraint("trade_date", "sector_or_etf", name="uq_sector_context_daily"),
        Index("ix_sector_context_sector", "sector_or_etf"),
    )

    context_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    trade_date = Column(Date, nullable=False)
    sector_or_etf = Column(String(64), nullable=False)
    close = Column(Numeric(12, 4), nullable=True)
    return_1d = Column(Numeric(12, 6), nullable=True)
    return_5d = Column(Numeric(12, 6), nullable=True)
    realized_vol_20d = Column(Numeric(12, 6), nullable=True)


class NewsSentimentDaily(Base):
    __tablename__ = "news_sentiment_daily"
    __table_args__ = (
        UniqueConstraint("trade_date", "underlying_symbol", name="uq_news_sentiment_daily"),
        Index("ix_news_sentiment_symbol", "underlying_symbol"),
    )

    news_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    trade_date = Column(Date, nullable=False)
    underlying_symbol = Column(String(32), nullable=False)
    article_count_24h = Column(Integer, nullable=True)
    sentiment_mean = Column(Numeric(10, 6), nullable=True)
    sentiment_std = Column(Numeric(10, 6), nullable=True)
    sentiment_abs_mean = Column(Numeric(10, 6), nullable=True)
    source_count = Column(Integer, nullable=True)
    news_missing = Column(Boolean, nullable=False, default=False)


class OptAggUnderlyingDaily(Base):
    __tablename__ = "opt_agg_underlying_daily"
    __table_args__ = (
        UniqueConstraint("trade_date", "underlying_symbol", name="uq_opt_agg_underlying_daily"),
        Index("ix_opt_agg_underlying_symbol", "underlying_symbol"),
    )

    agg_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    trade_date = Column(Date, nullable=False)
    underlying_symbol = Column(String(32), nullable=False)
    sector = Column(String(64), nullable=True)

    call_volume = Column(Numeric(14, 2), nullable=True)
    put_volume = Column(Numeric(14, 2), nullable=True)
    call_premium = Column(Numeric(16, 2), nullable=True)
    put_premium = Column(Numeric(16, 2), nullable=True)
    call_trade_count = Column(Integer, nullable=True)
    put_trade_count = Column(Integer, nullable=True)
    avg_iv_call = Column(Numeric(10, 6), nullable=True)
    avg_iv_put = Column(Numeric(10, 6), nullable=True)
    avg_iv_all = Column(Numeric(10, 6), nullable=True)
    oi_call_eod = Column(Numeric(14, 2), nullable=True)
    oi_put_eod = Column(Numeric(14, 2), nullable=True)
    oi_change_call = Column(Numeric(14, 2), nullable=True)
    oi_change_put = Column(Numeric(14, 2), nullable=True)
    pct_trades_missing_nbbo = Column(Numeric(8, 4), nullable=True)

    put_call_vol_ratio = Column(Numeric(12, 6), nullable=True)
    put_call_prem_ratio = Column(Numeric(12, 6), nullable=True)
    call_buy_premium = Column(Numeric(16, 2), nullable=True)
    call_sell_premium = Column(Numeric(16, 2), nullable=True)
    put_buy_premium = Column(Numeric(16, 2), nullable=True)
    put_sell_premium = Column(Numeric(16, 2), nullable=True)
    net_call_premium = Column(Numeric(16, 2), nullable=True)
    net_put_premium = Column(Numeric(16, 2), nullable=True)
    net_premium = Column(Numeric(16, 2), nullable=True)
    net_delta = Column(Numeric(16, 4), nullable=True)
    net_gamma = Column(Numeric(16, 4), nullable=True)
    net_vega = Column(Numeric(16, 4), nullable=True)

    net_premium_atm_calls = Column(Numeric(16, 2), nullable=True)
    net_premium_atm_puts = Column(Numeric(16, 2), nullable=True)
    net_premium_otm_calls = Column(Numeric(16, 2), nullable=True)
    net_premium_otm_puts = Column(Numeric(16, 2), nullable=True)
    net_premium_deep_otm_calls = Column(Numeric(16, 2), nullable=True)
    net_premium_deep_otm_puts = Column(Numeric(16, 2), nullable=True)


class OptAggContractDaily(Base):
    __tablename__ = "opt_agg_contract_daily"
    __table_args__ = (
        UniqueConstraint("trade_date", "option_chain_id", name="uq_opt_agg_contract_daily"),
        Index("ix_opt_agg_contract_chain", "option_chain_id"),
    )

    agg_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    trade_date = Column(Date, nullable=False)
    option_chain_id = Column(String(64), nullable=False)
    underlying_symbol = Column(String(32), nullable=False)
    expiry_date = Column(Date, nullable=True)
    option_type = Column(String(8), nullable=True)
    strike = Column(Numeric(12, 4), nullable=True)

    contract_volume = Column(Numeric(14, 2), nullable=True)
    contract_premium = Column(Numeric(16, 2), nullable=True)
    contract_trade_count = Column(Integer, nullable=True)
    iv_last = Column(Numeric(10, 6), nullable=True)
    iv_vwap = Column(Numeric(10, 6), nullable=True)
    delta_last = Column(Numeric(12, 6), nullable=True)
    gamma_last = Column(Numeric(12, 6), nullable=True)
    vega_last = Column(Numeric(12, 6), nullable=True)
    oi_eod = Column(Numeric(14, 2), nullable=True)

    uoa_volume_z = Column(Numeric(12, 6), nullable=True)
    uoa_premium_z = Column(Numeric(12, 6), nullable=True)
    uoa_vo_i = Column(Numeric(12, 6), nullable=True)
    is_uoa = Column(Boolean, nullable=False, default=False)


class FeaturesUnderlyingDaily(Base):
    __tablename__ = "features_underlying_daily"
    __table_args__ = (
        UniqueConstraint("trade_date", "underlying_symbol", name="uq_features_underlying_daily"),
        Index("ix_features_underlying_symbol", "underlying_symbol"),
    )

    feature_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    trade_date = Column(Date, nullable=False)
    underlying_symbol = Column(String(32), nullable=False)
    sector = Column(String(64), nullable=True)
    computed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Flow metrics
    call_volume = Column(Numeric(14, 2), nullable=True)
    put_volume = Column(Numeric(14, 2), nullable=True)
    call_premium = Column(Numeric(16, 2), nullable=True)
    put_premium = Column(Numeric(16, 2), nullable=True)
    put_call_vol_ratio = Column(Numeric(12, 6), nullable=True)
    put_call_prem_ratio = Column(Numeric(12, 6), nullable=True)
    call_buy_premium = Column(Numeric(16, 2), nullable=True)
    call_sell_premium = Column(Numeric(16, 2), nullable=True)
    put_buy_premium = Column(Numeric(16, 2), nullable=True)
    put_sell_premium = Column(Numeric(16, 2), nullable=True)
    net_call_premium = Column(Numeric(16, 2), nullable=True)
    net_put_premium = Column(Numeric(16, 2), nullable=True)
    net_premium = Column(Numeric(16, 2), nullable=True)
    net_delta = Column(Numeric(16, 4), nullable=True)
    net_gamma = Column(Numeric(16, 4), nullable=True)
    net_vega = Column(Numeric(16, 4), nullable=True)
    iv_vwap_all = Column(Numeric(10, 6), nullable=True)
    iv_vwap_call = Column(Numeric(10, 6), nullable=True)
    iv_vwap_put = Column(Numeric(10, 6), nullable=True)

    net_premium_atm_calls = Column(Numeric(16, 2), nullable=True)
    net_premium_atm_puts = Column(Numeric(16, 2), nullable=True)
    net_premium_otm_calls = Column(Numeric(16, 2), nullable=True)
    net_premium_otm_puts = Column(Numeric(16, 2), nullable=True)
    net_premium_deep_otm_calls = Column(Numeric(16, 2), nullable=True)
    net_premium_deep_otm_puts = Column(Numeric(16, 2), nullable=True)

    uoa_contract_count = Column(Integer, nullable=True)
    uoa_max_volume_z = Column(Numeric(12, 6), nullable=True)
    uoa_max_vo_i = Column(Numeric(12, 6), nullable=True)
    uoa_total_premium = Column(Numeric(16, 2), nullable=True)

    iv_25d_call = Column(Numeric(10, 6), nullable=True)
    iv_25d_put = Column(Numeric(10, 6), nullable=True)
    skew_25d = Column(Numeric(10, 6), nullable=True)
    iv_front = Column(Numeric(10, 6), nullable=True)
    iv_back = Column(Numeric(10, 6), nullable=True)
    term_structure = Column(Numeric(10, 6), nullable=True)

    # Technicals
    close = Column(Numeric(12, 4), nullable=True)
    ret_1d = Column(Numeric(12, 6), nullable=True)
    ret_5d = Column(Numeric(12, 6), nullable=True)
    ret_10d = Column(Numeric(12, 6), nullable=True)
    ret_20d = Column(Numeric(12, 6), nullable=True)
    sma_20 = Column(Numeric(12, 6), nullable=True)
    sma_50 = Column(Numeric(12, 6), nullable=True)
    ema_12 = Column(Numeric(12, 6), nullable=True)
    ema_26 = Column(Numeric(12, 6), nullable=True)
    rsi_14 = Column(Numeric(12, 6), nullable=True)
    macd = Column(Numeric(12, 6), nullable=True)
    macd_signal = Column(Numeric(12, 6), nullable=True)
    macd_hist = Column(Numeric(12, 6), nullable=True)
    bb_mid = Column(Numeric(12, 6), nullable=True)
    bb_std = Column(Numeric(12, 6), nullable=True)
    bb_upper = Column(Numeric(12, 6), nullable=True)
    bb_lower = Column(Numeric(12, 6), nullable=True)
    bb_width = Column(Numeric(12, 6), nullable=True)
    bb_pct = Column(Numeric(12, 6), nullable=True)
    rv_10 = Column(Numeric(12, 6), nullable=True)
    rv_20 = Column(Numeric(12, 6), nullable=True)
    is_new_20d_high = Column(Boolean, nullable=True)
    is_new_20d_low = Column(Boolean, nullable=True)

    # Volatility and IV regime
    iv_atm_proxy = Column(Numeric(10, 6), nullable=True)
    iv_minus_rv20 = Column(Numeric(12, 6), nullable=True)
    iv_to_rv20_ratio = Column(Numeric(12, 6), nullable=True)
    iv_rank_252 = Column(Numeric(12, 6), nullable=True)
    rv20_z = Column(Numeric(12, 6), nullable=True)
    iv_atm_proxy_change_1d = Column(Numeric(12, 6), nullable=True)
    iv_atm_proxy_change_5d = Column(Numeric(12, 6), nullable=True)
    rv_10_change_5d = Column(Numeric(12, 6), nullable=True)

    # News + macro
    news_count = Column(Integer, nullable=True)
    sentiment_mean = Column(Numeric(10, 6), nullable=True)
    sentiment_abs = Column(Numeric(10, 6), nullable=True)
    sentiment_change_1d = Column(Numeric(10, 6), nullable=True)
    news_count_z_60 = Column(Numeric(12, 6), nullable=True)
    news_missing = Column(Boolean, nullable=True)

    spx_ret_1d = Column(Numeric(12, 6), nullable=True)
    spx_ret_5d = Column(Numeric(12, 6), nullable=True)
    vix_level = Column(Numeric(12, 6), nullable=True)
    vix_change_1d = Column(Numeric(12, 6), nullable=True)
    vix_change_5d = Column(Numeric(12, 6), nullable=True)
    t10y_change_1d = Column(Numeric(12, 6), nullable=True)
    t10y_change_5d = Column(Numeric(12, 6), nullable=True)
    wti_ret_1d = Column(Numeric(12, 6), nullable=True)
    sector_ret_1d = Column(Numeric(12, 6), nullable=True)
    sector_ret_5d = Column(Numeric(12, 6), nullable=True)
    sector_rv_20 = Column(Numeric(12, 6), nullable=True)

    pct_trades_missing_nbbo = Column(Numeric(8, 4), nullable=True)


class SignalsUnderlyingDaily(Base):
    __tablename__ = "signals_underlying_daily"
    __table_args__ = (
        UniqueConstraint("trade_date", "underlying_symbol", "signal_name", name="uq_signals_underlying_daily"),
        Index("ix_signals_underlying_date_signal", "trade_date", "signal_name"),
        Index("ix_signals_underlying_score", "signal_name", "score"),
    )

    signal_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    trade_date = Column(Date, nullable=False)
    underlying_symbol = Column(String(32), nullable=False)
    signal_name = Column(String(32), nullable=False)
    score = Column(Numeric(14, 6), nullable=False)
    rank = Column(Integer, nullable=True)
    explanation_json = Column(JSON, nullable=True)
    thresholds_triggered = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AlertsEventLog(Base):
    __tablename__ = "alerts_event_log"
    __table_args__ = (
        Index("ix_alerts_event_date", "trade_date"),
        Index("ix_alerts_event_symbol", "underlying_symbol"),
    )

    event_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    event_ts = Column(DateTime, nullable=False, default=datetime.utcnow)
    trade_date = Column(Date, nullable=False)
    underlying_symbol = Column(String(32), nullable=False)
    event_type = Column(String(64), nullable=False)
    severity = Column(String(16), nullable=True)
    payload_json = Column(JSON, nullable=True)


class OptionsSignalsDataQualityDaily(Base):
    __tablename__ = "options_signals_data_quality_daily"
    __table_args__ = (UniqueConstraint("trade_date", name="uq_options_signals_quality_daily"),)

    quality_id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    trade_date = Column(Date, nullable=False)
    total_trades = Column(Integer, nullable=True)
    canceled_filtered = Column(Integer, nullable=True)
    trades_missing_nbbo = Column(Integer, nullable=True)
    symbols_missing_ohlcv = Column(Integer, nullable=True)
    symbols_missing_news = Column(Integer, nullable=True)
    freshness_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
