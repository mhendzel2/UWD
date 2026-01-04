"""
Outlier Detection Module for Options Data

Implements three complementary outlier detection methods:
1. Z-Score: Flags OI changes >3σ from mean (99.7% confidence)
2. IQR Method: Robust to skewed distributions, flags 1.5×IQR extremes
3. Pre-Event + Volume: OI spike + low volume + earnings proximity signals

Enhanced with flow sentiment integration (v2):
- Flow sentiment from BOT_EOD data boosts or penalizes outlier scores
- Confirming flow (OI + flow agree) = score boost
- Divergent flow (OI vs flow disagree) = score penalty
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict, field
from pathlib import Path


# Flow sentiment configuration
FLOW_SENTIMENT_BOOST = 0.3  # Boost factor when flow confirms OI direction
FLOW_SENTIMENT_PENALTY = 0.5  # Penalty factor when flow contradicts OI direction
MIN_PREMIUM_THRESHOLD = 100_000  # Minimum $100k premium to consider flow meaningful


@dataclass
class OutlierResult:
    """Single outlier detection result"""
    underlying_symbol: str
    option_symbol: str
    oi_diff: float
    strike: Optional[float]
    stock_price: Optional[float]
    option_bid: Optional[float]
    option_ask: Optional[float]
    option_mid: Optional[float]
    option_last_fill: Optional[float]
    option_avg_price: Optional[float]
    percentage_of_total: Optional[float]
    days_to_earnings: Optional[int]
    dte: Optional[int]
    sector: Optional[str]
    method: str
    score: float  # z-score, iqr-distance, or manipulation score
    # Flow sentiment fields (v2)
    flow_sentiment: Optional[float] = None  # -1 (bearish) to +1 (bullish)
    flow_total_premium: Optional[float] = None
    flow_adjusted_score: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OutlierSummary:
    """Summary statistics for outlier detection"""
    method: str
    count: int
    top_symbol: str
    max_oi_change: float
    threshold_info: str
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def get_flow_sentiment_for_underlying(
    underlying: str,
    flow_metrics: Dict[str, Dict[str, Any]]
) -> tuple[Optional[float], Optional[float]]:
    """Get flow sentiment score and total premium for an underlying.
    
    Args:
        underlying: The underlying symbol (e.g., 'AAPL')
        flow_metrics: Dict of {underlying: {sentiment_score, total_premium, ...}}
        
    Returns:
        Tuple of (sentiment_score, total_premium) or (None, None) if not found
    """
    # Try both upper and original case
    metrics = flow_metrics.get(underlying.upper()) or flow_metrics.get(underlying)
    if not metrics:
        return None, None
    
    sentiment = metrics.get("sentiment_score")
    total_premium = metrics.get("total_premium", 0)
    
    return sentiment, total_premium


def apply_flow_sentiment_adjustment(
    result: OutlierResult,
    flow_metrics: Dict[str, Dict[str, Any]],
    option_type: Optional[str] = None
) -> OutlierResult:
    """Apply flow sentiment adjustment to an outlier result.
    
    Logic:
    - For CALL outliers: positive flow sentiment boosts, negative penalizes
    - For PUT outliers: negative flow sentiment boosts, positive penalizes
    - No adjustment if insufficient premium (<$100k)
    
    Args:
        result: Original outlier result
        flow_metrics: Dict of {underlying: {sentiment_score, total_premium, ...}}
        option_type: 'call' or 'put' - inferred from option_symbol if not provided
        
    Returns:
        Updated OutlierResult with flow-adjusted score
    """
    sentiment, total_premium = get_flow_sentiment_for_underlying(
        result.underlying_symbol, flow_metrics
    )
    
    # Store raw flow data regardless of adjustment
    result.flow_sentiment = sentiment
    result.flow_total_premium = total_premium
    
    # Don't adjust if no sentiment or insufficient premium
    if sentiment is None or (total_premium or 0) < MIN_PREMIUM_THRESHOLD:
        result.flow_adjusted_score = result.score
        return result
    
    # Determine if this is a call or put from the option symbol
    if option_type is None:
        sym = result.option_symbol.upper()
        # Standard OSI option symbol format: underlying + expiry + C/P + strike
        option_type = "call" if "C" in sym[-15:-8] else "put" if "P" in sym[-15:-8] else None
        # Fallback: check if C or P appears before the strike digits
        if option_type is None:
            for i, char in enumerate(sym):
                if char in ("C", "P") and i > 0:
                    option_type = "call" if char == "C" else "put"
                    break
    
    # Determine OI direction (positive OI_diff = accumulation)
    oi_direction = 1 if result.oi_diff > 0 else -1
    
    # Calculate flow impact
    # For calls: bullish flow (positive sentiment) + positive OI = confirming
    # For puts: bearish flow (negative sentiment) + positive OI = confirming
    if option_type == "call":
        # Call accumulation + bullish flow = confirming
        flow_agrees = (oi_direction > 0 and sentiment > 0.2) or (oi_direction < 0 and sentiment < -0.2)
        flow_disagrees = (oi_direction > 0 and sentiment < -0.2) or (oi_direction < 0 and sentiment > 0.2)
    elif option_type == "put":
        # Put accumulation + bearish flow = confirming
        flow_agrees = (oi_direction > 0 and sentiment < -0.2) or (oi_direction < 0 and sentiment > 0.2)
        flow_disagrees = (oi_direction > 0 and sentiment > 0.2) or (oi_direction < 0 and sentiment < -0.2)
    else:
        # Unknown option type, no adjustment
        result.flow_adjusted_score = result.score
        return result
    
    # Apply adjustment
    if flow_agrees:
        # Boost: multiply by (1 + boost_factor * |sentiment|)
        adjustment = 1 + FLOW_SENTIMENT_BOOST * abs(sentiment)
        result.flow_adjusted_score = result.score * adjustment
    elif flow_disagrees:
        # Penalty: multiply by (1 - penalty_factor * |sentiment|)
        adjustment = max(0.1, 1 - FLOW_SENTIMENT_PENALTY * abs(sentiment))
        result.flow_adjusted_score = result.score * adjustment
    else:
        # Neutral sentiment, no change
        result.flow_adjusted_score = result.score
    
    return result


def enhance_results_with_flow(
    results: List[OutlierResult],
    flow_metrics: Dict[str, Dict[str, Any]]
) -> List[OutlierResult]:
    """Enhance a list of outlier results with flow sentiment data.
    
    Args:
        results: List of OutlierResult objects
        flow_metrics: Dict of {underlying: {sentiment_score, total_premium, ...}}
        
    Returns:
        Updated list with flow-adjusted scores
    """
    if not flow_metrics:
        # No flow data, just set adjusted = original
        for r in results:
            r.flow_adjusted_score = r.score
        return results
    
    return [apply_flow_sentiment_adjustment(r, flow_metrics) for r in results]


def load_oi_data(file_path: Path) -> pd.DataFrame:
    """Load and parse OI changes CSV file"""
    df = pd.read_csv(file_path)
    
    # Normalize column names (handle both formats)
    column_mapping = {
        'oi_diff_plain': 'oi_diff',
        'option_symbol': 'option_symbol',
        'underlying_symbol': 'underlying_symbol',
        'stock_price': 'stock_price',
        'percentage_of_total': 'percentage_of_total',
        'next_earnings_date': 'next_earnings_date',
        'curr_date': 'curr_date',
        'dte': 'dte',
        'sector': 'sector',
        'strike': 'strike',
    }
    
    # Rename columns if they exist
    for old_name, new_name in column_mapping.items():
        if old_name in df.columns and old_name != new_name:
            df = df.rename(columns={old_name: new_name})
    
    # Parse numeric columns
    numeric_cols = ['oi_diff', 'stock_price', 'percentage_of_total', 'dte', 'strike']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # Parse dates
    if 'curr_date' in df.columns:
        df['curr_date'] = pd.to_datetime(df['curr_date'], errors='coerce')
    if 'next_earnings_date' in df.columns:
        df['next_earnings_date'] = pd.to_datetime(df['next_earnings_date'], errors='coerce')
    
    # Calculate days to earnings if both dates exist
    if 'curr_date' in df.columns and 'next_earnings_date' in df.columns:
        df['days_to_earnings'] = (df['next_earnings_date'] - df['curr_date']).dt.days
    else:
        df['days_to_earnings'] = None
        
    return df


def load_hot_chains_data(file_path: Path) -> pd.DataFrame:
    """Load and parse hot chains CSV file"""
    df = pd.read_csv(file_path)
    
    # Rename columns if needed
    if 'ticker' in df.columns:
        df = df.rename(columns={'ticker': 'underlying_symbol'})
        
    return df


def load_darkpool_data(file_path: Path) -> pd.DataFrame:
    """Load and parse darkpool EOD CSV file"""
    df = pd.read_csv(file_path)
    return df


def detect_zscore_outliers(
    df: pd.DataFrame,
    threshold: float = 3.0,
    column: str = 'oi_diff',
    baseline_series: Optional[pd.Series] = None,
) -> tuple[List[OutlierResult], OutlierSummary]:
    """
    Z-Score Outlier Detection
    
    Flags OI changes >3 standard deviations from mean.
    Best for normally distributed data.
    
    Formula: z = (x - μ) / σ
    Threshold: |z| > 3 (99.7% confidence)
    """
    oi_clean = df[column].dropna()
    
    if len(oi_clean) < 10:
        return [], OutlierSummary(
            method='Z-Score',
            count=0,
            top_symbol='N/A',
            max_oi_change=0.0,
            threshold_info=f'Insufficient data (n={len(oi_clean)})'
        )
    
    baseline_clean = None
    if baseline_series is not None:
        baseline_clean = pd.to_numeric(baseline_series, errors="coerce").dropna()

    # Calculate z-scores (optionally using baseline mean/std)
    if baseline_clean is not None and len(baseline_clean) >= 10:
        mean_val = float(baseline_clean.mean())
        std_val = float(baseline_clean.std(ddof=0))
        if std_val == 0.0:
            z_scores = np.zeros(len(oi_clean))
        else:
            z_scores = np.abs((oi_clean.astype(float) - mean_val) / std_val)
        threshold_info = (
            f'baseline(n={len(baseline_clean)}): mu={mean_val:.2f}, sigma={std_val:.2f}, threshold=|z|>{threshold}'
        )
    else:
        # Avoid SciPy dependency: z = (x - mu) / sigma
        mean_val = float(oi_clean.mean())
        std_val = float(oi_clean.std(ddof=0))
        if std_val == 0.0:
            z_scores = np.zeros(len(oi_clean))
        else:
            z_scores = np.abs((oi_clean.astype(float) - mean_val) / std_val)
        mean_val = float(oi_clean.mean())
        std_val = float(oi_clean.std(ddof=0))
        threshold_info = f'mu={mean_val:.2f}, sigma={std_val:.2f}, threshold=|z|>{threshold}'
    df_with_z = df.loc[oi_clean.index].copy()
    df_with_z['z_score'] = z_scores
    
    # Filter outliers
    outliers_df = df_with_z[df_with_z['z_score'] > threshold].copy()
    outliers_df = outliers_df.sort_values(column, ascending=False)
    
    # Build results
    results = []
    for _, row in outliers_df.head(50).iterrows():  # Limit to top 50
        bid_v = row.get("last_bid")
        ask_v = row.get("last_ask")
        last_fill_v = row.get("last_fill")
        avg_price_v = row.get("avg_price")
        bid = float(bid_v) if bid_v is not None and pd.notna(bid_v) else None
        ask = float(ask_v) if ask_v is not None and pd.notna(ask_v) else None
        last_fill = float(last_fill_v) if last_fill_v is not None and pd.notna(last_fill_v) else None
        avg_price = float(avg_price_v) if avg_price_v is not None and pd.notna(avg_price_v) else None
        mid = (bid + ask) / 2.0 if (bid is not None and ask is not None) else None
        results.append(OutlierResult(
            underlying_symbol=str(row.get('underlying_symbol', 'N/A')),
            option_symbol=str(row.get('option_symbol', 'N/A')),
            oi_diff=float(row.get(column, 0)),
            strike=float(row['strike']) if pd.notna(row.get('strike')) else None,
            stock_price=float(row['stock_price']) if pd.notna(row.get('stock_price')) else None,
            option_bid=bid,
            option_ask=ask,
            option_mid=mid,
            option_last_fill=last_fill,
            option_avg_price=avg_price,
            percentage_of_total=float(row['percentage_of_total']) if pd.notna(row.get('percentage_of_total')) else None,
            days_to_earnings=int(row['days_to_earnings']) if pd.notna(row.get('days_to_earnings')) else None,
            dte=int(row['dte']) if pd.notna(row.get('dte')) else None,
            sector=str(row['sector']) if pd.notna(row.get('sector')) else None,
            method='Z-Score',
            score=float(row['z_score'])
        ))
    
    summary = OutlierSummary(
        method='Z-Score',
        count=len(outliers_df),
        top_symbol=str(outliers_df['underlying_symbol'].iloc[0]) if len(outliers_df) > 0 else 'N/A',
        max_oi_change=float(outliers_df[column].max()) if len(outliers_df) > 0 else 0.0,
        threshold_info=threshold_info
    )
    
    return results, summary


def detect_iqr_outliers(
    df: pd.DataFrame,
    multiplier: float = 1.5,
    column: str = 'oi_diff',
    baseline_series: Optional[pd.Series] = None,
) -> tuple[List[OutlierResult], OutlierSummary]:
    """
    IQR (Interquartile Range) Outlier Detection
    
    Robust to skewed distributions; flags 1.5×IQR extremes.
    Captures heavy-tailed OI distributions.
    
    Bounds: Q1 - 1.5×IQR to Q3 + 1.5×IQR
    """
    oi_clean = df[column].dropna()
    
    if len(oi_clean) < 10:
        return [], OutlierSummary(
            method='IQR',
            count=0,
            top_symbol='N/A',
            max_oi_change=0.0,
            threshold_info=f'Insufficient data (n={len(oi_clean)})'
        )
    
    baseline_clean = None
    if baseline_series is not None:
        baseline_clean = pd.to_numeric(baseline_series, errors="coerce").dropna()

    # Calculate IQR bounds (optionally using baseline quantiles)
    series_for_bounds = baseline_clean if baseline_clean is not None and len(baseline_clean) >= 10 else oi_clean

    Q1 = series_for_bounds.quantile(0.25)
    Q3 = series_for_bounds.quantile(0.75)
    IQR = Q3 - Q1
    lower_bound = Q1 - multiplier * IQR
    upper_bound = Q3 + multiplier * IQR
    
    # Identify outliers
    df_with_bounds = df.loc[oi_clean.index].copy()
    df_with_bounds['is_outlier'] = (df_with_bounds[column] < lower_bound) | (df_with_bounds[column] > upper_bound)
    df_with_bounds['iqr_distance'] = np.where(
        df_with_bounds[column] > upper_bound,
        (df_with_bounds[column] - upper_bound) / IQR,
        np.where(
            df_with_bounds[column] < lower_bound,
            (lower_bound - df_with_bounds[column]) / IQR,
            0
        )
    )
    
    outliers_df = df_with_bounds[df_with_bounds['is_outlier']].copy()
    outliers_df = outliers_df.sort_values(column, ascending=False)
    
    # Build results
    results = []
    for _, row in outliers_df.head(50).iterrows():
        bid_v = row.get("last_bid")
        ask_v = row.get("last_ask")
        last_fill_v = row.get("last_fill")
        avg_price_v = row.get("avg_price")
        bid = float(bid_v) if bid_v is not None and pd.notna(bid_v) else None
        ask = float(ask_v) if ask_v is not None and pd.notna(ask_v) else None
        last_fill = float(last_fill_v) if last_fill_v is not None and pd.notna(last_fill_v) else None
        avg_price = float(avg_price_v) if avg_price_v is not None and pd.notna(avg_price_v) else None
        mid = (bid + ask) / 2.0 if (bid is not None and ask is not None) else None
        results.append(OutlierResult(
            underlying_symbol=str(row.get('underlying_symbol', 'N/A')),
            option_symbol=str(row.get('option_symbol', 'N/A')),
            oi_diff=float(row.get(column, 0)),
            strike=float(row['strike']) if pd.notna(row.get('strike')) else None,
            stock_price=float(row['stock_price']) if pd.notna(row.get('stock_price')) else None,
            option_bid=bid,
            option_ask=ask,
            option_mid=mid,
            option_last_fill=last_fill,
            option_avg_price=avg_price,
            percentage_of_total=float(row['percentage_of_total']) if pd.notna(row.get('percentage_of_total')) else None,
            days_to_earnings=int(row['days_to_earnings']) if pd.notna(row.get('days_to_earnings')) else None,
            dte=int(row['dte']) if pd.notna(row.get('dte')) else None,
            sector=str(row['sector']) if pd.notna(row.get('sector')) else None,
            method='IQR',
            score=float(row['iqr_distance'])
        ))
    
    summary = OutlierSummary(
        method='IQR',
        count=len(outliers_df),
        top_symbol=str(outliers_df['underlying_symbol'].iloc[0]) if len(outliers_df) > 0 else 'N/A',
        max_oi_change=float(outliers_df[column].max()) if len(outliers_df) > 0 else 0.0,
        threshold_info=(
            (
                f'baseline(n={len(baseline_clean)}): '
                if baseline_clean is not None and len(baseline_clean) >= 10
                else ''
            )
            + f'Q1={Q1:.4f}, Q3={Q3:.4f}, IQR={IQR:.4f}, bounds=[{lower_bound:.4f}, {upper_bound:.4f}]'
        )
    )
    
    return results, summary


def detect_preevent_manipulation(
    df: pd.DataFrame,
    earnings_threshold_days: int = 14,
    chain_percentage_threshold: float = 0.20,
    oi_percentile_threshold: float = 0.95,
    column: str = 'oi_diff'
) -> tuple[List[OutlierResult], OutlierSummary]:
    """
    Pre-Event + Volume Manipulation Detection
    
    Most predictive for manipulation/news signals.
    Criteria: OI spike + low underlying volume + earnings proximity.
    
    Key thresholds:
    - OI > 95th percentile
    - Days to earnings < 14
    - % of total chain > 20%
    
    Score: oidiff × percentage_of_total × (1 / days_to_earnings)
    """
    oi_clean = df[column].dropna()
    
    if len(oi_clean) < 10:
        return [], OutlierSummary(
            method='Pre-Event Manipulation',
            count=0,
            top_symbol='N/A',
            max_oi_change=0.0,
            threshold_info=f'Insufficient data (n={len(oi_clean)})'
        )
    
    oi_threshold = oi_clean.quantile(oi_percentile_threshold)
    
    # Filter for pre-earnings window
    df_filtered = df.copy()
    
    # Apply filters
    has_earnings = pd.notna(df_filtered.get('days_to_earnings'))
    pre_earnings = df_filtered['days_to_earnings'] < earnings_threshold_days if 'days_to_earnings' in df_filtered else False
    high_chain_pct = df_filtered['percentage_of_total'] > chain_percentage_threshold if 'percentage_of_total' in df_filtered else False
    high_oi = df_filtered[column] > oi_threshold
    
    # Combine filters (relax if missing data)
    if 'days_to_earnings' in df_filtered.columns and 'percentage_of_total' in df_filtered.columns:
        mask = has_earnings & pre_earnings & high_chain_pct & high_oi
    elif 'percentage_of_total' in df_filtered.columns:
        mask = high_chain_pct & high_oi
    else:
        mask = high_oi
    
    candidates = df_filtered[mask].copy()
    
    if len(candidates) == 0:
        # Fallback: just use high OI threshold
        candidates = df_filtered[high_oi].copy()
    
    # Calculate manipulation score
    def calc_manip_score(row):
        oi_val = row.get(column, 0) or 0
        pct_total = row.get('percentage_of_total', 0.01) or 0.01
        days = row.get('days_to_earnings', 30) or 30
        days = max(days, 1)  # Avoid division by zero
        return abs(oi_val) * pct_total * (1 / days)
    
    candidates['manip_score'] = candidates.apply(calc_manip_score, axis=1)
    candidates = candidates.sort_values('manip_score', ascending=False)
    
    # Build results
    results = []
    for _, row in candidates.head(50).iterrows():
        bid_v = row.get("last_bid")
        ask_v = row.get("last_ask")
        last_fill_v = row.get("last_fill")
        avg_price_v = row.get("avg_price")
        bid = float(bid_v) if bid_v is not None and pd.notna(bid_v) else None
        ask = float(ask_v) if ask_v is not None and pd.notna(ask_v) else None
        last_fill = float(last_fill_v) if last_fill_v is not None and pd.notna(last_fill_v) else None
        avg_price = float(avg_price_v) if avg_price_v is not None and pd.notna(avg_price_v) else None
        mid = (bid + ask) / 2.0 if (bid is not None and ask is not None) else None
        results.append(OutlierResult(
            underlying_symbol=str(row.get('underlying_symbol', 'N/A')),
            option_symbol=str(row.get('option_symbol', 'N/A')),
            oi_diff=float(row.get(column, 0)),
            strike=float(row['strike']) if pd.notna(row.get('strike')) else None,
            stock_price=float(row['stock_price']) if pd.notna(row.get('stock_price')) else None,
            option_bid=bid,
            option_ask=ask,
            option_mid=mid,
            option_last_fill=last_fill,
            option_avg_price=avg_price,
            percentage_of_total=float(row['percentage_of_total']) if pd.notna(row.get('percentage_of_total')) else None,
            days_to_earnings=int(row['days_to_earnings']) if pd.notna(row.get('days_to_earnings')) else None,
            dte=int(row['dte']) if pd.notna(row.get('dte')) else None,
            sector=str(row['sector']) if pd.notna(row.get('sector')) else None,
            method='Pre-Event',
            score=float(row['manip_score'])
        ))
    
    summary = OutlierSummary(
        method='Pre-Event Manipulation',
        count=len(candidates),
        top_symbol=str(candidates['underlying_symbol'].iloc[0]) if len(candidates) > 0 else 'N/A',
        max_oi_change=float(candidates[column].max()) if len(candidates) > 0 else 0.0,
        threshold_info=f'earnings<{earnings_threshold_days}d, chain>{chain_percentage_threshold*100:.0f}%, OI>{oi_percentile_threshold*100:.0f}%ile'
    )
    
    return results, summary


def get_distribution_stats(df: pd.DataFrame, column: str = 'oi_diff') -> Dict[str, Any]:
    """Get distribution statistics for visualization"""
    oi_clean = df[column].dropna()
    
    if len(oi_clean) < 10:
        return {'error': 'Insufficient data'}
    
    # Calculate histogram bins
    hist, bin_edges = np.histogram(oi_clean, bins=50)
    
    # IQR bounds
    Q1 = oi_clean.quantile(0.25)
    Q3 = oi_clean.quantile(0.75)
    IQR = Q3 - Q1
    lower_bound = Q1 - 1.5 * IQR
    upper_bound = Q3 + 1.5 * IQR
    
    # Percentiles
    percentiles = {
        'p5': float(oi_clean.quantile(0.05)),
        'p25': float(Q1),
        'p50': float(oi_clean.quantile(0.50)),
        'p75': float(Q3),
        'p95': float(oi_clean.quantile(0.95)),
        'p99': float(oi_clean.quantile(0.99)),
    }
    
    return {
        'count': int(len(oi_clean)),
        'mean': float(oi_clean.mean()),
        'std': float(oi_clean.std()),
        'min': float(oi_clean.min()),
        'max': float(oi_clean.max()),
        'iqr_lower': float(lower_bound),
        'iqr_upper': float(upper_bound),
        'percentiles': percentiles,
        'histogram': {
            'counts': hist.tolist(),
            'bin_edges': bin_edges.tolist()
        }
    }


def run_all_detection_methods(
    df: pd.DataFrame,
    zscore_threshold: float = 3.0,
    iqr_multiplier: float = 1.5,
    earnings_days: int = 14,
    chain_pct: float = 0.20,
    baseline_df: Optional[pd.DataFrame] = None,
    flow_metrics: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Run all outlier detection methods and return combined results
    
    Args:
        df: DataFrame with OI data
        zscore_threshold: Z-score threshold for outlier detection
        iqr_multiplier: IQR multiplier for outlier detection
        earnings_days: Days to earnings threshold
        chain_pct: Chain percentage threshold
        baseline_df: Optional baseline DataFrame for z-score/IQR calculation
        flow_metrics: Optional dict of {underlying: {sentiment_score, total_premium, ...}}
                      for flow-adjusted scoring
    
    Note: For dynamic thresholds based on historical performance, use 
    run_all_detection_methods_with_feedback() instead.
    """
    
    # Run each method
    baseline_series = None
    if baseline_df is not None and 'oi_diff' in baseline_df.columns:
        baseline_series = baseline_df['oi_diff']

    zscore_results, zscore_summary = detect_zscore_outliers(
        df,
        threshold=zscore_threshold,
        baseline_series=baseline_series,
    )
    iqr_results, iqr_summary = detect_iqr_outliers(
        df,
        multiplier=iqr_multiplier,
        baseline_series=baseline_series,
    )
    preevent_results, preevent_summary = detect_preevent_manipulation(
        df, 
        earnings_threshold_days=earnings_days,
        chain_percentage_threshold=chain_pct
    )
    
    # Enhance results with flow sentiment if available
    if flow_metrics:
        zscore_results = enhance_results_with_flow(zscore_results, flow_metrics)
        iqr_results = enhance_results_with_flow(iqr_results, flow_metrics)
        preevent_results = enhance_results_with_flow(preevent_results, flow_metrics)
    else:
        # Set adjusted score = original score when no flow data
        for r in zscore_results + iqr_results + preevent_results:
            r.flow_adjusted_score = r.score
    
    # Get distribution stats
    dist_stats = get_distribution_stats(df)
    
    # Get top symbols across all methods
    all_symbols = set()
    for r in zscore_results + iqr_results + preevent_results:
        all_symbols.add(r.underlying_symbol)
    
    return {
        'zscore': {
            'results': [r.to_dict() for r in zscore_results],
            'summary': zscore_summary.to_dict()
        },
        'iqr': {
            'results': [r.to_dict() for r in iqr_results],
            'summary': iqr_summary.to_dict()
        },
        'preevent': {
            'results': [r.to_dict() for r in preevent_results],
            'summary': preevent_summary.to_dict()
        },
        'distribution': dist_stats,
        'unique_symbols': len(all_symbols),
        'total_outliers': len(zscore_results) + len(iqr_results) + len(preevent_results),
        'flow_enhanced': flow_metrics is not None
    }


