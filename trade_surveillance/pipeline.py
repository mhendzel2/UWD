from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from trade_surveillance.io import read_quotes, read_trades, write_parquet


@dataclass(frozen=True)
class ScoreConfig:
    random_state: int = 7
    # If the dataset is huge, optionally subsample for fitting.
    max_fit_rows: int = 200_000
    pca_components: int = 5


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


def _rolling_z_by_group(s: pd.Series, *, window: int, min_periods: int) -> pd.Series:
    r = s.rolling(window=int(window), min_periods=int(min_periods))
    mu = r.mean()
    sd = r.std(ddof=0)
    sd = sd.replace(0.0, np.nan)
    return (s - mu) / sd


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

    # Cross-symbol comparability: rolling per-symbol z-scores on log sizes + within-symbol percentiles.
    # This is effective even without market-cap/ADV data and helps reduce large-cap vs small-cap bias.
    try:
        window = 200
        min_periods = 30
        f = f.reset_index(drop=False).rename(columns={"index": "__row_id"})
        f = f.sort_values(["symbol", "timestamp", "__row_id"], kind="mergesort")

        if "notional" in f.columns:
            ln = np.log1p(pd.to_numeric(f["notional"], errors="coerce").clip(lower=0.0))
            f["z_log_notional"] = ln.groupby(f["symbol"], sort=False).transform(
                lambda s: _rolling_z_by_group(s, window=window, min_periods=min_periods)
            )
            n = pd.to_numeric(f["notional"], errors="coerce")
            f["pct_notional_in_symbol"] = n.groupby(f["symbol"], sort=False).rank(pct=True, method="average")

            # Rolling liquidity proxies from the trade stream itself.
            # These help reduce cross-ticker biases (share price / cap / volume differences)
            # by expressing size relative to recent activity.
            roll_sum_n = (
                n.groupby(f["symbol"], sort=False)
                .rolling(window=window, min_periods=min_periods)
                .sum()
                .reset_index(level=0, drop=True)
            )
            roll_med_n = (
                n.groupby(f["symbol"], sort=False)
                .rolling(window=window, min_periods=min_periods)
                .median()
                .reset_index(level=0, drop=True)
            )
            denom_sum_n = pd.to_numeric(roll_sum_n, errors="coerce").fillna(0.0) + 1e-9
            denom_med_n = pd.to_numeric(roll_med_n, errors="coerce").fillna(0.0) + 1e-9
            f["notional_participation"] = (pd.to_numeric(n, errors="coerce").fillna(0.0) / denom_sum_n).astype(float)
            f["log_notional_over_roll_median"] = (
                np.log1p(pd.to_numeric(n, errors="coerce").fillna(0.0).clip(lower=0.0))
                - np.log1p(pd.to_numeric(denom_med_n, errors="coerce").fillna(0.0).clip(lower=0.0))
            ).astype(float)
            f["z_log_notional_over_roll_median"] = pd.Series(
                f["log_notional_over_roll_median"], dtype=float
            ).groupby(f["symbol"], sort=False).transform(
                lambda s: _rolling_z_by_group(s, window=window, min_periods=min_periods)
            )

        if "qty" in f.columns:
            lq = np.log1p(pd.to_numeric(f["qty"], errors="coerce").clip(lower=0.0))
            f["z_log_qty"] = lq.groupby(f["symbol"], sort=False).transform(
                lambda s: _rolling_z_by_group(s, window=window, min_periods=min_periods)
            )
            q = pd.to_numeric(f["qty"], errors="coerce")
            f["pct_qty_in_symbol"] = q.groupby(f["symbol"], sort=False).rank(pct=True, method="average")

            roll_sum_q = (
                q.groupby(f["symbol"], sort=False)
                .rolling(window=window, min_periods=min_periods)
                .sum()
                .reset_index(level=0, drop=True)
            )
            roll_med_q = (
                q.groupby(f["symbol"], sort=False)
                .rolling(window=window, min_periods=min_periods)
                .median()
                .reset_index(level=0, drop=True)
            )
            denom_sum_q = pd.to_numeric(roll_sum_q, errors="coerce").fillna(0.0) + 1e-9
            denom_med_q = pd.to_numeric(roll_med_q, errors="coerce").fillna(0.0) + 1e-9
            f["qty_participation"] = (pd.to_numeric(q, errors="coerce").fillna(0.0) / denom_sum_q).astype(float)
            f["log_qty_over_roll_median"] = (
                np.log1p(pd.to_numeric(q, errors="coerce").fillna(0.0).clip(lower=0.0))
                - np.log1p(pd.to_numeric(denom_med_q, errors="coerce").fillna(0.0).clip(lower=0.0))
            ).astype(float)
            f["z_log_qty_over_roll_median"] = pd.Series(f["log_qty_over_roll_median"], dtype=float).groupby(
                f["symbol"], sort=False
            ).transform(lambda s: _rolling_z_by_group(s, window=window, min_periods=min_periods))

        f = f.sort_values("__row_id", kind="mergesort").drop(columns=["__row_id"], errors="ignore")
    except Exception:
        # Keep featurize robust; these columns are optional.
        pass

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
    # Optional cross-symbol normalization fields
    keep_cols.extend([
        "z_log_notional",
        "z_log_qty",
        "pct_notional_in_symbol",
        "pct_qty_in_symbol",
        "notional_participation",
        "qty_participation",
        "log_notional_over_roll_median",
        "log_qty_over_roll_median",
        "z_log_notional_over_roll_median",
        "z_log_qty_over_roll_median",
    ])
    for col in numeric_cols:
        keep_cols.extend([f"{col}_z_svt", f"{col}_z_sv", f"{col}_z_s"])

    keep_cols = [c for c in keep_cols if c in f.columns]
    out_df = f[keep_cols].sort_values("timestamp").reset_index(drop=True)
    write_parquet(out_df, out_path)


