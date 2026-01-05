from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from trade_surveillance.io import read_quotes, read_trades, write_parquet


@dataclass(frozen=True)
class FeaturizeConfig:
    # Minimum group size for the most granular context normalization.
    min_group_size: int = 50
    # Bin size for intraday time-of-day context normalization.
    tod_bin_minutes: int = 30


def _ensure_trade_fields(df: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "symbol", "price", "qty"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"trades missing required columns: {sorted(missing)}")

    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
    out = out.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    if "side" in out.columns:
        out["side"] = out["side"].astype(str).str.upper()
    else:
        out["side"] = "UNKNOWN"

    if "venue" not in out.columns:
        out["venue"] = "UNKNOWN"
    if "trader_id" not in out.columns:
        out["trader_id"] = "UNKNOWN"

    for col in ["price", "qty"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["price", "qty"])
    return out


def _asof_join_quotes(trades: pd.DataFrame, quotes: pd.DataFrame) -> pd.DataFrame:
    q = quotes.copy()
    q["timestamp"] = pd.to_datetime(q["timestamp"], utc=True, errors="coerce")
    q = q.dropna(subset=["timestamp"]).sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    # pandas.merge_asof requires data sorted by the merge key globally.
    # Doing this per-symbol is simple and avoids subtle ordering violations.
    out_parts: list[pd.DataFrame] = []
    for sym, t_sym in trades.groupby("symbol", sort=False):
        t_sym = t_sym.sort_values("timestamp").reset_index(drop=True)
        q_sym = q[q["symbol"] == sym].sort_values("timestamp").reset_index(drop=True)
        if q_sym.empty:
            out_parts.append(t_sym)
            continue
        merged = pd.merge_asof(
            t_sym,
            q_sym,
            on="timestamp",
            direction="nearest",
            tolerance=pd.Timedelta(seconds=2),
            suffixes=("", "_q"),
        )
        out_parts.append(merged)
    out = pd.concat(out_parts, ignore_index=True)
    return out.sort_values("timestamp").reset_index(drop=True)


def _mad(x: pd.Series) -> float:
    # Median absolute deviation, consistent with median (not scaled to sigma).
    med = float(np.nanmedian(x.to_numpy(dtype=float)))
    return float(np.nanmedian(np.abs(x.to_numpy(dtype=float) - med)))


def _robust_z(x: pd.Series, center: pd.Series, scale: pd.Series) -> pd.Series:
    xv = pd.to_numeric(x, errors="coerce").astype(float)
    cv = pd.to_numeric(center, errors="coerce").astype(float)
    sv = pd.to_numeric(scale, errors="coerce").astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (xv - cv) / sv
    bad = (~np.isfinite(z.to_numpy())) | (~np.isfinite(sv.to_numpy())) | (sv.to_numpy() <= 0)
    if bool(np.any(bad)):
        z = z.to_numpy()
        z[bad] = 0.0
        return pd.Series(z, index=x.index, dtype=float)
    return z


def _context_normalize(
    df: pd.DataFrame,
    numeric_cols: list[str],
    *,
    cfg: FeaturizeConfig,
    group_cols: list[str],
    z_suffix: str,
) -> pd.DataFrame:
    out = df.copy()
    for col in numeric_cols:
        zcol = f"{col}{z_suffix}"
        out[zcol] = np.nan

    # Compute med/MAD per group
    grouped = out.groupby(group_cols, dropna=False, sort=False)
    counts = grouped.size().rename("__n").reset_index()
    stats_rows = []
    for col in numeric_cols:
        med = grouped[col].median().rename(f"__med_{col}")
        mad = grouped[col].apply(_mad).rename(f"__mad_{col}")
        stats_rows.append(med)
        stats_rows.append(mad)
    stats = pd.concat(stats_rows, axis=1).reset_index()
    stats = stats.merge(counts, on=group_cols, how="left")

    out = out.merge(stats, on=group_cols, how="left")

    # Apply only for sufficiently large groups.
    ok = out["__n"].fillna(0).astype(int) >= int(cfg.min_group_size)
    for col in numeric_cols:
        zcol = f"{col}{z_suffix}"
        out.loc[ok, zcol] = _robust_z(out.loc[ok, col], out.loc[ok, f"__med_{col}"], out.loc[ok, f"__mad_{col}"])

    # Cleanup temp columns
    drop_cols = ["__n"]
    for col in numeric_cols:
        drop_cols.extend([f"__med_{col}", f"__mad_{col}"])
    out = out.drop(columns=[c for c in drop_cols if c in out.columns])
    return out