def analyze_from_session_data(
    oi_data: List[Dict[str, Any]],
    zscore_threshold: float = 3.0,
    iqr_multiplier: float = 1.5,
    earnings_days: int = 14,
    chain_pct: float = 0.20,
    baseline_oi_data: Optional[List[Dict[str, Any]]] = None,
    flow_metrics: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Analyze outliers from session data (already loaded in DB)
    
    Args:
        oi_data: List of OI change rows
        zscore_threshold: Z-score threshold for outlier detection
        iqr_multiplier: IQR multiplier for outlier detection
        earnings_days: Days to earnings threshold
        chain_pct: Chain percentage threshold
        baseline_oi_data: Optional baseline data for z-score/IQR calculation
        flow_metrics: Optional dict of {underlying: {sentiment_score, total_premium, ...}}
                      for flow-adjusted scoring
    """
    
    if not oi_data:
        return {'error': 'No OI data provided'}
    
    def _normalize_df(rows: List[Dict[str, Any]]) -> pd.DataFrame:
        df_local = pd.DataFrame(rows)

        # Normalize column names from DB format
        column_mapping = {
            # Ingest CSV headers (snake_case)
            'oi_diff_plain': 'oi_diff',

            # Legacy DB row format (lowercase / no underscores)
            'oidiff': 'oi_diff',
            'underlyingsymbol': 'underlying_symbol',
            'plainoptionsymbol': 'option_symbol',
            'stockprice': 'stock_price',
            'percentageoftotal': 'percentage_of_total',
            'nextearningsdate': 'next_earnings_date',
            'currdate': 'curr_date',
        }

        for old_name, new_name in column_mapping.items():
            if old_name in df_local.columns:
                df_local = df_local.rename(columns={old_name: new_name})

        # Parse numeric columns
        numeric_cols = ['oi_diff', 'stock_price', 'percentage_of_total', 'dte', 'strike']
        for col in numeric_cols:
            if col in df_local.columns:
                df_local[col] = pd.to_numeric(df_local[col], errors='coerce')

        # Parse dates and calculate days to earnings
        if 'curr_date' in df_local.columns:
            df_local['curr_date'] = pd.to_datetime(df_local['curr_date'], errors='coerce')
        if 'next_earnings_date' in df_local.columns:
            df_local['next_earnings_date'] = pd.to_datetime(df_local['next_earnings_date'], errors='coerce')
            if 'curr_date' in df_local.columns:
                df_local['days_to_earnings'] = (df_local['next_earnings_date'] - df_local['curr_date']).dt.days

        return df_local

    # Convert to DataFrame
    df = _normalize_df(oi_data)

    baseline_df = None
    if baseline_oi_data:
        baseline_df = _normalize_df(baseline_oi_data)
    
    return run_all_detection_methods(
        df,
        zscore_threshold=zscore_threshold,
        iqr_multiplier=iqr_multiplier,
        earnings_days=earnings_days,
        chain_pct=chain_pct,
        baseline_df=baseline_df,
        flow_metrics=flow_metrics,
    )


def run_with_dynamic_thresholds(
    db,  # SQLAlchemy session
    oi_data: List[Dict[str, Any]],
    baseline_oi_data: Optional[List[Dict[str, Any]]] = None,
    flow_metrics: Optional[Dict[str, Dict[str, Any]]] = None,
    base_zscore_threshold: float = 3.0,
    base_iqr_multiplier: float = 1.5,
    earnings_days: int = 14,
    chain_pct: float = 0.20,
    use_dynamic_thresholds: bool = True,
) -> Dict[str, Any]:
    """Run outlier detection with dynamic thresholds based on historical performance.
    
    This function retrieves recommended thresholds from the success_rate module
    based on historical win rates and adjusts detection parameters accordingly.
    
    Args:
        db: SQLAlchemy session for querying historical performance
        oi_data: List of OI change rows
        baseline_oi_data: Optional baseline data for z-score/IQR calculation
        flow_metrics: Optional dict for flow-adjusted scoring
        base_zscore_threshold: Default z-score threshold (may be adjusted)
        base_iqr_multiplier: Default IQR multiplier (may be adjusted)
        earnings_days: Days to earnings threshold
        chain_pct: Chain percentage threshold
        use_dynamic_thresholds: If True, adjust thresholds based on history
        
    Returns:
        Dict with detection results plus threshold info
    """
    from app.analysis.success_rate import get_dynamic_threshold, get_method_performance
    
    zscore_threshold = base_zscore_threshold
    iqr_multiplier = base_iqr_multiplier
    threshold_adjustments = {}
    
    if use_dynamic_thresholds and db is not None:
        try:
            # Get dynamic z-score threshold
            dyn_zscore = get_dynamic_threshold(db, "Z-Score", base_threshold=base_zscore_threshold)
            if dyn_zscore != base_zscore_threshold:
                threshold_adjustments["zscore"] = {
                    "base": base_zscore_threshold,
                    "dynamic": dyn_zscore,
                    "reason": "Adjusted based on historical win rate",
                }
                zscore_threshold = dyn_zscore
            
            # Get dynamic IQR multiplier (same logic, different base)
            dyn_iqr = get_dynamic_threshold(db, "IQR", base_threshold=base_iqr_multiplier)
            if dyn_iqr != base_iqr_multiplier:
                threshold_adjustments["iqr"] = {
                    "base": base_iqr_multiplier,
                    "dynamic": dyn_iqr,
                    "reason": "Adjusted based on historical win rate",
                }
                iqr_multiplier = dyn_iqr
            
            # Get performance summaries for context
            for method in ["Z-Score", "IQR", "Pre-Event"]:
                perf = get_method_performance(db, method)
                if perf:
                    threshold_adjustments[f"{method.lower().replace('-', '_')}_perf"] = {
                        "win_rate": perf.win_rate,
                        "total_signals": perf.total_signals,
                        "confidence": perf.confidence_level,
                    }
        except Exception as e:
            # If dynamic threshold lookup fails, continue with base thresholds
            threshold_adjustments["error"] = str(e)
    
    # Run the main detection
    results = analyze_from_session_data(
        oi_data,
        zscore_threshold=zscore_threshold,
        iqr_multiplier=iqr_multiplier,
        earnings_days=earnings_days,
        chain_pct=chain_pct,
        baseline_oi_data=baseline_oi_data,
        flow_metrics=flow_metrics,
    )
    
    # Add threshold adjustment info to results
    results["threshold_adjustments"] = threshold_adjustments
    results["thresholds_used"] = {
        "zscore": zscore_threshold,
        "iqr_multiplier": iqr_multiplier,
        "earnings_days": earnings_days,
        "chain_pct": chain_pct,
    }
    
    return results
