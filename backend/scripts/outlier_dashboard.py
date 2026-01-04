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

import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Iterable

import pandas as pd
import plotly.express as px
import streamlit as st


def _repo_backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


_FILE_RE = re.compile(r"^(?P<prefix>chain-oi-changes|dp-eod-report|hot-chains|stock-screener)-(?P<date>\d{4}-\d{2}-\d{2})\.csv$")


def _require_db_url() -> str | None:
    return os.environ.get("UW_DATABASE_URL")


def _latest_session_date_from_db() -> date | None:
    try:
        from sqlalchemy import func

        from app.db import models
        from app.db.engine import session_scope
    except Exception:
        return None

    with session_scope() as db:
        return db.query(func.max(models.Session.date)).scalar()


def _session_date_range_from_db() -> tuple[date | None, date | None]:
    try:
        from sqlalchemy import func

        from app.db import models
        from app.db.engine import session_scope
    except Exception:
        return None, None

    with session_scope() as db:
        dmin = db.query(func.min(models.Session.date)).scalar()
        dmax = db.query(func.max(models.Session.date)).scalar()
        return dmin, dmax


def _events_contain_date(df: pd.DataFrame, d: date) -> bool:
    if df.empty or "event_date" not in df.columns:
        return False
    return bool((df["event_date"] == d).any())


def _run_outlier_report_for_range(*, start: date, end: date, baseline_days: int, top_n: int) -> tuple[int, str]:
    db_url = _require_db_url()
    if not db_url:
        return 2, "UW_DATABASE_URL is not set; cannot recompute reports."

    root = _repo_backend_root()
    script = root / "scripts" / "outlier_performance_report.py"
    cmd = [
        sys.executable,
        "-u",
        str(script),
        "--baseline-days",
        str(int(baseline_days)),
        "--top-n",
        str(int(top_n)),
        "--start-date",
        start.isoformat(),
        "--end-date",
        end.isoformat(),
    ]
    env = dict(os.environ)
    env["UW_DATABASE_URL"] = db_url

    try:
        p = subprocess.run(cmd, cwd=str(root), env=env, capture_output=True, text=True)
    except Exception as e:
        return 2, f"Failed to run report: {e}"

    out = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return int(p.returncode or 0), out.strip()


def _snip_log(text: str, max_chars: int = 8000) -> str:
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return "…\n" + text[-max_chars:]


