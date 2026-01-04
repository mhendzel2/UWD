"""Interactive dashboard for outlier performance outputs.

Reads outputs produced by scripts/outlier_performance_report.py:
- backend/tmp/outlier_events.csv
- backend/tmp/outlier_summary.csv

Supports:
- Fast filters (date/method/symbol/score)
- 3D Plotly scatter (score vs oi_diff vs forward return)
- Distributions (histogram / box)
- Top movers tables

Run:
  $env:UW_DATABASE_URL="postgresql+psycopg2://uw_app:uw_password@127.0.0.1:5433/uw_eod"
  C:/Users/mjhen/Github/UWD/.venv/Scripts/python.exe -m streamlit run scripts/outlier_dashboard.py

Optional (DB-backed): load the CSVs to Postgres first via scripts/load_outlier_reports_to_db.py
and then switch the dashboard "Data source" to "Postgres tables".
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st


def _repo_backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _coerce_numeric(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


@st.cache_data(show_spinner=False)
def _load_events_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    # Normalize types
    for c in ["event_date", "anchor_date"]:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce").dt.date

    df = _coerce_numeric(
        df,
        [
            "score",
            "oi_diff",
            "close_0",
            "close_1",
            "close_5",
            "close_20",
            "ret_1",
            "ret_5",
            "ret_20",
        ],
    )

    if "symbol" in df.columns:
        df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
    if "method" in df.columns:
        df["method"] = df["method"].astype(str).str.strip()

    return df


@st.cache_data(show_spinner=False)
def _load_summary_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = _coerce_numeric(df, ["horizon_trading_days", "n", "mean", "median", "p25", "p75"])
    if "method" in df.columns:
        df["method"] = df["method"].astype(str).str.strip()
    return df


@st.cache_data(show_spinner=False)
def _load_events_from_db(table_name: str, schema: str | None = None) -> pd.DataFrame:
    from app.db.engine import engine

    df = pd.read_sql_table(table_name, con=engine, schema=schema)
    # Try to match CSV types
    for c in ["event_date", "anchor_date"]:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce").dt.date
    df = _coerce_numeric(df, ["score", "oi_diff", "ret_1", "ret_5", "ret_20"])
    if "symbol" in df.columns:
        df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
    if "method" in df.columns:
        df["method"] = df["method"].astype(str).str.strip()
    return df


@st.cache_data(show_spinner=False)
def _load_summary_from_db(table_name: str, schema: str | None = None) -> pd.DataFrame:
    from app.db.engine import engine

    df = pd.read_sql_table(table_name, con=engine, schema=schema)
    df = _coerce_numeric(df, ["horizon_trading_days", "n", "mean", "median", "p25", "p75"])
    if "method" in df.columns:
        df["method"] = df["method"].astype(str).str.strip()
    return df


def main() -> None:
    st.set_page_config(page_title="UWD Outlier Performance", layout="wide")

    st.title("UWD – Outlier Performance Dashboard")

    root = _repo_backend_root()
    default_events = str(root / "tmp" / "outlier_events.csv")
    default_summary = str(root / "tmp" / "outlier_summary.csv")

    with st.sidebar:
        st.header("Data")
        source = st.radio("Data source", ["CSV outputs", "Postgres tables"], index=0)

        if source == "CSV outputs":
            events_path = st.text_input("Events CSV", value=default_events)
            summary_path = st.text_input("Summary CSV", value=default_summary)
            if st.button("Reload data"):
                _load_events_csv.clear()
                _load_summary_csv.clear()

            try:
                df = _load_events_csv(events_path)
            except Exception as e:
                st.error(f"Failed to load events CSV: {e}")
                return

            try:
                df_sum = _load_summary_csv(summary_path)
            except Exception:
                df_sum = pd.DataFrame()

        else:
            schema = st.text_input("Schema (optional)", value="")
            schema_val = schema.strip() or None
            events_table = st.text_input("Events table", value="report_outlier_events")
            summary_table = st.text_input("Summary table", value="report_outlier_summary")
            if st.button("Reload data"):
                _load_events_from_db.clear()
                _load_summary_from_db.clear()

            try:
                df = _load_events_from_db(events_table, schema=schema_val)
            except Exception as e:
                st.error(f"Failed to load events table: {e}")
                return

            try:
                df_sum = _load_summary_from_db(summary_table, schema=schema_val)
            except Exception:
                df_sum = pd.DataFrame()

        st.header("Filters")
        methods = sorted([m for m in df.get("method", pd.Series([], dtype=str)).dropna().unique()])
        symbols = sorted([s for s in df.get("symbol", pd.Series([], dtype=str)).dropna().unique()])

        default_methods = methods
        sel_methods = st.multiselect("Method", methods, default=default_methods)

        symbol_query = st.text_input("Symbol contains", value="")

        if "event_date" in df.columns and df["event_date"].notna().any():
            dmin = df["event_date"].min()
            dmax = df["event_date"].max()
            date_range = st.date_input("Event date range", value=(dmin, dmax), min_value=dmin, max_value=dmax)
            if isinstance(date_range, tuple) and len(date_range) == 2:
                start_d, end_d = date_range
            else:
                start_d, end_d = dmin, dmax
        else:
            start_d = end_d = None

        horizon = st.selectbox("Forward return horizon", [1, 5, 20], index=1)
        ret_col = f"ret_{horizon}"

        min_abs_score = st.number_input("Min |score|", value=0.0, min_value=0.0, step=1.0)
        min_abs_oi = st.number_input("Min |oi_diff|", value=0.0, min_value=0.0, step=1000.0)
        require_return = st.checkbox("Only rows with return", value=True)

    # Apply filters
    f = df.copy()
    if sel_methods and "method" in f.columns:
        f = f[f["method"].isin(sel_methods)]

    if symbol_query.strip() and "symbol" in f.columns:
        q = symbol_query.strip().upper()
        f = f[f["symbol"].astype(str).str.contains(q, na=False)]

    if start_d and end_d and "event_date" in f.columns:
        f = f[(f["event_date"] >= start_d) & (f["event_date"] <= end_d)]

    if min_abs_score > 0 and "score" in f.columns:
        f = f[f["score"].abs() >= float(min_abs_score)]

    if min_abs_oi > 0 and "oi_diff" in f.columns:
        f = f[f["oi_diff"].abs() >= float(min_abs_oi)]

    if require_return and ret_col in f.columns:
        f = f[f[ret_col].notna()]

    # KPIs
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rows", f.shape[0])
    c2.metric("Unique symbols", int(f["symbol"].nunique()) if "symbol" in f.columns else 0)
    c3.metric("Methods", int(f["method"].nunique()) if "method" in f.columns else 0)
    if "event_date" in f.columns and f["event_date"].notna().any():
        c4.metric("Date span", f"{f['event_date'].min()} → {f['event_date'].max()}")

    # Layout
    left, right = st.columns([2, 1])

    with left:
        st.subheader("3D: score vs oi_diff vs forward return")
        if all(col in f.columns for col in ["score", "oi_diff", ret_col]):
            plot_df = f.dropna(subset=["score", "oi_diff", ret_col]).copy()
            plot_df["abs_oi"] = plot_df["oi_diff"].abs()
            fig3d = px.scatter_3d(
                plot_df,
                x="score",
                y="oi_diff",
                z=ret_col,
                color="method" if "method" in plot_df.columns else None,
                hover_data=[c for c in ["symbol", "event_date", "session_id"] if c in plot_df.columns],
                size="abs_oi",
                size_max=14,
                opacity=0.75,
            )
            fig3d.update_layout(margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig3d, use_container_width=True)
        else:
            st.info("Missing required columns for 3D plot.")

        st.subheader("Distribution")
        if ret_col in f.columns and f[ret_col].notna().any():
            fig_hist = px.histogram(
                f.dropna(subset=[ret_col]),
                x=ret_col,
                color="method" if "method" in f.columns else None,
                nbins=60,
                barmode="overlay",
                opacity=0.55,
            )
            st.plotly_chart(fig_hist, use_container_width=True)

            if "method" in f.columns:
                fig_box = px.box(f.dropna(subset=[ret_col]), x="method", y=ret_col, points="outliers")
                st.plotly_chart(fig_box, use_container_width=True)

    with right:
        st.subheader("Top movers")
        if ret_col in f.columns and f[ret_col].notna().any():
            top_pos = f.sort_values(ret_col, ascending=False).head(20)
            top_neg = f.sort_values(ret_col, ascending=True).head(20)

            st.caption(f"Top +{horizon}d returns")
            st.dataframe(
                top_pos[[c for c in ["event_date", "symbol", "method", "score", "oi_diff", ret_col] if c in top_pos.columns]],
                use_container_width=True,
                height=280,
            )

            st.caption(f"Top -{horizon}d returns")
            st.dataframe(
                top_neg[[c for c in ["event_date", "symbol", "method", "score", "oi_diff", ret_col] if c in top_neg.columns]],
                use_container_width=True,
                height=280,
            )
        else:
            st.info("No return data available under current filters.")

        if not df_sum.empty:
            st.subheader("Summary stats")
            st.dataframe(df_sum, use_container_width=True, height=260)


if __name__ == "__main__":
    main()
