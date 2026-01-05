from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st


def _first_present(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _add_normalized_columns(
    df: pd.DataFrame,
    *,
    symbol_col: str = "symbol",
    timestamp_col: str = "timestamp",
    lookback: int = 200,
    min_periods: int = 30,
) -> pd.DataFrame:
    """Add optional normalization fields for cross-symbol comparability.

    Preference order:
    - Liquidity-scaled ratios when ADV columns exist
    - Market-cap scaled ratio when market_cap exists
    - Per-symbol rolling z-scores of log(notional) and log(qty)
    - Within-symbol percentile ranks
    """
    if df.empty:
        return df

    out = df.copy()

    notional_col = _first_present(out, ["notional", "order_notional", "trade_notional"])
    qty_col = _first_present(out, ["qty", "quantity", "size", "shares"])
    mcap_col = _first_present(out, ["market_cap", "mkt_cap", "marketcap"])
    adv_notional_col = _first_present(
        out,
        [
            "adv20_notional",
            "adv_20d_notional",
            "adv_notional_20d",
            "adv_notional",
            "notional_adv_20d",
        ],
    )
    adv_qty_col = _first_present(
        out,
        [
            "adv20_qty",
            "adv_20d_qty",
            "adv_qty_20d",
            "adv_qty",
            "adv20_volume",
            "adv_20d_volume",
            "avg_daily_volume_20d",
            "adv_shares_20d",
        ],
    )
    vol_col = _first_present(out, ["sigma_20d", "vol_20d", "daily_vol_20d", "returns_vol_20d"])

    if notional_col and adv_notional_col:
        denom = pd.to_numeric(out[adv_notional_col], errors="coerce")
        num = pd.to_numeric(out[notional_col], errors="coerce")
        out["notional_vs_adv20"] = num / denom.replace(0, np.nan)

    if qty_col and adv_qty_col:
        denom = pd.to_numeric(out[adv_qty_col], errors="coerce")
        num = pd.to_numeric(out[qty_col], errors="coerce")
        out["qty_vs_adv20"] = num / denom.replace(0, np.nan)

    if "notional_vs_adv20" in out.columns and vol_col:
        vol = pd.to_numeric(out[vol_col], errors="coerce")
        out["notional_vs_adv20_x_vol"] = out["notional_vs_adv20"] / vol.replace(0, np.nan)

    if notional_col and mcap_col:
        mc = pd.to_numeric(out[mcap_col], errors="coerce")
        num = pd.to_numeric(out[notional_col], errors="coerce")
        out["notional_pct_mcap"] = num / mc.replace(0, np.nan)

    if symbol_col in out.columns and (notional_col or qty_col):
        out["_row_id__"] = np.arange(len(out), dtype=np.int64)

        if timestamp_col in out.columns:
            work = out.sort_values([symbol_col, timestamp_col, "_row_id__"], kind="mergesort")
        else:
            work = out.sort_values([symbol_col, "_row_id__"], kind="mergesort")

        def _rolling_z(series: pd.Series) -> pd.Series:
            s = pd.to_numeric(series, errors="coerce")
            r = s.rolling(window=int(lookback), min_periods=int(min_periods))
            mu = r.mean()
            sd = r.std(ddof=0)
            return (s - mu) / sd.replace(0, np.nan)

        if notional_col:
            ln = np.log1p(pd.to_numeric(work[notional_col], errors="coerce").clip(lower=0))
            work["z_log_notional"] = ln.groupby(work[symbol_col], sort=False).transform(_rolling_z)
            n = pd.to_numeric(work[notional_col], errors="coerce")
            work["pct_notional_in_symbol"] = n.groupby(work[symbol_col], sort=False).rank(pct=True, method="average")

        if qty_col:
            lq = np.log1p(pd.to_numeric(work[qty_col], errors="coerce").clip(lower=0))
            work["z_log_qty"] = lq.groupby(work[symbol_col], sort=False).transform(_rolling_z)
            q = pd.to_numeric(work[qty_col], errors="coerce")
            work["pct_qty_in_symbol"] = q.groupby(work[symbol_col], sort=False).rank(pct=True, method="average")

        work = work.sort_values("_row_id__", kind="mergesort")
        out = work.drop(columns=["_row_id__"], errors="ignore")

    return out


def run(*, scores_path: str) -> None:
    st.set_page_config(page_title="Trade Surveillance", layout="wide")
    st.title("Unusual Trade Detection")

    p = Path(scores_path)
    if not p.exists():
        alt = None
        # Common Windows/PowerShell pitfall: running generate/featurize/score from `backend/`
        # writes under `backend/backend/tmp/...` instead of `backend/tmp/...`.
        try:
            s = str(p).replace("backend\\tmp\\", "backend\\backend\\tmp\\")
            if s != str(p):
                alt_path = Path(s)
                if alt_path.exists():
                    alt = alt_path
        except Exception:
            alt = None

        st.error(f"scores file not found: {p}")
        st.caption(f"Working directory: {Path.cwd()}")
        st.caption(f"Resolved path: {p.resolve()}")
        if alt is not None:
            st.info(f"Found a likely file here instead: {alt}")
            st.info("Tip: re-run with that path, or run commands from the repo root.")
        st.info("Run: python -m trade_surveillance score --features <features.parquet> --out <scores.parquet>")
        st.stop()

    try:
        df = pd.read_parquet(p)
    except Exception as e:
        st.error(f"Failed to read parquet: {e}")
        st.stop()

    if df.empty:
        st.warning("scores dataset is empty")
        st.stop()

    # Normalize expected columns
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")

    if "ensemble_pct" not in df.columns and "ensemble_score" in df.columns:
        df["ensemble_pct"] = df["ensemble_score"].rank(pct=True, method="average")

    if "ensemble_pct_by_symbol" not in df.columns and "ensemble_score" in df.columns and "symbol" in df.columns:
        df["ensemble_pct_by_symbol"] = df.groupby("symbol")["ensemble_score"].rank(pct=True, method="average")

    if "ensemble_pct" not in df.columns:
        st.error("Missing required column: ensemble_pct")
        st.stop()

    # Minimal UX: high-stringency filter + sortable table.
    left, right = st.columns([2, 3])
    with left:
        st.caption("High-stringency view")
        pct_options = [("Global percentile (ensemble_pct)", "ensemble_pct")]
        if "ensemble_pct_by_symbol" in df.columns:
            pct_options.insert(0, ("Per-symbol percentile (ensemble_pct_by_symbol)", "ensemble_pct_by_symbol"))
        pct_label = st.selectbox("Percentile basis", options=[o[0] for o in pct_options], index=0)
        pct_col = dict(pct_options)[pct_label]

        default_cut = 0.99
        min_pct = st.slider(f"Minimum percentile ({pct_col})", 0.0, 1.0, float(default_cut), 0.005)
        max_rows = st.number_input("Max rows", min_value=50, max_value=5000, value=500, step=50)
        show_all_cols = st.checkbox("Show all columns", value=False)

        st.divider()
        st.caption("Normalization (cross-symbol scale)")
        enable_norm = st.checkbox("Compute normalized size features", value=True)
        lookback = st.number_input("Rolling lookback (rows per symbol)", min_value=50, max_value=5000, value=200, step=50)
        min_periods = st.number_input("Min periods", min_value=10, max_value=500, value=30, step=10)

    if enable_norm:
        df = _add_normalized_columns(df, lookback=int(lookback), min_periods=int(min_periods))

    filtered = df[pd.to_numeric(df.get(pct_col), errors="coerce").fillna(0.0) >= float(min_pct)].copy()
    filtered = filtered.sort_values("ensemble_pct", ascending=False)

    with right:
        st.metric("Rows", int(len(df)))
        st.metric("High-stringency rows", int(len(filtered)))

    if show_all_cols:
        view = filtered
    else:
        preferred = [
            c
            for c in [
                "timestamp",
                "symbol",
                "venue",
                "trader_id",
                "side",
                "price",
                "qty",
                "notional",
                "qty_vs_adv20",
                "notional_vs_adv20",
                "notional_vs_adv20_x_vol",
                "notional_pct_mcap",
                "z_log_qty",
                "z_log_notional",
                "pct_qty_in_symbol",
                "pct_notional_in_symbol",
                pct_col,
                "ensemble_score",
                "score_mcd_mahal",
                "score_isoforest",
                "score_pca_spe",
                "score_pca_t2",
                "score_changepoint",
                "reason",
            ]
            if c in filtered.columns
        ]
        view = filtered[preferred]

    st.subheader("Plots")
    # Minimal plotting to help interpret the outputs.
    # Keep plots driven by existing filter (min_pct) only.
    try:
        plot_df = filtered.copy()
        if "timestamp" in plot_df.columns:
            plot_df = plot_df.dropna(subset=["timestamp"]).sort_values("timestamp")

        c1, c2 = st.columns(2)
        with c1:
            fig = px.histogram(plot_df, x=pct_col, nbins=50, title=f"Percentile distribution ({pct_col})")
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            if "symbol" in plot_df.columns:
                counts = plot_df["symbol"].value_counts().reset_index()
                counts.columns = ["symbol", "count"]
                fig = px.bar(counts, x="symbol", y="count", title="High-stringency counts by symbol")
                st.plotly_chart(fig, use_container_width=True)

        c3, c4 = st.columns(2)
        with c3:
            if "timestamp" in plot_df.columns:
                fig = px.line(
                    plot_df,
                    x="timestamp",
                    y="ensemble_pct",
                    color="symbol" if "symbol" in plot_df.columns else None,
                    title="Ensemble percentile over time",
                )
                st.plotly_chart(fig, use_container_width=True)
        with c4:
            size_candidates = [
                ("Liquidity-scaled notional (notional_vs_adv20)", "notional_vs_adv20"),
                ("Liquidity-scaled qty (qty_vs_adv20)", "qty_vs_adv20"),
                ("Rolling z-score log(notional) (z_log_notional)", "z_log_notional"),
                ("Rolling z-score log(qty) (z_log_qty)", "z_log_qty"),
                ("Raw qty (qty)", "qty"),
                ("Raw notional (notional)", "notional"),
            ]
            available = [(label, col) for (label, col) in size_candidates if col in plot_df.columns]
            if available:
                x_label = st.selectbox("Size axis", options=[a[0] for a in available], index=0)
                x = dict(available)[x_label]
                fig = px.scatter(
                    plot_df,
                    x=x,
                    y=pct_col,
                    color="symbol" if "symbol" in plot_df.columns else None,
                    hover_data=[c for c in ["reason", "venue", "side"] if c in plot_df.columns],
                    title=f"{x_label} vs ensemble percentile",
                )
                st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.warning(f"Plot rendering failed: {e}")

    st.subheader("Rows")
    st.dataframe(view.head(int(max_rows)), width="stretch")
