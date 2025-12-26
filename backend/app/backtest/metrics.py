"""
Performance Metrics Calculator
==============================

Calculates comprehensive KPIs for backtest results including:
- Tier 1: Core metrics (Win Rate, Profit Factor, etc.)
- Tier 2: Risk metrics (Sharpe, Sortino, Max Drawdown, etc.)
- Tier 3: Options-specific metrics (by regime, by strategy, etc.)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict

import numpy as np


@dataclass
class PerformanceMetrics:
    """Complete performance metrics for a backtest run."""
    
    # Tier 1: Core Performance
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    breakeven_trades: int = 0
    
    win_rate: float = 0.0
    total_pnl: float = 0.0
    total_return_pct: float = 0.0
    
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float = 0.0
    
    avg_win: float = 0.0
    avg_loss: float = 0.0
    avg_win_loss_ratio: float = 0.0
    avg_pnl_per_trade: float = 0.0
    
    # Tier 2: Risk Metrics
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    
    max_drawdown_pct: float = 0.0
    max_drawdown_duration_days: int = 0
    avg_drawdown_pct: float = 0.0
    
    volatility_annual: float = 0.0
    downside_volatility: float = 0.0
    
    avg_holding_minutes: float = 0.0
    time_in_market_pct: float = 0.0
    
    # Tier 3: Advanced/Options Metrics
    trade_efficiency: float = 0.0  # Avg(actual_pnl / MFE)
    risk_efficiency: float = 0.0   # Avg(actual_pnl / |MAE|)
    
    best_trade_pnl: float = 0.0
    worst_trade_pnl: float = 0.0
    
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    
    # Breakdowns
    pnl_by_strategy: Dict[str, float] = None
    win_rate_by_regime: Dict[str, float] = None
    pnl_by_underlying: Dict[str, float] = None
    trades_by_exit_reason: Dict[str, int] = None
    
    def __post_init__(self):
        if self.pnl_by_strategy is None:
            self.pnl_by_strategy = {}
        if self.win_rate_by_regime is None:
            self.win_rate_by_regime = {}
        if self.pnl_by_underlying is None:
            self.pnl_by_underlying = {}
        if self.trades_by_exit_reason is None:
            self.trades_by_exit_reason = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON storage."""
        return {
            # Tier 1
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": round(self.win_rate, 4),
            "total_pnl": round(self.total_pnl, 2),
            "total_return_pct": round(self.total_return_pct, 4),
            "gross_profit": round(self.gross_profit, 2),
            "gross_loss": round(self.gross_loss, 2),
            "profit_factor": round(self.profit_factor, 2),
            "avg_win": round(self.avg_win, 2),
            "avg_loss": round(self.avg_loss, 2),
            "avg_win_loss_ratio": round(self.avg_win_loss_ratio, 2),
            "avg_pnl_per_trade": round(self.avg_pnl_per_trade, 2),
            # Tier 2
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "sortino_ratio": round(self.sortino_ratio, 2),
            "calmar_ratio": round(self.calmar_ratio, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "max_drawdown_duration_days": self.max_drawdown_duration_days,
            "avg_drawdown_pct": round(self.avg_drawdown_pct, 4),
            "volatility_annual": round(self.volatility_annual, 4),
            "avg_holding_minutes": round(self.avg_holding_minutes, 1),
            "time_in_market_pct": round(self.time_in_market_pct, 4),
            # Tier 3
            "trade_efficiency": round(self.trade_efficiency, 4),
            "risk_efficiency": round(self.risk_efficiency, 4),
            "best_trade_pnl": round(self.best_trade_pnl, 2),
            "worst_trade_pnl": round(self.worst_trade_pnl, 2),
            "max_consecutive_wins": self.max_consecutive_wins,
            "max_consecutive_losses": self.max_consecutive_losses,
            # Breakdowns
            "pnl_by_strategy": self.pnl_by_strategy,
            "win_rate_by_regime": self.win_rate_by_regime,
            "pnl_by_underlying": self.pnl_by_underlying,
            "trades_by_exit_reason": self.trades_by_exit_reason,
        }


class PerformanceCalculator:
    """
    Calculates comprehensive performance metrics from backtest results.
    
    Usage:
        calc = PerformanceCalculator(
            trades=closed_trades,
            equity_curve=equity_points,
            initial_capital=100000.0,
            risk_free_rate=0.045,
        )
        metrics = calc.calculate()
    """
    
    def __init__(
        self,
        trades: List[Dict[str, Any]],
        equity_curve: List[Dict[str, Any]],
        initial_capital: float,
        risk_free_rate: float = 0.045,
    ):
        self.trades = trades
        self.equity_curve = equity_curve
        self.initial_capital = initial_capital
        self.risk_free_rate = risk_free_rate
    
    def calculate(self) -> PerformanceMetrics:
        """Calculate all performance metrics."""
        metrics = PerformanceMetrics()
        
        if not self.trades:
            return metrics
        
        # Tier 1: Core metrics
        self._calculate_core_metrics(metrics)
        
        # Tier 2: Risk metrics
        if self.equity_curve:
            self._calculate_risk_metrics(metrics)
        
        # Tier 3: Advanced metrics
        self._calculate_advanced_metrics(metrics)
        
        return metrics
    
    def _calculate_core_metrics(self, metrics: PerformanceMetrics) -> None:
        """Calculate Tier 1 core performance metrics."""
        pnls = [t.get("pnl_absolute", 0) or 0 for t in self.trades]
        
        metrics.total_trades = len(self.trades)
        metrics.winning_trades = sum(1 for p in pnls if p > 0)
        metrics.losing_trades = sum(1 for p in pnls if p < 0)
        metrics.breakeven_trades = sum(1 for p in pnls if p == 0)
        
        metrics.win_rate = metrics.winning_trades / metrics.total_trades if metrics.total_trades > 0 else 0
        
        metrics.total_pnl = sum(pnls)
        
        # Calculate return based on ending equity
        if self.equity_curve:
            ending_value = self.equity_curve[-1].get("portfolio_value", self.initial_capital)
            metrics.total_return_pct = (ending_value - self.initial_capital) / self.initial_capital
        else:
            metrics.total_return_pct = metrics.total_pnl / self.initial_capital
        
        # Gross profit/loss
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        
        metrics.gross_profit = sum(wins)
        metrics.gross_loss = abs(sum(losses))
        
        metrics.profit_factor = (
            metrics.gross_profit / metrics.gross_loss 
            if metrics.gross_loss > 0 else float('inf')
        )
        
        # Averages
        metrics.avg_win = metrics.gross_profit / len(wins) if wins else 0
        metrics.avg_loss = metrics.gross_loss / len(losses) if losses else 0
        metrics.avg_win_loss_ratio = (
            metrics.avg_win / metrics.avg_loss 
            if metrics.avg_loss > 0 else float('inf')
        )
        metrics.avg_pnl_per_trade = metrics.total_pnl / metrics.total_trades
    
    def _calculate_risk_metrics(self, metrics: PerformanceMetrics) -> None:
        """Calculate Tier 2 risk-adjusted metrics."""
        if len(self.equity_curve) < 2:
            return
        
        # Calculate daily returns
        values = [e.get("portfolio_value", 0) for e in self.equity_curve]
        daily_returns = []
        for i in range(1, len(values)):
            if values[i-1] > 0:
                daily_returns.append((values[i] - values[i-1]) / values[i-1])
        
        if not daily_returns:
            return
        
        daily_returns = np.array(daily_returns)
        
        # Volatility (annualized)
        std_daily = np.std(daily_returns)
        metrics.volatility_annual = std_daily * np.sqrt(252)
        
        # Sharpe Ratio
        avg_daily_return = np.mean(daily_returns)
        risk_free_daily = self.risk_free_rate / 252
        
        if std_daily > 0:
            metrics.sharpe_ratio = (avg_daily_return - risk_free_daily) / std_daily * np.sqrt(252)
        
        # Sortino Ratio (only downside volatility)
        negative_returns = daily_returns[daily_returns < 0]
        if len(negative_returns) > 0:
            downside_std = np.std(negative_returns)
            metrics.downside_volatility = downside_std * np.sqrt(252)
            if downside_std > 0:
                metrics.sortino_ratio = (avg_daily_return - risk_free_daily) / downside_std * np.sqrt(252)
        
        # Maximum Drawdown
        peak = values[0]
        max_dd = 0
        max_dd_duration = 0
        current_dd_start = 0
        
        drawdowns = []
        
        for i, val in enumerate(values):
            if val > peak:
                peak = val
                if max_dd_duration > 0:
                    max_dd_duration = max(max_dd_duration, i - current_dd_start)
                current_dd_start = i
            
            dd = (peak - val) / peak if peak > 0 else 0
            drawdowns.append(dd)
            
            if dd > max_dd:
                max_dd = dd
        
        metrics.max_drawdown_pct = max_dd
        metrics.max_drawdown_duration_days = max_dd_duration
        metrics.avg_drawdown_pct = np.mean(drawdowns) if drawdowns else 0
        
        # Calmar Ratio
        annualized_return = metrics.total_return_pct * (252 / len(self.equity_curve))
        if max_dd > 0:
            metrics.calmar_ratio = annualized_return / max_dd
        
        # Time in market
        days_with_positions = sum(
            1 for e in self.equity_curve 
            if e.get("open_positions_count", 0) > 0
        )
        metrics.time_in_market_pct = days_with_positions / len(self.equity_curve)
    
    def _calculate_advanced_metrics(self, metrics: PerformanceMetrics) -> None:
        """Calculate Tier 3 advanced and options-specific metrics."""
        pnls = [t.get("pnl_absolute", 0) or 0 for t in self.trades]
        
        # Best/worst trades
        if pnls:
            metrics.best_trade_pnl = max(pnls)
            metrics.worst_trade_pnl = min(pnls)
        
        # Consecutive wins/losses
        max_wins = max_losses = current_wins = current_losses = 0
        for pnl in pnls:
            if pnl > 0:
                current_wins += 1
                current_losses = 0
                max_wins = max(max_wins, current_wins)
            elif pnl < 0:
                current_losses += 1
                current_wins = 0
                max_losses = max(max_losses, current_losses)
            else:
                current_wins = current_losses = 0
        
        metrics.max_consecutive_wins = max_wins
        metrics.max_consecutive_losses = max_losses
        
        # Average holding time
        holding_times = [
            t.get("holding_minutes", 0) or 0 
            for t in self.trades 
            if t.get("holding_minutes")
        ]
        metrics.avg_holding_minutes = np.mean(holding_times) if holding_times else 0
        
        # Trade efficiency (actual P&L vs MFE)
        efficiencies = []
        risk_efficiencies = []
        
        for t in self.trades:
            pnl_pct = t.get("pnl_percentage", 0) or 0
            mfe = t.get("max_favorable_excursion", 0) or 0
            mae = t.get("max_adverse_excursion", 0) or 0
            
            if mfe > 0:
                efficiencies.append(pnl_pct / mfe)
            if mae < 0:
                risk_efficiencies.append(pnl_pct / abs(mae))
        
        metrics.trade_efficiency = np.mean(efficiencies) if efficiencies else 0
        metrics.risk_efficiency = np.mean(risk_efficiencies) if risk_efficiencies else 0
        
        # Breakdown by strategy
        strategy_pnl = defaultdict(float)
        for t in self.trades:
            strategy = t.get("strategy_name", "unknown")
            strategy_pnl[strategy] += t.get("pnl_absolute", 0) or 0
        metrics.pnl_by_strategy = dict(strategy_pnl)
        
        # Breakdown by underlying
        underlying_pnl = defaultdict(float)
        for t in self.trades:
            underlying = t.get("underlying_symbol", "unknown")
            underlying_pnl[underlying] += t.get("pnl_absolute", 0) or 0
        metrics.pnl_by_underlying = dict(underlying_pnl)
        
        # Breakdown by exit reason
        exit_counts = defaultdict(int)
        for t in self.trades:
            reason = t.get("exit_reason", "unknown")
            if reason:
                exit_counts[str(reason)] += 1
        metrics.trades_by_exit_reason = dict(exit_counts)
        
        # Win rate by regime (from signal snapshot)
        regime_trades = defaultdict(list)
        for t in self.trades:
            snapshot = t.get("signal_snapshot", {}) or {}
            regime = snapshot.get("regime_label", "unknown")
            pnl = t.get("pnl_absolute", 0) or 0
            regime_trades[regime].append(pnl > 0)
        
        metrics.win_rate_by_regime = {
            regime: np.mean(wins) if wins else 0
            for regime, wins in regime_trades.items()
        }
