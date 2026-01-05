"""Backfill outlier outcomes from outlier_events.csv and compute method statistics.

This script:
1. Reads outlier_events.csv (produced by outlier_performance_report.py)
2. Classifies each event as WIN/LOSS/NEUTRAL based on returns
3. Stores outcomes in the outlier_outcomes table
4. Computes and stores aggregated statistics in outlier_method_stats

Usage:
  $env:UW_DATABASE_URL="postgresql+psycopg2://uw_app:uw_password@127.0.0.1:5433/uw_eod"
  python scripts/backfill_outlier_outcomes.py

Options:
  --events-csv PATH     Path to outlier_events.csv (default: backend/tmp/outlier_events.csv)
  --win-threshold FLOAT Minimum return to classify as WIN (default: 0.05 = 5%)
  --loss-threshold FLOAT Maximum return to classify as LOSS (default: -0.05 = -5%)
  --horizon INT         Trading days horizon for outcome classification (default: 5)
  --lookback-days INT   Days to look back for stats computation (default: 90)
  --dry-run             Don't write to database, just print summary
"""

from __future__ import annotations

import argparse
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import func

from app.db import models
from app.db.engine import session_scope


def classify_outcome(
    return_val: float | None,
    win_threshold: float,
    loss_threshold: float,
) -> models.OutlierOutcomeLabel | None:
    """Classify a return value as WIN, LOSS, or NEUTRAL."""
    if return_val is None:
        return None
    if return_val >= win_threshold:
        return models.OutlierOutcomeLabel.WIN
    if return_val <= loss_threshold:
        return models.OutlierOutcomeLabel.LOSS
    return models.OutlierOutcomeLabel.NEUTRAL


