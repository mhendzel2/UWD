from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st


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

    if "ensemble_pct" not in df.columns:
        st.error("Missing required column: ensemble_pct")
        st.stop()

    # Minimal UX: high-stringency filter + sortable table.
    left, right = st.columns([2, 3])
    with left:
        st.caption("High-stringency view")
        default_cut = 0.99
        min_pct = st.slider("Minimum ensemble percentile", 0.0, 1.0, float(default_cut), 0.005)
        max_rows = st.number_input("Max rows", min_value=50, max_value=5000, value=500, step=50)
        show_all_cols = st.checkbox("Show all columns", value=False)

    filtered = df[df["ensemble_pct"] >= float(min_pct)].copy()
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
                "ensemble_pct",
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

    st.dataframe(view.head(int(max_rows)), use_container_width=True)
