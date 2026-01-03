"""
Outlier Detection Module for Options Data

Implements three complementary outlier detection methods:
1. Z-Score: Flags OI changes >3σ from mean (99.7% confidence)
2. IQR Method: Robust to skewed distributions, flags 1.5×IQR extremes
3. Pre-Event + Volume: OI spike + low volume + earnings proximity signals
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class OutlierResult:
    """Single outlier detection result"""
    underlying_symbol: str
    option_symbol: str
    oi_diff: float
    strike: Optional[float]
    stock_price: Optional[float]
    percentage_of_total: Optional[float]
    days_to_earnings: Optional[int]
    dte: Optional[int]
    sector: Optional[str]
    method: str
    score: float  # z-score, iqr-distance, or manipulation score
    
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
        results.append(OutlierResult(
            underlying_symbol=str(row.get('underlying_symbol', 'N/A')),
            option_symbol=str(row.get('option_symbol', 'N/A')),
            oi_diff=float(row.get(column, 0)),
            strike=float(row['strike']) if pd.notna(row.get('strike')) else None,
            stock_price=float(row['stock_price']) if pd.notna(row.get('stock_price')) else None,
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
        results.append(OutlierResult(
            underlying_symbol=str(row.get('underlying_symbol', 'N/A')),
            option_symbol=str(row.get('option_symbol', 'N/A')),
            oi_diff=float(row.get(column, 0)),
            strike=float(row['strike']) if pd.notna(row.get('strike')) else None,
            stock_price=float(row['stock_price']) if pd.notna(row.get('stock_price')) else None,
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
        results.append(OutlierResult(
            underlying_symbol=str(row.get('underlying_symbol', 'N/A')),
            option_symbol=str(row.get('option_symbol', 'N/A')),
            oi_diff=float(row.get(column, 0)),
            strike=float(row['strike']) if pd.notna(row.get('strike')) else None,
            stock_price=float(row['stock_price']) if pd.notna(row.get('stock_price')) else None,
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
) -> Dict[str, Any]:
    """Run all outlier detection methods and return combined results"""
    
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
        'total_outliers': len(zscore_results) + len(iqr_results) + len(preevent_results)
    }


def analyze_from_session_data(
    oi_data: List[Dict[str, Any]],
    zscore_threshold: float = 3.0,
    iqr_multiplier: float = 1.5,
    earnings_days: int = 14,
    chain_pct: float = 0.20,
    baseline_oi_data: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Analyze outliers from session data (already loaded in DB)"""
    
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
    )