def _import_uploaded_csvs_to_db(*, files: Iterable[st.runtime.uploaded_file_manager.UploadedFile], target_date: str) -> tuple[str, str]:
    """Import uploaded CSVs into Postgres as RawFile records.

    Returns (session_id, log).
    """
    db_url = _require_db_url()
    if not db_url:
        raise RuntimeError("UW_DATABASE_URL is not set")

    from app.api import routes
    from app.db import models
    from app.db.engine import session_scope
    from app.utils.hashing import sha256_file

    # Map filename prefixes to RawSource
    prefix_to_source: dict[str, models.RawSource] = {
        "chain-oi-changes": models.RawSource.OI_DIFF,
        "dp-eod-report": models.RawSource.DARKPOOL_EOD,
        "hot-chains": models.RawSource.HOT_CHAINS,
        "stock-screener": models.RawSource.STOCK_SCREENER,
    }

    root = _repo_backend_root()
    upload_dir = root / "tmp" / "uploaded" / target_date
    upload_dir.mkdir(parents=True, exist_ok=True)

    saved: list[tuple[models.RawSource, Path]] = []
    skipped: list[str] = []

    for f in files:
        name = str(getattr(f, "name", "") or "")
        m = _FILE_RE.match(name)
        if not m:
            skipped.append(f"skip {name}: unexpected filename")
            continue

        date_str = m.group("date")
        if date_str != target_date:
            skipped.append(f"skip {name}: date {date_str} != target {target_date}")
            continue

        source = prefix_to_source[m.group("prefix")]
        path = upload_dir / name
        path.write_bytes(f.getvalue())
        saved.append((source, path))

    if not saved:
        raise RuntimeError("No valid files to import. Expect filenames like chain-oi-changes-YYYY-MM-DD.csv")

    log_lines: list[str] = []
    with session_scope() as db:
        resp = routes.ensure_session(session_date=target_date, strategy_mode=models.StrategyMode.INDEX_EOD, db=db)
        session_id = resp["session_id"]
        log_lines.append(f"session_id={session_id}")

        imported = 0
        deduped = 0
        for source, path in sorted(saved, key=lambda t: t[0].value):
            checksum = sha256_file(path)
            exists = (
                db.query(models.RawFile.file_id)
                .filter(
                    models.RawFile.session_id == session_id,
                    models.RawFile.source == source,
                    models.RawFile.sha256 == checksum,
                )
                .first()
            )
            if exists:
                deduped += 1
                log_lines.append(f"dedupe {source.value}: {path.name}")
                continue

            parsed = routes._dispatch_parser(source, path)
            raw_file = models.RawFile(
                session_id=session_id,
                source=source,
                filename=path.name,
                sha256=checksum,
                rows=len(parsed.rows),
                extras={"headers": parsed.headers, "rows": parsed.rows},
                parse_status=models.ParseStatus.OK if not parsed.errors else models.ParseStatus.ERROR,
                error_message=";".join(parsed.errors) if parsed.errors else None,
            )
            db.add(raw_file)
            db.add(
                models.LogMessage(
                    session_id=session_id,
                    level=models.LogLevel.INFO,
                    message=f"Imported {path.name}",
                    context={"source": source.value, "rows": len(parsed.rows)},
                )
            )
            db.commit()
            imported += 1
            log_lines.append(f"imported {source.value}: {path.name} rows={len(parsed.rows)}")

    if skipped:
        log_lines.append("\n".join(skipped))
    log_lines.append(f"imported={imported} deduped={deduped}")
    return session_id, "\n".join(log_lines)


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

        st.subheader("Latest")
        auto_latest = st.checkbox("Auto-analyze latest date", value=True)
        baseline_days = st.number_input("Baseline days", value=0, min_value=0, step=1)
        top_n = st.number_input("Top N per method", value=10, min_value=1, step=1)

        if source == "CSV outputs":
            events_path = st.text_input("Events CSV", value=default_events)
            summary_path = st.text_input("Summary CSV", value=default_summary)
            if st.button("Reload data"):
                _load_events_csv.clear()
                _load_summary_csv.clear()

            # If we have a DB and the latest session isn't reflected in the CSV yet,
            # automatically recompute just the latest day.
            latest_db_date = _latest_session_date_from_db() if auto_latest and _require_db_url() else None

            df = pd.DataFrame()
            try:
                if Path(events_path).exists():
                    df = _load_events_csv(events_path)
            except Exception:
                df = pd.DataFrame()

            if latest_db_date and not _events_contain_date(df, latest_db_date):
                with st.spinner(f"Computing outlier report for latest date {latest_db_date}..."):
                    rc, out = _run_outlier_report_for_range(
                        start=latest_db_date,
                        end=latest_db_date,
                        baseline_days=int(baseline_days),
                        top_n=int(top_n),
                    )
                st.caption("Latest analysis log")
                st.code(out or "(no output)")
                if rc != 0:
                    st.error("Latest analysis failed. Ensure UW_DATABASE_URL is set and the DB is reachable.")
                    return
                _load_events_csv.clear()
                _load_summary_csv.clear()

            try:
                df = _load_events_csv(events_path)
            except Exception as e:
                st.error(f"Failed to load events CSV: {e}")
                st.info("If this is your first run, set UW_DATABASE_URL and enable Auto-analyze latest date.")
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

        st.subheader("Upload & update")
        st.caption("Upload CSVs for a single date (filenames must include YYYY-MM-DD).")
        uploaded = st.file_uploader("Upload daily CSVs", type=["csv"], accept_multiple_files=True)
        inferred_dates = []
        for uf in uploaded or []:
            m = _FILE_RE.match(str(getattr(uf, "name", "") or ""))
            if m:
                inferred_dates.append(m.group("date"))
        inferred_dates = sorted(set(inferred_dates))
        default_target = inferred_dates[-1] if inferred_dates else ""
        target_date = st.text_input("Target date (YYYY-MM-DD)", value=default_target)
        recompute_all = st.checkbox("Recompute full history after import", value=False)
        if st.button("Import uploads + recompute", disabled=not uploaded or not target_date.strip()):
            if not _require_db_url():
                st.error("UW_DATABASE_URL is not set; cannot import uploads.")
            else:
                with st.spinner("Importing uploads into Postgres..."):
                    try:
                        _, import_log = _import_uploaded_csvs_to_db(files=uploaded, target_date=target_date.strip())
                    except Exception as e:
                        st.error(f"Import failed: {e}")
                        return
                st.caption("Import log")
                st.code(import_log)

                try:
                    d = pd.to_datetime(target_date.strip(), errors="raise").date()
                except Exception:
                    st.error("Invalid target date format; expected YYYY-MM-DD")
                    return

                if recompute_all:
                    dmin, dmax = _session_date_range_from_db()
                    if not dmin or not dmax:
                        st.error("Could not determine DB session date range.")
                        return
                    with st.spinner(f"Recomputing outlier report for full history ({dmin} → {dmax})..."):
                        rc, out = _run_outlier_report_for_range(
                            start=dmin,
                            end=dmax,
                            baseline_days=int(baseline_days),
                            top_n=int(top_n),
                        )
                else:
                    with st.spinner(f"Recomputing outlier report for {d}..."):
                        rc, out = _run_outlier_report_for_range(
                            start=d,
                            end=d,
                            baseline_days=int(baseline_days),
                            top_n=int(top_n),
                        )
                st.caption("Recompute log")
                st.code(_snip_log(out) or "(no output)")
                if rc != 0:
                    st.error("Recompute failed. Check log output above.")
                    return
                _load_events_csv.clear()
                _load_summary_csv.clear()
                st.success("Updated. Reloading view...")
                st.rerun()

        st.header("Filters")
        methods = sorted([m for m in df.get("method", pd.Series([], dtype=str)).dropna().unique()])
        symbols = sorted([s for s in df.get("symbol", pd.Series([], dtype=str)).dropna().unique()])

        default_methods = methods
        sel_methods = st.multiselect("Method", methods, default=default_methods)

        symbol_query = st.text_input("Symbol contains", value="")

        if "event_date" in df.columns and df["event_date"].notna().any():
            dmin = df["event_date"].min()
            dmax = df["event_date"].max()
            show_all = st.checkbox("Show all dates", value=False)
            default_range = (dmin, dmax) if show_all else (dmax, dmax)
            date_range = st.date_input("Event date range", value=default_range, min_value=dmin, max_value=dmax)
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
        st.subheader("Scatter (x / y / color / size)")
        numeric_candidates = [c for c in ["score", "oi_diff", "ret_1", "ret_5", "ret_20"] if c in f.columns]
        if numeric_candidates:
            x_col = st.selectbox("X", options=numeric_candidates, index=numeric_candidates.index("score") if "score" in numeric_candidates else 0)
            y_default = ret_col if ret_col in numeric_candidates else numeric_candidates[0]
            y_col = st.selectbox("Y", options=numeric_candidates, index=numeric_candidates.index(y_default))

            color_options = ["method", "symbol"] + numeric_candidates
            color_options = [c for c in color_options if c in f.columns]
            color_col = st.selectbox("Color", options=color_options, index=0)

            size_options = ["abs(oi_diff)", "abs(score)", "none"]
            size_sel = st.selectbox("Size", options=size_options, index=0)

            plot_df = f.dropna(subset=[x_col, y_col]).copy()
            if size_sel == "abs(oi_diff)" and "oi_diff" in plot_df.columns:
                plot_df["_size"] = plot_df["oi_diff"].abs()
                size_col = "_size"
            elif size_sel == "abs(score)" and "score" in plot_df.columns:
                plot_df["_size"] = plot_df["score"].abs()
                size_col = "_size"
            else:
                size_col = None

            fig2d = px.scatter(
                plot_df,
                x=x_col,
                y=y_col,
                color=color_col if color_col else None,
                size=size_col,
                hover_data=[c for c in ["symbol", "method", "event_date", "session_id", "oi_diff", "score"] if c in plot_df.columns],
                opacity=0.75,
            )
            st.plotly_chart(fig2d, use_container_width=True)
        else:
            st.info("No numeric columns available to plot.")

        with st.expander("3D view (optional)", expanded=False):
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
