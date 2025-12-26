"""
Backtest Configuration
======================

Dataclass-based configuration for backtesting runs with validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional
from decimal import Decimal


@dataclass
class BacktestConfig:
    """
    Configuration for a backtest run.
    
    All monetary values use Decimal for precision.
    Percentages are expressed as decimals (0.05 = 5%).
    """
    
    # Required: Date range
    start_date: date
    end_date: date
    
    # Capital settings
    initial_capital: float = 100_000.0
    
    # Position sizing
    max_position_size_pct: float = 0.05  # Max 5% of portfolio per trade
    max_open_positions: int = 10
    min_position_size: int = 1  # Minimum contracts per trade
    
    # Strategy selection
    strategy_version: str = "v1_ensemble"
    
    # Entry filters
    min_confidence: float = 0.5  # Minimum ensemble confidence to enter
    allowed_regimes: List[str] = field(default_factory=lambda: ["TREND_RISK", "PIN_RANGE"])
    underlying_filter: Optional[List[str]] = None  # None = all underlyings
    
    # Exit rules
    profit_target_pct: float = 0.75  # Take profit at +75%
    stop_loss_pct: float = 0.40       # Stop loss at -40%
    max_hold_days: int = 1            # Maximum holding period (0DTE default)
    time_exit_minutes: Optional[int] = None  # Exit N minutes before close
    
    # Risk parameters
    risk_free_rate: float = 0.045  # 4.5% annual for Sharpe calculation
    
    # Slippage and costs (applied to each trade)
    slippage_pct: float = 0.01  # 1% slippage on options
    commission_per_contract: float = 0.65  # Per contract commission
    
    # Simulation settings
    use_intraday_prices: bool = False  # If True, use minute-level data
    skip_weekends: bool = True
    skip_holidays: bool = True
    
    def __post_init__(self):
        """Validate configuration after initialization."""
        if self.start_date >= self.end_date:
            raise ValueError("start_date must be before end_date")
        
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        
        if not 0 < self.max_position_size_pct <= 1:
            raise ValueError("max_position_size_pct must be between 0 and 1")
        
        if self.max_open_positions < 1:
            raise ValueError("max_open_positions must be at least 1")
        
        if not 0 <= self.min_confidence <= 1:
            raise ValueError("min_confidence must be between 0 and 1")
        
        if self.profit_target_pct <= 0:
            raise ValueError("profit_target_pct must be positive")
        
        if self.stop_loss_pct <= 0:
            raise ValueError("stop_loss_pct must be positive")
        
        if self.max_hold_days < 0:
            raise ValueError("max_hold_days cannot be negative")
    
    def to_dict(self) -> dict:
        """Convert config to dictionary for JSON storage."""
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "initial_capital": self.initial_capital,
            "max_position_size_pct": self.max_position_size_pct,
            "max_open_positions": self.max_open_positions,
            "min_position_size": self.min_position_size,
            "strategy_version": self.strategy_version,
            "min_confidence": self.min_confidence,
            "allowed_regimes": self.allowed_regimes,
            "underlying_filter": self.underlying_filter,
            "profit_target_pct": self.profit_target_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "max_hold_days": self.max_hold_days,
            "time_exit_minutes": self.time_exit_minutes,
            "risk_free_rate": self.risk_free_rate,
            "slippage_pct": self.slippage_pct,
            "commission_per_contract": self.commission_per_contract,
            "use_intraday_prices": self.use_intraday_prices,
        }
    
    @classmethod
    def from_dict(cls, d: dict) -> "BacktestConfig":
        """Create config from dictionary."""
        d = d.copy()
        if isinstance(d.get("start_date"), str):
            d["start_date"] = date.fromisoformat(d["start_date"])
        if isinstance(d.get("end_date"), str):
            d["end_date"] = date.fromisoformat(d["end_date"])
        return cls(**d)


@dataclass
class SimulatedPositionState:
    """
    Represents an open position during simulation.
    
    Tracks entry details and running MFE/MAE for trade analysis.
    """
    trade_id: str
    underlying_symbol: str
    option_symbol: Optional[str]
    
    entry_timestamp: date
    entry_price_stock: float
    entry_price_option: Optional[float]
    position_size: int
    capital_at_risk: float
    
    strategy_name: str
    entry_reason: str
    signal_snapshot: dict
    
    # Running MFE/MAE tracking
    max_favorable_price: Optional[float] = None
    max_adverse_price: Optional[float] = None
    
    def __post_init__(self):
        """Initialize MFE/MAE tracking."""
        if self.entry_price_option:
            if self.max_favorable_price is None:
                self.max_favorable_price = self.entry_price_option
            if self.max_adverse_price is None:
                self.max_adverse_price = self.entry_price_option
    
    def update_mfe_mae(self, current_price: float) -> None:
        """Update MFE/MAE with current price."""
        if current_price is None:
            return
        if self.max_favorable_price is None or current_price > self.max_favorable_price:
            self.max_favorable_price = current_price
        if self.max_adverse_price is None or current_price < self.max_adverse_price:
            self.max_adverse_price = current_price
    
    @property
    def mfe_pct(self) -> Optional[float]:
        """Calculate MFE as percentage from entry."""
        if self.entry_price_option and self.max_favorable_price:
            return (self.max_favorable_price - self.entry_price_option) / self.entry_price_option
        return None
    
    @property
    def mae_pct(self) -> Optional[float]:
        """Calculate MAE as percentage from entry (negative value)."""
        if self.entry_price_option and self.max_adverse_price:
            return (self.max_adverse_price - self.entry_price_option) / self.entry_price_option
        return None
