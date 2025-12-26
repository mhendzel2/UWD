"""
Backtesting Engine for UWD System
=================================

This module provides a production-ready backtesting engine for options trading
strategies, designed to integrate with the UWD signal generation system.

Key Features:
- Strict lookahead bias prevention
- MFE/MAE tracking for trade analysis
- Comprehensive KPI calculation (Sharpe, Sortino, Calmar, etc.)
- Signal snapshot preservation for post-analysis
- Regime-based performance breakdown
"""

from .config import BacktestConfig
from .engine import OptionsBacktester
from .metrics import PerformanceCalculator

__all__ = ["BacktestConfig", "OptionsBacktester", "PerformanceCalculator"]