def load_events_csv(path: Path) -> pd.DataFrame:
    """Load and parse the outlier_events.csv file."""
    df = pd.read_csv(path)
    
    # Parse date columns
    date_cols = ["event_date", "anchor_date"]
    for col in date_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
    
    # Parse numeric columns
    numeric_cols = [
        "score", "oi_diff", "close_0", "strike", "dte", "option_mid_0",
        "flow_sentiment", "flow_total_premium", "flow_adjusted_score",
        "ret_1", "ret_5", "ret_20",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    
    return df


def backfill_outcomes(
    df: pd.DataFrame,
    win_threshold: float,
    loss_threshold: float,
    horizon: int,
    dry_run: bool = False,
) -> tuple[int, int, int]:
    """
    Insert or update outlier outcomes from DataFrame.
    
    Returns: (inserted, updated, skipped)
    """
    ret_col = f"ret_{horizon}"
    if ret_col not in df.columns:
        print(f"Warning: Column {ret_col} not found. Available: {list(df.columns)}")
        return 0, 0, len(df)
    
    inserted = 0
    updated = 0
    skipped = 0
    
    with session_scope() as db:
        for _, row in df.iterrows():
            event_date = row.get("event_date")
            underlying = str(row.get("underlying_symbol") or "").strip().upper()
            option_symbol = str(row.get("option_symbol") or "").strip().upper() or None
            method = str(row.get("method") or "").strip()
            
            if not event_date or not underlying or not method:
                skipped += 1
                continue
            
            # Get return value for classification
            ret_val = row.get(ret_col)
            if pd.isna(ret_val):
                ret_val = None
            else:
                ret_val = float(ret_val)
            
            outcome_label = classify_outcome(ret_val, win_threshold, loss_threshold)
            
            # Check for existing record
            existing = (
                db.query(models.OutlierOutcome)
                .filter(
                    models.OutlierOutcome.event_date == event_date,
                    models.OutlierOutcome.underlying_symbol == underlying,
                    models.OutlierOutcome.option_symbol == option_symbol,
                    models.OutlierOutcome.method == method,
                )
                .first()
            )
            
            def _safe_float(v, default=None):
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    return default
                try:
                    return float(v)
                except (ValueError, TypeError):
                    return default
            
            def _safe_int(v, default=None):
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    return default
                try:
                    return int(v)
                except (ValueError, TypeError):
                    return default
            
            anchor_date = row.get("anchor_date") or event_date
            
            payload = {
                "event_date": event_date,
                "underlying_symbol": underlying,
                "option_symbol": option_symbol,
                "method": method,
                "score": Decimal(str(_safe_float(row.get("score"), 0))),
                "flow_sentiment": Decimal(str(_safe_float(row.get("flow_sentiment")))) if _safe_float(row.get("flow_sentiment")) is not None else None,
                "flow_adjusted_score": Decimal(str(_safe_float(row.get("flow_adjusted_score")))) if _safe_float(row.get("flow_adjusted_score")) is not None else None,
                "oi_diff": Decimal(str(_safe_float(row.get("oi_diff")))) if _safe_float(row.get("oi_diff")) is not None else None,
                "strike": Decimal(str(_safe_float(row.get("strike")))) if _safe_float(row.get("strike")) is not None else None,
                "dte": _safe_int(row.get("dte")),
                "sector": str(row.get("sector")) if row.get("sector") and not pd.isna(row.get("sector")) else None,
                "entry_date": anchor_date,
                "entry_price_underlying": Decimal(str(_safe_float(row.get("close_0")))) if _safe_float(row.get("close_0")) is not None else None,
                "entry_price_option": Decimal(str(_safe_float(row.get("option_mid_0")))) if _safe_float(row.get("option_mid_0")) is not None else None,
                "return_1d": Decimal(str(_safe_float(row.get("ret_1")))) if _safe_float(row.get("ret_1")) is not None else None,
                "return_5d": Decimal(str(_safe_float(row.get("ret_5")))) if _safe_float(row.get("ret_5")) is not None else None,
                "return_20d": Decimal(str(_safe_float(row.get("ret_20")))) if _safe_float(row.get("ret_20")) is not None else None,
                "outcome_label": outcome_label,
                "win_threshold_used": Decimal(str(win_threshold)),
                "loss_threshold_used": Decimal(str(loss_threshold)),
            }
            
            # Calculate holding days if we have exit info
            close_col = f"close_{horizon}"
            date_col = f"date_{horizon}"
            if date_col in row and not pd.isna(row.get(date_col)):
                try:
                    exit_date = pd.to_datetime(row[date_col]).date()
                    payload["exit_date"] = exit_date
                    payload["holding_days"] = (exit_date - anchor_date).days
                except Exception:
                    pass
            if close_col in row and not pd.isna(row.get(close_col)):
                payload["exit_price_underlying"] = Decimal(str(float(row[close_col])))
            
            if dry_run:
                action = "UPDATE" if existing else "INSERT"
                print(f"[DRY-RUN] {action}: {event_date} {underlying} {method} -> {outcome_label}")
                if existing:
                    updated += 1
                else:
                    inserted += 1
                continue
            
            if existing:
                for key, value in payload.items():
                    setattr(existing, key, value)
                existing.updated_at = datetime.now(timezone.utc)
                updated += 1
            else:
                outcome = models.OutlierOutcome(
                    outcome_id=uuid.uuid4(),
                    **payload,
                )
                db.add(outcome)
                inserted += 1
        
        if not dry_run:
            db.commit()
    
    return inserted, updated, skipped


def compute_method_stats(
    lookback_days: int,
    as_of_date: date | None = None,
    dry_run: bool = False,
) -> int:
    """
    Compute and store aggregated statistics by method/underlying/sector.
    
    Returns: Number of stats rows upserted
    """
    if as_of_date is None:
        as_of_date = date.today()
    
    cutoff_date = as_of_date - pd.Timedelta(days=lookback_days)
    
    stats_written = 0
    
    with session_scope() as db:
        # Get all outcomes within lookback window
        outcomes = (
            db.query(models.OutlierOutcome)
            .filter(models.OutlierOutcome.event_date >= cutoff_date)
            .filter(models.OutlierOutcome.event_date <= as_of_date)
            .all()
        )
        
        if not outcomes:
            print("No outcomes found in lookback window.")
            return 0
        
        # Convert to DataFrame for easier aggregation
        records = []
        for o in outcomes:
            records.append({
                "method": o.method,
                "underlying_symbol": o.underlying_symbol,
                "sector": o.sector,
                "outcome_label": o.outcome_label.value if o.outcome_label else None,
                "return_5d": float(o.return_5d) if o.return_5d else None,
            })
        df = pd.DataFrame(records)
        
        # Compute stats at different aggregation levels
        aggregations = [
            # Method-only stats (all underlyings, all sectors)
            {"groupby": ["method"], "underlying_symbol": None, "sector": None},
            # Method + underlying stats
            {"groupby": ["method", "underlying_symbol"], "sector": None},
        ]
        
        # Only add sector-level if we have sector data
        if df["sector"].notna().any():
            aggregations.append(
                {"groupby": ["method", "sector"], "underlying_symbol": None}
            )
        
        for agg_config in aggregations:
            groupby_cols = agg_config["groupby"]
            grouped = df.groupby(groupby_cols, dropna=False)

            def _none_if_na(v: Any) -> Any:
                try:
                    if v is None or pd.isna(v):
                        return None
                except Exception:
                    pass
                return v
            
            for group_key, group_df in grouped:
                if not isinstance(group_key, tuple):
                    group_key = (group_key,)
                
                method = group_key[0]
                underlying = None
                sector = None
                
                if len(groupby_cols) == 2:
                    if "underlying_symbol" in groupby_cols:
                        underlying = _none_if_na(group_key[1] if len(group_key) > 1 else None)
                    elif "sector" in groupby_cols:
                        sector = _none_if_na(group_key[1] if len(group_key) > 1 else None)
                
                total = int(len(group_df))
                win_count = int((group_df["outcome_label"] == "WIN").sum())
                loss_count = int((group_df["outcome_label"] == "LOSS").sum())
                neutral_count = int((group_df["outcome_label"] == "NEUTRAL").sum())
                
                returns = group_df["return_5d"].dropna()
                avg_return = returns.mean() if len(returns) > 0 else None
                median_return = returns.median() if len(returns) > 0 else None
                best_return = returns.max() if len(returns) > 0 else None
                worst_return = returns.min() if len(returns) > 0 else None
                
                # Sharpe ratio (assuming daily returns, annualized)
                sharpe = None
                if len(returns) > 1 and returns.std() > 0:
                    sharpe = (returns.mean() / returns.std()) * (252 ** 0.5)  # Annualized
                
                win_rate = win_count / total if total > 0 else None
                
                # Dynamic threshold: if win rate < 50%, recommend higher threshold
                # Simple heuristic: increase threshold proportionally to (0.5 - win_rate)
                recommended_threshold = None
                if win_rate is not None and total >= 10:
                    if win_rate < 0.5:
                        # Current threshold is 3.0 for z-score; recommend increasing
                        base_threshold = 3.0
                        recommended_threshold = base_threshold * (1 + 2 * (0.5 - win_rate))
                    else:
                        # Good performance, keep or lower threshold
                        recommended_threshold = 3.0 * (1 - 0.5 * (win_rate - 0.5))
                
                if dry_run:
                    print(f"[DRY-RUN] STATS: method={method} underlying={underlying} sector={sector}")
                    print(f"          total={total} wins={win_count} losses={loss_count} win_rate={win_rate:.2%}" if win_rate else f"          total={total}")
                    stats_written += 1
                    continue
                
                # Upsert stats
                existing = (
                    db.query(models.OutlierMethodStats)
                    .filter(
                        models.OutlierMethodStats.method == method,
                        models.OutlierMethodStats.underlying_symbol == underlying,
                        models.OutlierMethodStats.sector == sector,
                        models.OutlierMethodStats.lookback_days == lookback_days,
                    )
                    .first()
                )
                
                payload = {
                    "method": method,
                    "underlying_symbol": underlying,
                    "sector": sector,
                    "lookback_days": lookback_days,
                    "total_signals": total,
                    "win_count": win_count,
                    "loss_count": loss_count,
                    "neutral_count": neutral_count,
                    "win_rate": Decimal(str(win_rate)) if win_rate is not None else None,
                    "avg_return": Decimal(str(avg_return)) if avg_return is not None else None,
                    "median_return": Decimal(str(median_return)) if median_return is not None else None,
                    "sharpe_ratio": Decimal(str(sharpe)) if sharpe is not None else None,
                    "best_return": Decimal(str(best_return)) if best_return is not None else None,
                    "worst_return": Decimal(str(worst_return)) if worst_return is not None else None,
                    "recommended_score_threshold": Decimal(str(recommended_threshold)) if recommended_threshold is not None else None,
                    "as_of_date": as_of_date,
                    "computed_at": datetime.now(timezone.utc),
                }
                
                if existing:
                    for key, value in payload.items():
                        setattr(existing, key, value)
                else:
                    stats = models.OutlierMethodStats(
                        stats_id=uuid.uuid4(),
                        **payload,
                    )
                    db.add(stats)
                
                stats_written += 1
        
        if not dry_run:
            db.commit()
    
    return stats_written


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill outlier outcomes and compute statistics")
    parser.add_argument(
        "--events-csv",
        type=str,
        default=None,
        help="Path to outlier_events.csv",
    )
    parser.add_argument("--win-threshold", type=float, default=0.05, help="Win threshold (default: 0.05 = 5%%)")
    parser.add_argument("--loss-threshold", type=float, default=-0.05, help="Loss threshold (default: -0.05 = -5%%)")
    parser.add_argument("--horizon", type=int, default=5, help="Trading days horizon (default: 5)")
    parser.add_argument("--lookback-days", type=int, default=90, help="Days for stats computation (default: 90)")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to database")
    args = parser.parse_args()
    
    # Default CSV path
    if args.events_csv:
        events_path = Path(args.events_csv)
    else:
        events_path = Path(__file__).resolve().parents[1] / "tmp" / "outlier_events.csv"
    
    if not events_path.exists():
        print(f"Error: Events CSV not found: {events_path}")
        print("Run outlier_performance_report.py first to generate the events CSV.")
        return 1
    
    print(f"Loading events from: {events_path}")
    df = load_events_csv(events_path)
    print(f"Loaded {len(df)} events")
    
    print(f"\nBackfilling outcomes (horizon={args.horizon}d, win>={args.win_threshold:.1%}, loss<={args.loss_threshold:.1%})...")
    inserted, updated, skipped = backfill_outcomes(
        df,
        win_threshold=args.win_threshold,
        loss_threshold=args.loss_threshold,
        horizon=args.horizon,
        dry_run=args.dry_run,
    )
    print(f"Outcomes: {inserted} inserted, {updated} updated, {skipped} skipped")
    
    print(f"\nComputing method statistics (lookback={args.lookback_days}d)...")
    stats_count = compute_method_stats(
        lookback_days=args.lookback_days,
        dry_run=args.dry_run,
    )
    print(f"Stats: {stats_count} rows written")
    
    # Print summary
    if not args.dry_run:
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        with session_scope() as db:
            total_outcomes = db.query(models.OutlierOutcome).count()
            win_outcomes = db.query(models.OutlierOutcome).filter(
                models.OutlierOutcome.outcome_label == models.OutlierOutcomeLabel.WIN
            ).count()
            loss_outcomes = db.query(models.OutlierOutcome).filter(
                models.OutlierOutcome.outcome_label == models.OutlierOutcomeLabel.LOSS
            ).count()
            
            print(f"Total outcomes in DB: {total_outcomes}")
            print(f"  WIN:     {win_outcomes} ({win_outcomes/total_outcomes:.1%})" if total_outcomes else "  WIN: 0")
            print(f"  LOSS:    {loss_outcomes} ({loss_outcomes/total_outcomes:.1%})" if total_outcomes else "  LOSS: 0")
            print(f"  NEUTRAL: {total_outcomes - win_outcomes - loss_outcomes}")
            
            print("\nMethod Stats:")
            stats = (
                db.query(models.OutlierMethodStats)
                .filter(models.OutlierMethodStats.underlying_symbol.is_(None))
                .filter(models.OutlierMethodStats.sector.is_(None))
                .all()
            )
            for s in stats:
                wr = f"{float(s.win_rate):.1%}" if s.win_rate else "N/A"
                rec = f"{float(s.recommended_score_threshold):.2f}" if s.recommended_score_threshold else "N/A"
                print(f"  {s.method}: {s.total_signals} signals, {wr} win rate, recommended threshold: {rec}")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
