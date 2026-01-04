"""Success rate calculation and dynamic threshold adjustment.

This module provides functions to:
1. Query historical success rates by method/underlying/sector
2. Compute dynamic thresholds based on historical performance
3. Provide real-time feedback for outlier scoring
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.db import models


@dataclass
class MethodPerformance:
    """Performance metrics for an outlier detection method."""
    method: str
    underlying_symbol: Optional[str]
    sector: Optional[str]
    total_signals: int
    win_count: int
    loss_count: int
    neutral_count: int
    win_rate: Optional[float]
    avg_return: Optional[float]
    median_return: Optional[float]
    sharpe_ratio: Optional[float]
    recommended_threshold: Optional[float]
    lookback_days: int
    
    @property
    def confidence_level(self) -> str:
        """Return confidence level based on sample size."""
        if self.total_signals < 10:
            return "LOW"
        if self.total_signals < 30:
            return "MEDIUM"
        return "HIGH"
    
    @property
    def is_profitable(self) -> bool:
        """Return True if method has positive expected value."""
        if self.avg_return is None:
            return False
        return self.avg_return > 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "method": self.method,
            "underlying_symbol": self.underlying_symbol,
            "sector": self.sector,
            "total_signals": self.total_signals,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "neutral_count": self.neutral_count,
            "win_rate": self.win_rate,
            "avg_return": self.avg_return,
            "median_return": self.median_return,
            "sharpe_ratio": self.sharpe_ratio,
            "recommended_threshold": self.recommended_threshold,
            "lookback_days": self.lookback_days,
            "confidence_level": self.confidence_level,
            "is_profitable": self.is_profitable,
        }


def get_method_performance(
    db: Session,
    method: str,
    underlying_symbol: Optional[str] = None,
    sector: Optional[str] = None,
    lookback_days: int = 90,
) -> Optional[MethodPerformance]:
    """Get cached performance stats for a method/underlying/sector combination.
    
    Args:
        db: SQLAlchemy session
        method: Detection method (Z-Score, IQR, Pre-Event)
        underlying_symbol: Optional underlying filter
        sector: Optional sector filter
        lookback_days: Lookback window for stats
        
    Returns:
        MethodPerformance object or None if no stats available
    """
    stats = (
        db.query(models.OutlierMethodStats)
        .filter(
            models.OutlierMethodStats.method == method,
            models.OutlierMethodStats.underlying_symbol == underlying_symbol,
            models.OutlierMethodStats.sector == sector,
            models.OutlierMethodStats.lookback_days == lookback_days,
        )
        .first()
    )
    
    if not stats:
        return None
    
    return MethodPerformance(
        method=stats.method,
        underlying_symbol=stats.underlying_symbol,
        sector=stats.sector,
        total_signals=stats.total_signals,
        win_count=stats.win_count,
        loss_count=stats.loss_count,
        neutral_count=stats.neutral_count,
        win_rate=float(stats.win_rate) if stats.win_rate else None,
        avg_return=float(stats.avg_return) if stats.avg_return else None,
        median_return=float(stats.median_return) if stats.median_return else None,
        sharpe_ratio=float(stats.sharpe_ratio) if stats.sharpe_ratio else None,
        recommended_threshold=float(stats.recommended_score_threshold) if stats.recommended_score_threshold else None,
        lookback_days=stats.lookback_days,
    )


def get_all_method_performances(
    db: Session,
    lookback_days: int = 90,
    method_filter: Optional[str] = None,
) -> list[MethodPerformance]:
    """Get all cached performance stats.
    
    Args:
        db: SQLAlchemy session
        lookback_days: Lookback window for stats
        method_filter: Optional method name filter
        
    Returns:
        List of MethodPerformance objects
    """
    q = (
        db.query(models.OutlierMethodStats)
        .filter(models.OutlierMethodStats.lookback_days == lookback_days)
    )
    
    if method_filter:
        q = q.filter(models.OutlierMethodStats.method == method_filter)
    
    results = []
    for stats in q.all():
        results.append(MethodPerformance(
            method=stats.method,
            underlying_symbol=stats.underlying_symbol,
            sector=stats.sector,
            total_signals=stats.total_signals,
            win_count=stats.win_count,
            loss_count=stats.loss_count,
            neutral_count=stats.neutral_count,
            win_rate=float(stats.win_rate) if stats.win_rate else None,
            avg_return=float(stats.avg_return) if stats.avg_return else None,
            median_return=float(stats.median_return) if stats.median_return else None,
            sharpe_ratio=float(stats.sharpe_ratio) if stats.sharpe_ratio else None,
            recommended_threshold=float(stats.recommended_score_threshold) if stats.recommended_score_threshold else None,
            lookback_days=stats.lookback_days,
        ))
    
    return results


def compute_live_win_rate(
    db: Session,
    method: str,
    underlying_symbol: Optional[str] = None,
    lookback_days: int = 90,
) -> tuple[Optional[float], int]:
    """Compute win rate directly from outcomes table (not cached).
    
    Useful for real-time updates before stats cache is refreshed.
    
    Returns: (win_rate, total_count)
    """
    from sqlalchemy import func
    
    cutoff = date.today() - timedelta(days=lookback_days)
    
    q = (
        db.query(models.OutlierOutcome)
        .filter(
            models.OutlierOutcome.method == method,
            models.OutlierOutcome.event_date >= cutoff,
        )
    )
    
    if underlying_symbol:
        q = q.filter(models.OutlierOutcome.underlying_symbol == underlying_symbol)
    
    total = q.count()
    if total == 0:
        return None, 0
    
    wins = q.filter(models.OutlierOutcome.outcome_label == models.OutlierOutcomeLabel.WIN).count()
    
    return wins / total, total


def get_dynamic_threshold(
    db: Session,
    method: str,
    underlying_symbol: Optional[str] = None,
    base_threshold: float = 3.0,
    min_signals: int = 10,
) -> float:
    """Get a dynamically adjusted threshold based on historical performance.
    
    Logic:
    - If win rate < 50%: increase threshold (be more selective)
    - If win rate > 60%: decrease threshold (capture more signals)
    - If insufficient data: use base threshold
    
    Args:
        db: SQLAlchemy session
        method: Detection method
        underlying_symbol: Optional underlying for specific threshold
        base_threshold: Default threshold (e.g., 3.0 for z-score)
        min_signals: Minimum signals required to adjust threshold
        
    Returns:
        Adjusted threshold value
    """
    # First try underlying-specific stats
    perf = None
    if underlying_symbol:
        perf = get_method_performance(db, method, underlying_symbol=underlying_symbol)
    
    # Fall back to method-wide stats
    if perf is None or perf.total_signals < min_signals:
        perf = get_method_performance(db, method)
    
    # If still no data or not enough samples, return base threshold
    if perf is None or perf.total_signals < min_signals or perf.win_rate is None:
        return base_threshold
    
    # Use cached recommendation if available
    if perf.recommended_threshold is not None:
        return perf.recommended_threshold
    
    # Otherwise compute dynamically
    win_rate = perf.win_rate
    
    if win_rate < 0.4:
        # Poor performance: increase threshold significantly
        return base_threshold * 1.5
    elif win_rate < 0.5:
        # Below average: increase threshold moderately
        return base_threshold * 1.25
    elif win_rate > 0.65:
        # Excellent performance: lower threshold
        return base_threshold * 0.8
    elif win_rate > 0.55:
        # Good performance: slightly lower threshold
        return base_threshold * 0.9
    else:
        # Average performance: keep base threshold
        return base_threshold


def get_performance_summary(db: Session, lookback_days: int = 90) -> Dict[str, Any]:
    """Get a summary of all method performances for display.
    
    Returns dict suitable for dashboard display.
    """
    methods = ["Z-Score", "IQR", "Pre-Event"]
    summary = {}
    
    for method in methods:
        perf = get_method_performance(db, method, lookback_days=lookback_days)
        if perf:
            summary[method] = perf.to_dict()
        else:
            summary[method] = {
                "method": method,
                "total_signals": 0,
                "win_rate": None,
                "confidence_level": "NONE",
            }
    
    # Overall stats
    from sqlalchemy import func
    
    cutoff = date.today() - timedelta(days=lookback_days)
    
    total = db.query(models.OutlierOutcome).filter(
        models.OutlierOutcome.event_date >= cutoff
    ).count()
    
    wins = db.query(models.OutlierOutcome).filter(
        models.OutlierOutcome.event_date >= cutoff,
        models.OutlierOutcome.outcome_label == models.OutlierOutcomeLabel.WIN,
    ).count()
    
    summary["_overall"] = {
        "total_signals": total,
        "win_count": wins,
        "win_rate": wins / total if total > 0 else None,
        "lookback_days": lookback_days,
    }
    
    return summary


def should_filter_signal(
    db: Session,
    method: str,
    underlying_symbol: str,
    score: float,
    flow_sentiment: Optional[float] = None,
    min_win_rate: float = 0.35,
) -> tuple[bool, str]:
    """Determine if a signal should be filtered based on historical performance.
    
    Returns: (should_filter, reason)
    """
    # Get underlying-specific performance
    perf = get_method_performance(db, method, underlying_symbol=underlying_symbol)
    
    # If underlying has very poor track record, filter
    if perf and perf.total_signals >= 10 and perf.win_rate is not None:
        if perf.win_rate < min_win_rate:
            return True, f"{underlying_symbol} has {perf.win_rate:.0%} win rate for {method}"
    
    # Get method-wide performance
    method_perf = get_method_performance(db, method)
    
    if method_perf and method_perf.total_signals >= 30:
        # Get dynamic threshold
        threshold = get_dynamic_threshold(db, method, underlying_symbol)
        
        # For z-score/iqr methods, check if score meets threshold
        if method in ("Z-Score", "IQR") and abs(score) < threshold:
            return True, f"Score {score:.2f} below dynamic threshold {threshold:.2f}"
    
    # If flow sentiment strongly contradicts, consider filtering
    if flow_sentiment is not None and abs(flow_sentiment) > 0.5:
        # Strong bearish flow on a bullish signal (or vice versa)
        # This could indicate the signal is likely to fail
        pass  # Let the flow adjustment handle this for now
    
    return False, ""