def featurize(*, trades_path: str, quotes_path: str | None, out_path: str) -> None:
    cfg = FeaturizeConfig()

    trades = _ensure_trade_fields(read_trades(trades_path))
    if quotes_path:
        quotes = read_quotes(quotes_path)
        trades = _asof_join_quotes(trades, quotes)

    # Ensure bid/ask exist if present; compute mid.
    if "bid" in trades.columns:
        trades["bid"] = pd.to_numeric(trades["bid"], errors="coerce")
    if "ask" in trades.columns:
        trades["ask"] = pd.to_numeric(trades["ask"], errors="coerce")

    if "mid_price" in trades.columns:
        trades["mid_price"] = pd.to_numeric(trades["mid_price"], errors="coerce")
    else:
        if "bid" in trades.columns and "ask" in trades.columns:
            trades["mid_price"] = (trades["bid"] + trades["ask"]) / 2.0
        else:
            trades["mid_price"] = trades["price"]

    # Core engineered features
    side_sign = trades["side"].map({"BUY": 1.0, "SELL": -1.0}).fillna(0.0)
    trades["signed_qty"] = trades["qty"] * side_sign
    trades["notional"] = trades["price"] * trades["qty"]

    if "bid" in trades.columns and "ask" in trades.columns:
        trades["spread"] = trades["ask"] - trades["bid"]
        trades["spread_bps"] = np.where(
            trades["mid_price"].astype(float) != 0,
            trades["spread"].astype(float) / trades["mid_price"].astype(float) * 10000.0,
            np.nan,
        )
    else:
        trades["spread"] = np.nan
        trades["spread_bps"] = np.nan

    trades["price_vs_mid_bps"] = np.where(
        trades["mid_price"].astype(float) != 0,
        (trades["price"].astype(float) - trades["mid_price"].astype(float)) / trades["mid_price"].astype(float) * 10000.0,
        np.nan,
    )
    trades["effective_spread_bps"] = 2.0 * trades["price_vs_mid_bps"].abs()

    # Time-of-day context
    ts = pd.to_datetime(trades["timestamp"], utc=True)
    trades["tod_seconds"] = ts.dt.hour * 3600 + ts.dt.minute * 60 + ts.dt.second
    bin_s = int(cfg.tod_bin_minutes) * 60
    trades["tod_bin"] = (trades["tod_seconds"] // bin_s).astype(int)

    # Inter-trade gap by symbol (seconds)
    trades["gap_s_symbol"] = (
        trades.sort_values(["symbol", "timestamp"]).groupby("symbol")["timestamp"].diff().dt.total_seconds()
    )

    numeric_cols = [
        "qty",
        "notional",
        "signed_qty",
        "spread_bps",
        "price_vs_mid_bps",
        "effective_spread_bps",
        "gap_s_symbol",
    ]

    # Fill missing numeric with 0 for stable scaling only where it makes sense.
    trades["gap_s_symbol"] = trades["gap_s_symbol"].fillna(trades["gap_s_symbol"].median())

    # Hierarchical context normalization with fallbacks.
    f = trades
    f = _context_normalize(f, numeric_cols, cfg=cfg, group_cols=["symbol", "venue", "tod_bin"], z_suffix="_z_svt")
    # For rows that didn't get svt z-scores (small groups), fill with symbol+venue.
    missing_mask = f["qty_z_svt"].isna()
    if bool(missing_mask.any()):
        f2 = _context_normalize(f.loc[missing_mask].copy(), numeric_cols, cfg=FeaturizeConfig(min_group_size=1), group_cols=["symbol", "venue"], z_suffix="_z_sv")
        for col in numeric_cols:
            f.loc[missing_mask, f"{col}_z_sv"] = f2[f"{col}_z_sv"].to_numpy()
    else:
        for col in numeric_cols:
            f[f"{col}_z_sv"] = f[f"{col}_z_svt"]

    # Final fallback: symbol only
    missing_mask = f["qty_z_sv"].isna()
    if bool(missing_mask.any()):
        f3 = _context_normalize(f.loc[missing_mask].copy(), numeric_cols, cfg=FeaturizeConfig(min_group_size=1), group_cols=["symbol"], z_suffix="_z_s")
        for col in numeric_cols:
            f.loc[missing_mask, f"{col}_z_s"] = f3[f"{col}_z_s"].to_numpy()
    else:
        for col in numeric_cols:
            f[f"{col}_z_s"] = f[f"{col}_z_sv"]

    # If any z columns still NaN, fill with 0.
    for col in numeric_cols:
        for suffix in ["_z_svt", "_z_sv", "_z_s"]:
            zcol = f"{col}{suffix}"
            if zcol in f.columns:
                f[zcol] = pd.to_numeric(f[zcol], errors="coerce").fillna(0.0)

    # Select output columns
    keep_cols = [
        "timestamp",
        "symbol",
        "venue",
        "trader_id",
        "side",
        "price",
        "qty",
        "notional",
        "signed_qty",
        "mid_price",
        "spread_bps",
        "price_vs_mid_bps",
        "effective_spread_bps",
        "gap_s_symbol",
        "tod_seconds",
        "tod_bin",
    ]
    for col in numeric_cols:
        keep_cols.extend([f"{col}_z_svt", f"{col}_z_sv", f"{col}_z_s"])

    keep_cols = [c for c in keep_cols if c in f.columns]
    out_df = f[keep_cols].sort_values("timestamp").reset_index(drop=True)
    write_parquet(out_df, out_path)


def score(*, features_path: str, out_path: str) -> None:
    raise NotImplementedError("Phase 4: detectors + ensemble")