def score(*, features_path: str, out_path: str, use_cross_norm: bool = False) -> None:
    from sklearn.covariance import MinCovDet
    from sklearn.decomposition import PCA
    from sklearn.ensemble import IsolationForest

    cfg = ScoreConfig()
    df = pd.read_parquet(features_path)
    if df.empty:
        raise ValueError("features is empty")

    # Select a stable feature set (context-normalized z-scores).
    feature_cols: list[str] = [
        "qty_z_s",
        "notional_z_s",
        "signed_qty_z_s",
        "spread_bps_z_s",
        "price_vs_mid_bps_z_s",
        "effective_spread_bps_z_s",
        "gap_s_symbol_z_s",
    ]

    # Optional: add rolling/percentile normalization features for time-varying context.
    # These are computed in featurize() when possible.
    if bool(use_cross_norm):
        feature_cols.extend(
            [
                "z_log_notional",
                "z_log_qty",
                "pct_notional_in_symbol",
                "pct_qty_in_symbol",
                "notional_participation",
                "qty_participation",
                "z_log_notional_over_roll_median",
                "z_log_qty_over_roll_median",
            ]
        )
    feature_cols = [c for c in feature_cols if c in df.columns]
    if not feature_cols:
        raise ValueError("No usable feature columns found (expected *_z_s columns)")

    X = df[feature_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0).to_numpy(dtype=float)
    n = X.shape[0]

    # Fit set (may subsample for speed).
    fit_idx = np.arange(n)
    if n > int(cfg.max_fit_rows):
        rng = np.random.default_rng(int(cfg.random_state))
        fit_idx = rng.choice(fit_idx, size=int(cfg.max_fit_rows), replace=False)
        fit_idx.sort()

    X_fit = X[fit_idx]

    out = df[[c for c in ["timestamp", "symbol", "venue", "trader_id", "side", "price", "qty", "notional"] if c in df.columns]].copy()

    # 1) Robust Mahalanobis via MCD
    try:
        mcd = MinCovDet(random_state=int(cfg.random_state)).fit(X_fit)
        mah = mcd.mahalanobis(X)
    except Exception:
        # Fallback: use standard covariance if MCD fails
        mu = X_fit.mean(axis=0)
        cov = np.cov(X_fit.T)
        cov += np.eye(cov.shape[0]) * 1e-6
        inv = np.linalg.pinv(cov)
        d = X - mu
        mah = np.einsum("ij,jk,ik->i", d, inv, d)
    out["score_mcd_mahal"] = pd.Series(mah, dtype=float)

    # 2) IsolationForest
    iso = IsolationForest(
        n_estimators=300,
        random_state=int(cfg.random_state),
        n_jobs=-1,
        contamination="auto",
    ).fit(X_fit)
    # decision_function: higher is more normal. Convert to anomaly score.
    out["score_isoforest"] = (-iso.decision_function(X)).astype(float)

    # 3) PCA T^2 and SPE
    k = min(int(cfg.pca_components), X_fit.shape[1])
    if k >= 1:
        pca = PCA(n_components=k, random_state=int(cfg.random_state)).fit(X_fit)
        scores = pca.transform(X)
        recon = pca.inverse_transform(scores)
        resid = X - recon
        spe = np.sum(resid**2, axis=1)
        # T^2 = sum (score_i^2 / eigenvalue_i)
        ev = pca.explained_variance_.astype(float)
        ev = np.where(ev <= 1e-12, 1e-12, ev)
        t2 = np.sum((scores**2) / ev, axis=1)
    else:
        spe = np.zeros(n, dtype=float)
        t2 = np.zeros(n, dtype=float)
    out["score_pca_spe"] = pd.Series(spe, dtype=float)
    out["score_pca_t2"] = pd.Series(t2, dtype=float)

    # 4) Change-point proxy: big deltas in selected z-features within symbol
    if "symbol" in df.columns and "timestamp" in df.columns:
        tmp = df[["symbol", "timestamp"] + feature_cols].copy()
        tmp["timestamp"] = pd.to_datetime(tmp["timestamp"], utc=True, errors="coerce")
        tmp = tmp.dropna(subset=["timestamp"]).sort_values(["symbol", "timestamp"]).reset_index()
        deltas = []
        for c in [c for c in feature_cols if c in tmp.columns]:
            deltas.append(tmp.groupby("symbol")[c].diff().abs().fillna(0.0).to_numpy())
        if deltas:
            cp = np.sum(np.vstack(deltas), axis=0)
        else:
            cp = np.zeros(len(tmp), dtype=float)
        tmp["score_changepoint"] = cp
        # Map back to original row order via the stored original index
        out = out.merge(tmp[["index", "score_changepoint"]], left_index=True, right_on="index", how="left")
        out = out.drop(columns=["index"])  # from merge
        out["score_changepoint"] = pd.to_numeric(out["score_changepoint"], errors="coerce").fillna(0.0)
    else:
        out["score_changepoint"] = 0.0

    score_cols = [c for c in out.columns if c.startswith("score_")]

    # Percentile-normalize each method score for ensembling.
    for c in score_cols:
        out[f"pct_{c}"] = out[c].rank(pct=True, method="average")

    pct_cols = [f"pct_{c}" for c in score_cols]
    out["ensemble_score"] = out[pct_cols].mean(axis=1)
    out["ensemble_pct"] = out["ensemble_score"].rank(pct=True, method="average")

    # Per-symbol calibration for alerting/thresholding.
    # This is the simplest, robust way to remove cross-ticker scale bias when selecting top signals.
    if "symbol" in out.columns:
        out["ensemble_pct_by_symbol"] = out.groupby("symbol")["ensemble_score"].rank(pct=True, method="average")

    # Reason codes: top method(s) + top abs feature z(s)
    # Keep it compact, single string column.
    pct_mat = out[pct_cols].to_numpy(dtype=float)
    top_method_idx = np.argsort(-pct_mat, axis=1)[:, :2]
    method_names = np.array([c.removeprefix("pct_") for c in pct_cols], dtype=object)
    top_methods = ["/".join(method_names[row]) for row in top_method_idx]

    z_cols_for_reason = [c for c in feature_cols if c.endswith("_z_s")]
    Z = df[z_cols_for_reason].apply(pd.to_numeric, errors="coerce").fillna(0.0).to_numpy(dtype=float)
    top_feat_idx = np.argsort(-np.abs(Z), axis=1)[:, :2]
    feat_names = np.array(z_cols_for_reason, dtype=object)
    feat_parts = []
    for i in range(n):
        parts = []
        for j in top_feat_idx[i]:
            name = str(feat_names[j])
            val = float(Z[i, j])
            parts.append(f"{name}={val:.2f}")
        feat_parts.append(",".join(parts))

    out["reason"] = [f"{m}; {fp}" for m, fp in zip(top_methods, feat_parts)]

    write_parquet(out, out_path)
