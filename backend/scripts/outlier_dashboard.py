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
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


def _repo_backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _repo_root() -> Path:
    return _repo_backend_root().parents[0]


_FILE_RE = re.compile(r"^(?P<prefix>chain-oi-changes|bot-eod-report|dp-eod-report|hot-chains|stock-screener)-(?P<date>\d{4}-\d{2}-\d{2})\.csv$")
_OCC_RE = re.compile(r"^(?P<underlying>[A-Z]+)(?P<yymmdd>\d{6})(?P<cp>[CP])(?P<strike>\d{8})$")


def _require_db_url() -> str | None:
    return os.environ.get("UW_DATABASE_URL")


def _run_sample_data_sync(*, sample_data_dir: str, start_date: date | None = None, end_date: date | None = None) -> tuple[int, str]:
    """Scan sample_data folder and import any new/updated files into Postgres.

    Uses scripts/load_all_sample_data_to_db.py which de-dupes by sha256.
    """
    db_url = _require_db_url()
    if not db_url:
        return 2, "UW_DATABASE_URL is not set; cannot import sample_data into DB."

    root = _repo_backend_root()
    script = root / "scripts" / "load_all_sample_data_to_db.py"
    cmd = [sys.executable, "-u", str(script), "--sample-data-dir", str(sample_data_dir)]
    if start_date:
        cmd += ["--start-date", start_date.isoformat()]
    if end_date:
        cmd += ["--end-date", end_date.isoformat()]

    env = dict(os.environ)
    env["UW_DATABASE_URL"] = db_url

    try:
        p = subprocess.run(cmd, cwd=str(root), env=env, capture_output=True, text=True)
    except Exception as e:
        return 2, f"Failed to run sample_data sync: {e}"

    out = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return int(p.returncode or 0), out.strip()


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


def _show_method_performance_stats() -> None:
    """Display method performance statistics from the database."""
    db_url = _require_db_url()
    if not db_url:
        st.info("Database not connected. Connect to view historical performance stats.")
        return
    
    try:
        from app.db.engine import session_scope
        from app.db import models
        from app.analysis.success_rate import get_performance_summary, get_all_method_performances
    except ImportError as e:
        st.warning(f"Could not import success_rate module: {e}")
        return
    
    try:
        with session_scope() as db:
            # Check if we have any outcomes
            outcome_count = db.query(models.OutlierOutcome).count()
            if outcome_count == 0:
                st.info(
                    "No outcome data available yet. Run `backfill_outlier_outcomes.py` to populate historical outcomes."
                )
                return
            
            summary = get_performance_summary(db, lookback_days=90)
            
            # Overall stats
            overall = summary.get("_overall", {})
            st.markdown(f"**Overall Performance (90-day lookback): {overall.get('total_signals', 0)} signals**")
            
            if overall.get("win_rate") is not None:
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Signals", overall.get("total_signals", 0))
                col2.metric("Win Count", overall.get("win_count", 0))
                col3.metric("Win Rate", f"{overall['win_rate']:.1%}" if overall.get("win_rate") else "N/A")
            
            st.markdown("---")
            st.markdown("**Performance by Method**")
            
            # Method-level stats table
            method_rows = []
            for method in ["Z-Score", "IQR", "Pre-Event"]:
                m = summary.get(method, {})
                if m.get("total_signals", 0) > 0:
                    method_rows.append({
                        "Method": method,
                        "Signals": m.get("total_signals", 0),
                        "Wins": m.get("win_count", 0),
                        "Losses": m.get("loss_count", 0),
                        "Win Rate": f"{m['win_rate']:.1%}" if m.get("win_rate") else "N/A",
                        "Avg Return": f"{m['avg_return']:.2%}" if m.get("avg_return") else "N/A",
                        "Sharpe": f"{m['sharpe_ratio']:.2f}" if m.get("sharpe_ratio") else "N/A",
                        "Rec. Threshold": f"{m['recommended_threshold']:.2f}" if m.get("recommended_threshold") else "—",
                        "Confidence": m.get("confidence_level", "N/A"),
                    })
            
            if method_rows:
                st.dataframe(pd.DataFrame(method_rows), use_container_width=True, hide_index=True)
            else:
                st.info("No method-level statistics available.")
            
            # Top/Bottom performing underlyings
            perfs = get_all_method_performances(db, lookback_days=90)
            underlying_perfs = [p for p in perfs if p.underlying_symbol and p.total_signals >= 5]
            
            if underlying_perfs:
                st.markdown("---")
                col_top, col_bot = st.columns(2)
                
                with col_top:
                    st.markdown("**🏆 Top 5 Underlyings (by win rate)**")
                    top_perfs = sorted(
                        [p for p in underlying_perfs if p.win_rate is not None],
                        key=lambda p: p.win_rate or 0,
                        reverse=True,
                    )[:5]
                    if top_perfs:
                        top_rows = [{
                            "Symbol": p.underlying_symbol,
                            "Method": p.method,
                            "Signals": p.total_signals,
                            "Win Rate": f"{p.win_rate:.0%}" if p.win_rate else "N/A",
                        } for p in top_perfs]
                        st.dataframe(pd.DataFrame(top_rows), use_container_width=True, hide_index=True)
                
                with col_bot:
                    st.markdown("**⚠️ Bottom 5 Underlyings (by win rate)**")
                    bot_perfs = sorted(
                        [p for p in underlying_perfs if p.win_rate is not None],
                        key=lambda p: p.win_rate or 0,
                    )[:5]
                    if bot_perfs:
                        bot_rows = [{
                            "Symbol": p.underlying_symbol,
                            "Method": p.method,
                            "Signals": p.total_signals,
                            "Win Rate": f"{p.win_rate:.0%}" if p.win_rate else "N/A",
                        } for p in bot_perfs]
                        st.dataframe(pd.DataFrame(bot_rows), use_container_width=True, hide_index=True)
    
    except Exception as e:
        st.error(f"Error loading performance stats: {e}")


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
        "bot-eod-report": models.RawSource.BOT_EOD,
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

    # Backwards/forwards compatibility: normalize key column names.
    if "underlying_symbol" not in df.columns and "symbol" in df.columns:
        df = df.rename(columns={"symbol": "underlying_symbol"})

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

    if "underlying_symbol" in df.columns:
        df["underlying_symbol"] = df["underlying_symbol"].astype(str).str.upper().str.strip()
    if "option_symbol" in df.columns:
        df["option_symbol"] = df["option_symbol"].astype(str).str.upper().str.strip()
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
    if "underlying_symbol" not in df.columns and "symbol" in df.columns:
        df = df.rename(columns={"symbol": "underlying_symbol"})
    if "underlying_symbol" in df.columns:
        df["underlying_symbol"] = df["underlying_symbol"].astype(str).str.upper().str.strip()
    if "option_symbol" in df.columns:
        df["option_symbol"] = df["option_symbol"].astype(str).str.upper().str.strip()
    if "method" in df.columns:
        df["method"] = df["method"].astype(str).str.strip()
    return df


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs_price(*, S: float, K: float, T: float, sigma: float, option_type: str, r: float = 0.0) -> float:
    """Black-Scholes price (European), no dividends.

    Uses math.erf for N(x) to avoid SciPy.
    """
    if S <= 0 or K <= 0:
        return 0.0
    if T <= 0 or sigma <= 0:
        if option_type.upper().startswith("C"):
            return max(S - K, 0.0)
        return max(K - S, 0.0)

    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT

    if option_type.upper().startswith("C"):
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def _parse_occ_option_symbol(sym: str) -> tuple[date | None, str | None, float | None]:
    """Parse OCC-style symbol like IBIT251219P00043000."""
    m = _OCC_RE.match((sym or "").strip().upper())
    if not m:
        return None, None, None
    yymmdd = m.group("yymmdd")
    cp = m.group("cp")
    strike_raw = m.group("strike")

    try:
        exp = datetime.strptime(yymmdd, "%y%m%d").date()
    except Exception:
        exp = None

    opt_type = "CALL" if cp == "C" else "PUT"
    try:
        strike = int(strike_raw) / 1000.0
    except Exception:
        strike = None
    return exp, opt_type, strike


def _stooq_candidates(sym: str) -> list[str]:
    s = (sym or "").strip().upper()
    if not s or s == "N/A":
        return []
    index_map = {"SPX": "^spx", "SPXW": "^spx", "NDX": "^ndx", "RUT": "^rut", "VIX": "^vix"}
    if s in index_map:
        return [index_map[s]]
    base = s.lower()
    return [f"{base}.us", base]


@st.cache_data(show_spinner=False)
def _load_cached_price_df(symbol: str) -> pd.DataFrame | None:
    root = _repo_backend_root()
    cache_dir = root / ".cache" / "prices"
    for candidate in _stooq_candidates(symbol):
        safe = candidate.replace("/", "_").replace("\\", "_")
        cache_path = cache_dir / f"{safe}.csv"
        if not cache_path.exists():
            continue
        try:
            df = pd.read_csv(cache_path)
            df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
            df = df.dropna(subset=["date"]).sort_values("date")
            return df
        except Exception:
            continue
    return None


@st.cache_data(show_spinner=False)
def _realized_vol_annual(symbol: str, asof: date, lookback_trading_days: int = 20) -> float | None:
    df = _load_cached_price_df(symbol)
    if df is None or df.empty or "date" not in df.columns or "close" not in df.columns:
        return None
    df2 = df[df["date"] <= asof]
    if df2.empty:
        return None
    closes = pd.to_numeric(df2["close"], errors="coerce").dropna().astype(float).values
    if closes.size < lookback_trading_days + 1:
        return None
    closes = closes[-(lookback_trading_days + 1) :]
    rets = (pd.Series(closes).pct_change()).dropna().astype(float).values
    if rets.size < 2:
        return None
    vol_daily = float(pd.Series(rets).std(ddof=0))
    vol_annual = vol_daily * math.sqrt(252.0)
    # Clamp to keep BS stable.
    return float(max(0.05, min(2.0, vol_annual)))


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
    repo_root = _repo_root()
    default_events = str(root / "tmp" / "outlier_events.csv")
    default_summary = str(root / "tmp" / "outlier_summary.csv")
    default_sample_data_dir = str(repo_root / "sample_data")

    # Sidebar state defaults
    if "_uwd_recompute_full_history_after_sync" not in st.session_state:
        st.session_state["_uwd_recompute_full_history_after_sync"] = True
    if "_uwd_sync_only_latest" not in st.session_state:
        st.session_state["_uwd_sync_only_latest"] = False

    def _on_change_recompute_full_history_after_sync() -> None:
        if st.session_state.get("_uwd_recompute_full_history_after_sync"):
            # Full-history recompute implies we should ingest all dates, not just latest.
            st.session_state["_uwd_sync_only_latest"] = False

    with st.sidebar:
        st.header("Ingest")
        sample_data_dir = st.text_input("sample_data directory", value=default_sample_data_dir)
        sync_on_startup = st.checkbox("Sync sample_data on startup", value=True)
        sync_only_latest = st.checkbox("Sync only latest date", key="_uwd_sync_only_latest")

        st.subheader("Recompute")
        baseline_days = st.number_input("Baseline days", value=0, min_value=0, step=1)
        top_n = st.number_input("Top N per method", value=10, min_value=1, step=1)
        recompute_full_history_after_sync = st.checkbox(
            "Recompute full history after sync",
            key="_uwd_recompute_full_history_after_sync",
            on_change=_on_change_recompute_full_history_after_sync,
        )

        if st.button("Refresh: sync sample_data + recompute"):
            if not _require_db_url():
                st.error("UW_DATABASE_URL is not set; cannot sync.")
                st.stop()
            with st.spinner("Syncing sample_data into Postgres..."):
                if sync_only_latest:
                    latest_db_date = _latest_session_date_from_db()
                    # If DB has no sessions yet, do a full sync.
                    rc, out = _run_sample_data_sync(
                        sample_data_dir=sample_data_dir,
                        start_date=latest_db_date,
                        end_date=None,
                    )
                else:
                    rc, out = _run_sample_data_sync(sample_data_dir=sample_data_dir)
            st.caption("Sync log")
            st.code(_snip_log(out) or "(no output)")
            if rc != 0:
                st.error("Sync failed. Check log above.")
                st.stop()

            # After sync, recompute full history (default) or latest day.
            dmin, dmax = _session_date_range_from_db()
            latest_db_date = dmax
            if recompute_full_history_after_sync and dmin and dmax:
                with st.spinner(f"Recomputing outlier report for full history ({dmin} → {dmax})..."):
                    rc2, out2 = _run_outlier_report_for_range(
                        start=dmin,
                        end=dmax,
                        baseline_days=int(baseline_days),
                        top_n=int(top_n),
                    )
                st.caption("Recompute log")
                st.code(_snip_log(out2) or "(no output)")
                if rc2 != 0:
                    st.error("Recompute failed. Check log above.")
                    st.stop()
            elif latest_db_date:
                with st.spinner(f"Recomputing outlier report for latest date {latest_db_date}..."):
                    rc2, out2 = _run_outlier_report_for_range(
                        start=latest_db_date,
                        end=latest_db_date,
                        baseline_days=int(baseline_days),
                        top_n=int(top_n),
                    )
                st.caption("Recompute log")
                st.code(_snip_log(out2) or "(no output)")
                if rc2 != 0:
                    st.error("Recompute failed. Check log above.")
                    st.stop()
            _load_events_csv.clear()
            _load_summary_csv.clear()
            st.success("Refreshed.")
            st.rerun()

        st.header("Data")
        source = st.radio("Data source", ["CSV outputs", "Postgres tables"], index=0)

        st.subheader("Latest")
        auto_latest = st.checkbox("Auto-analyze latest date", value=True)

        # One-time startup sync.
        if sync_on_startup and _require_db_url() and not st.session_state.get("_uwd_startup_synced"):
            st.session_state["_uwd_startup_synced"] = True
            with st.spinner("Syncing sample_data into Postgres (startup)..."):
                if sync_only_latest:
                    latest_db_date = _latest_session_date_from_db()
                    rc, out = _run_sample_data_sync(
                        sample_data_dir=sample_data_dir,
                        start_date=latest_db_date,
                        end_date=None,
                    )
                else:
                    rc, out = _run_sample_data_sync(sample_data_dir=sample_data_dir)
            st.caption("Startup sync log")
            st.code(_snip_log(out) or "(no output)")
            if rc != 0:
                st.error("Startup sync failed. Check log above.")
                st.stop()

            # Startup recompute (full history by default)
            dmin, dmax = _session_date_range_from_db()
            latest_db_date = dmax
            if recompute_full_history_after_sync and dmin and dmax:
                with st.spinner(f"Recomputing outlier report for full history ({dmin} → {dmax})..."):
                    rc2, out2 = _run_outlier_report_for_range(
                        start=dmin,
                        end=dmax,
                        baseline_days=int(baseline_days),
                        top_n=int(top_n),
                    )
                st.caption("Startup recompute log")
                st.code(_snip_log(out2) or "(no output)")
                if rc2 != 0:
                    st.error("Startup recompute failed. Check log above.")
                    st.stop()
            elif latest_db_date:
                with st.spinner(f"Recomputing outlier report for latest date {latest_db_date}..."):
                    rc2, out2 = _run_outlier_report_for_range(
                        start=latest_db_date,
                        end=latest_db_date,
                        baseline_days=int(baseline_days),
                        top_n=int(top_n),
                    )
                st.caption("Startup recompute log")
                st.code(_snip_log(out2) or "(no output)")
                if rc2 != 0:
                    st.error("Startup recompute failed. Check log above.")
                    st.stop()

            _load_events_csv.clear()
            _load_summary_csv.clear()

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
                st.code(_snip_log(out) or "(no output)")
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
        symbols = sorted([s for s in df.get("underlying_symbol", pd.Series([], dtype=str)).dropna().unique()])

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
        # Back-compat: older CSVs used 'symbol'
        q = symbol_query.strip().upper()
        f = f[f["symbol"].astype(str).str.contains(q, na=False)]
    elif symbol_query.strip() and "underlying_symbol" in f.columns:
        q = symbol_query.strip().upper()
        f = f[f["underlying_symbol"].astype(str).str.contains(q, na=False)]

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
    c2.metric("Unique symbols", int(f["underlying_symbol"].nunique()) if "underlying_symbol" in f.columns else (int(f["symbol"].nunique()) if "symbol" in f.columns else 0))
    c3.metric("Methods", int(f["method"].nunique()) if "method" in f.columns else 0)
    if "event_date" in f.columns and f["event_date"].notna().any():
        c4.metric("Date span", f"{f['event_date'].min()} → {f['event_date'].max()}")

    # Method Performance Section (Phase 2: Feedback Loop)
    with st.expander("📊 Method Performance Stats", expanded=False):
        _show_method_performance_stats()

    # Layout
    left, right = st.columns([2, 1])

    with left:
        st.subheader("Scatter (x / y / color / size)")
        numeric_candidates = [c for c in ["score", "oi_diff", "ret_1", "ret_5", "ret_20"] if c in f.columns]
        if numeric_candidates:
            x_col = st.selectbox("X", options=numeric_candidates, index=numeric_candidates.index("score") if "score" in numeric_candidates else 0)
            y_default = ret_col if ret_col in numeric_candidates else numeric_candidates[0]
            y_col = st.selectbox("Y", options=numeric_candidates, index=numeric_candidates.index(y_default))

            color_options = ["method", "underlying_symbol", "option_symbol"] + numeric_candidates
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
                hover_data=[
                    c
                    for c in [
                        "underlying_symbol",
                        "option_symbol",
                        "method",
                        "event_date",
                        "session_id",
                        "oi_diff",
                        "score",
                    ]
                    if c in plot_df.columns
                ],
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
        st.subheader("Daily top 5 picks")
        st.caption(
            "Option P/L uses actual entry option mid when available; otherwise Black-Scholes. "
            "For P/L tracking, non-0DTE options are exited at least 2 days before expiry."
        )

        picks_per_day = 5
        dedupe_underlying = st.checkbox("One pick per underlying", value=True)

        def _compute_pick_row(row: pd.Series) -> dict[str, Any]:
            def _to_float(v: Any) -> float | None:
                try:
                    if v is None:
                        return None
                    if isinstance(v, str) and not v.strip():
                        return None
                    return float(v)
                except Exception:
                    return None

            def _to_date(v: Any) -> date | None:
                if v is None:
                    return None
                # pandas uses NaT/NaN for missing
                try:
                    if pd.isna(v):
                        return None
                except Exception:
                    pass

                if isinstance(v, str):
                    s = v.strip()
                    if not s:
                        return None
                    try:
                        return datetime.strptime(s, "%Y-%m-%d").date()
                    except Exception:
                        return None

                # datetime is a subclass of date; coerce to date.
                if isinstance(v, datetime):
                    return v.date()
                if isinstance(v, date):
                    return v

                # pandas Timestamp or similar objects with .to_pydatetime()
                to_py = getattr(v, "to_pydatetime", None)
                if callable(to_py):
                    try:
                        py = to_py()
                        if isinstance(py, datetime):
                            return py.date()
                    except Exception:
                        return None
                return None

            underlying = str(row.get("underlying_symbol") or row.get("symbol") or "").strip().upper()
            option_symbol = str(row.get("option_symbol") or "").strip().upper() or None

            entry_date = _to_date(row.get("anchor_date")) or _to_date(row.get("event_date"))
            exit_date = None

            close0 = _to_float(row.get("close_0"))
            close_h = None

            exp, opt_type, occ_strike = _parse_occ_option_symbol(option_symbol or "")
            if opt_type is None:
                # Fallback: infer direction from score sign.
                score = float(row.get("score")) if pd.notna(row.get("score")) else 0.0
                opt_type = "CALL" if score >= 0 else "PUT"
            strike = None
            if pd.notna(row.get("strike")):
                try:
                    strike = float(row.get("strike"))
                except Exception:
                    strike = None
            if strike is None:
                strike = occ_strike
            if strike is None and close0 is not None:
                strike = float(round(close0))

            if exp is None and entry_date:
                exp = entry_date + timedelta(days=30)

            sigma = None
            if entry_date:
                sigma = _realized_vol_annual(underlying, entry_date)
            sigma = sigma if sigma is not None else 0.5

            entry_mid = _to_float(row.get("option_mid_0"))

            theo_entry = None
            theo_exit = None

            if isinstance(exp, datetime):
                exp = exp.date()

            if close0 is not None and strike is not None and entry_date and exp:
                T0 = max((exp - entry_date).days / 365.0, 0.0)
                theo_entry = _bs_price(S=close0, K=float(strike), T=T0, sigma=float(sigma), option_type=opt_type)

            # Exit rule: if not 0DTE, exit at least 2 days prior to expiry.
            if entry_date and exp:
                is_0dte = (exp == entry_date)
                last_allowed_exit = exp if is_0dte else (exp - timedelta(days=2))
                if last_allowed_exit < entry_date:
                    last_allowed_exit = entry_date

                price_df = _load_cached_price_df(underlying)
                if price_df is not None and not price_df.empty:
                    price_df = price_df.sort_values("date")
                    # Anchor to first trading day >= entry_date
                    mask_anchor = price_df["date"] >= entry_date
                    if mask_anchor.any():
                        anchor_idx = int(price_df.index[mask_anchor][0])
                        # Exit at last trading day <= last_allowed_exit
                        mask_exit = price_df["date"] <= last_allowed_exit
                        exit_idx = anchor_idx
                        if mask_exit.any():
                            exit_idx = int(price_df.index[mask_exit][-1])
                        if exit_idx < anchor_idx:
                            exit_idx = anchor_idx

                        exit_trade_date = price_df.loc[exit_idx, "date"]
                        exit_date = _to_date(exit_trade_date)
                        try:
                            close_h = float(price_df.loc[exit_idx, "close"])
                        except Exception:
                            close_h = None

                        if close_h is not None and strike is not None:
                            Tt = max((exp - (exit_date or entry_date)).days / 365.0, 0.0)
                            theo_exit = _bs_price(
                                S=close_h,
                                K=float(strike),
                                T=Tt,
                                sigma=float(sigma),
                                option_type=opt_type,
                            )

            entry_px = entry_mid if (entry_mid is not None and entry_mid > 0) else theo_entry
            exit_px = theo_exit

            pnl = None
            ret_pct = None
            if entry_px is not None and exit_px is not None and entry_px > 0:
                pnl = (exit_px - entry_px) * 100.0
                ret_pct = (exit_px / entry_px) - 1.0

            return {
                "event_date": row.get("event_date"),
                "underlying": underlying,
                "option_symbol": option_symbol or "",
                "type": opt_type,
                "strike": strike or "",
                "exp": exp.isoformat() if exp else "",
                "exit_date": exit_date.isoformat() if exit_date else "",
                "method": row.get("method"),
                "score": row.get("score"),
                "flow_sent": row.get("flow_sentiment"),
                "flow_adj": row.get("flow_adjusted_score"),
                "oi_diff": row.get("oi_diff"),
                "entry_underlying": close0,
                "exit_underlying": close_h,
                "entry_mid_actual": entry_mid,
                "entry_mid_used": entry_px,
                "exit_mid_theo": exit_px,
                "pnl_$": pnl,
                "ret_%": (ret_pct * 100.0) if ret_pct is not None else None,
                "sigma": sigma,
            }

        def _top_picks_for_day(d: date) -> pd.DataFrame:
            day_df = df[df["event_date"] == d].copy()
            if day_df.empty:
                return day_df
            day_df["_rank"] = pd.to_numeric(day_df.get("score"), errors="coerce").abs().fillna(0.0)
            day_df = day_df.sort_values("_rank", ascending=False)
            if dedupe_underlying:
                key_col = "underlying_symbol" if "underlying_symbol" in day_df.columns else "symbol"
                if key_col in day_df.columns:
                    day_df = day_df.drop_duplicates(subset=[key_col], keep="first")
            return day_df.head(picks_per_day)

        if "event_date" not in df.columns or not df["event_date"].notna().any():
            st.info("No event_date column found in data.")
        else:
            # Section 1: latest day table
            latest_day = max(df["event_date"].dropna())
            st.markdown(f"**Latest day picks ({latest_day})**")
            latest_picks_df = _top_picks_for_day(latest_day)
            latest_rows = [_compute_pick_row(r) for _, r in latest_picks_df.iterrows()]
            latest_out = pd.DataFrame(latest_rows)
            if latest_out.empty:
                st.info("No picks available for latest day.")
            else:
                st.dataframe(
                    latest_out[[
                        c
                        for c in [
                            "underlying",
                            "option_symbol",
                            "type",
                            "strike",
                            "exp",
                            "exit_date",
                            "method",
                            "score",
                            "flow_sent",
                            "flow_adj",
                            "oi_diff",
                            "entry_mid_used",
                            "exit_mid_theo",
                            "ret_%",
                            "sigma",
                        ]
                        if c in latest_out.columns
                    ]],
                    use_container_width=True,
                    height=220,
                )

            # Section 2: P/L path for all picks
            st.markdown("**P/L vs days post acquisition (all daily top 5 picks)**")
            pl_metric = st.selectbox("P/L metric", ["Return %", "P/L $ per contract"], index=0)

            all_series_rows: list[dict[str, Any]] = []
            all_picks_rows: list[pd.Series] = []
            for d in sorted(df["event_date"].dropna().unique()):
                all_picks_rows.extend([r for _, r in _top_picks_for_day(d).iterrows()])

            for r in all_picks_rows:
                underlying = str(r.get("underlying_symbol") or r.get("symbol") or "").strip().upper()
                entry_date = r.get("anchor_date") or r.get("event_date")
                try:
                    if pd.isna(entry_date):
                        continue
                except Exception:
                    pass
                if isinstance(entry_date, str):
                    try:
                        entry_date = datetime.strptime(entry_date, "%Y-%m-%d").date()
                    except Exception:
                        continue
                elif isinstance(entry_date, datetime):
                    entry_date = entry_date.date()
                elif isinstance(entry_date, date):
                    entry_date = entry_date
                else:
                    # pandas Timestamp
                    to_py = getattr(entry_date, "to_pydatetime", None)
                    if callable(to_py):
                        try:
                            entry_date = to_py().date()
                        except Exception:
                            continue
                    else:
                        continue

                option_symbol = str(r.get("option_symbol") or "").strip().upper()
                exp, opt_type, occ_strike = _parse_occ_option_symbol(option_symbol)
                if opt_type is None:
                    score = float(r.get("score")) if pd.notna(r.get("score")) else 0.0
                    opt_type = "CALL" if score >= 0 else "PUT"

                strike = None
                if pd.notna(r.get("strike")):
                    try:
                        strike = float(r.get("strike"))
                    except Exception:
                        strike = None
                if strike is None:
                    strike = occ_strike

                close0 = r.get("close_0")
                try:
                    close0 = float(close0) if close0 is not None and not (isinstance(close0, str) and not close0.strip()) else None
                except Exception:
                    close0 = None
                if close0 is None:
                    continue

                if exp is None:
                    exp = entry_date + timedelta(days=30)

                # Exit rule: if not 0DTE, exit at least 2 days prior to expiry.
                is_0dte = (exp == entry_date)
                last_allowed_exit = exp if is_0dte else (exp - timedelta(days=2))
                if last_allowed_exit < entry_date:
                    last_allowed_exit = entry_date

                sigma = _realized_vol_annual(underlying, entry_date) or 0.5
                entry_mid = None
                try:
                    v = r.get("option_mid_0")
                    if v is not None and not (isinstance(v, str) and not v.strip()) and pd.notna(v):
                        entry_mid = float(v)
                except Exception:
                    entry_mid = None

                T0 = max((exp - entry_date).days / 365.0, 0.0)
                theo_entry = _bs_price(S=close0, K=float(strike or round(close0)), T=T0, sigma=float(sigma), option_type=opt_type)
                entry_px = entry_mid if (entry_mid is not None and entry_mid > 0) else theo_entry
                if entry_px is None or entry_px <= 0:
                    continue

                price_df = _load_cached_price_df(underlying)
                if price_df is None or price_df.empty:
                    continue
                # Align to trading calendar: use the first trading day >= entry_date
                price_df = price_df.sort_values("date")
                mask = price_df["date"] >= entry_date
                if not mask.any():
                    continue
                anchor_idx = int(price_df.index[mask][0])
                anchor_trade_date = price_df.loc[price_df.index[mask][0], "date"]
                # If anchor_trade_date is after last_allowed_exit, we can only do day 0
                max_idx = anchor_idx
                # Find last trading day <= last_allowed_exit
                mask_exit = price_df["date"] <= last_allowed_exit
                if mask_exit.any():
                    max_idx = int(price_df.index[mask_exit][-1])

                max_offset = max_idx - anchor_idx
                if max_offset < 0:
                    max_offset = 0

                for off in range(0, max_offset + 1):
                    idx = anchor_idx + off
                    if idx not in price_df.index:
                        continue
                    trade_date = price_df.loc[idx, "date"]
                    try:
                        S_t = float(price_df.loc[idx, "close"])
                    except Exception:
                        continue
                    Tt = max((exp - trade_date).days / 365.0, 0.0)
                    theo_t = _bs_price(S=S_t, K=float(strike or round(close0)), T=Tt, sigma=float(sigma), option_type=opt_type)
                    pnl = (theo_t - entry_px) * 100.0
                    ret_pct = (theo_t / entry_px) - 1.0 if entry_px else None
                    all_series_rows.append(
                        {
                            "days_post": off,
                            "event_date": r.get("event_date"),
                            "underlying": underlying,
                            "option_symbol": option_symbol,
                            "trade_date": trade_date,
                            "pnl_$": pnl,
                            "ret_%": (ret_pct * 100.0) if ret_pct is not None else None,
                        }
                    )

            series_df = pd.DataFrame(all_series_rows)
            if series_df.empty:
                st.info("No P/L paths available (missing cached prices or option fields).")
            else:
                ycol = "ret_%" if pl_metric == "Return %" else "pnl_$"
                agg = (
                    series_df.groupby("days_post")[ycol]
                    .agg(["count", "mean", "median", lambda s: s.quantile(0.25), lambda s: s.quantile(0.75)])
                    .reset_index()
                )
                agg = agg.rename(columns={"<lambda_0>": "p25", "<lambda_1>": "p75"})
                fig = go.Figure()
                fig.add_trace(
                    go.Scatter(
                        x=agg["days_post"],
                        y=agg["p75"],
                        mode="lines",
                        line=dict(width=0),
                        showlegend=False,
                        hoverinfo="skip",
                        name="p75",
                    )
                )
                fig.add_trace(
                    go.Scatter(
                        x=agg["days_post"],
                        y=agg["p25"],
                        mode="lines",
                        line=dict(width=0),
                        fill="tonexty",
                        fillcolor="rgba(100, 149, 237, 0.18)",
                        showlegend=True,
                        name="p25–p75",
                        hoverinfo="skip",
                    )
                )
                fig.add_trace(
                    go.Scatter(
                        x=agg["days_post"],
                        y=agg["median"],
                        mode="lines+markers",
                        line=dict(width=2),
                        name="median",
                        customdata=agg[["count"]],
                        hovertemplate="days=%{x}<br>median=%{y:.2f}<br>n=%{customdata[0]}<extra></extra>",
                    )
                )
                fig.update_layout(
                    xaxis_title="Trading days post acquisition",
                    yaxis_title=("Return %" if ycol == "ret_%" else "P/L $ per contract"),
                    margin=dict(l=0, r=0, t=10, b=0),
                    legend_orientation="h",
                    legend_yanchor="bottom",
                    legend_y=1.02,
                    legend_xanchor="left",
                    legend_x=0,
                )
                st.plotly_chart(fig, use_container_width=True)
                st.caption("Aggregate across all daily top 5 picks: median with p25–p75 band.")

        st.subheader("Top movers")
        if ret_col in f.columns and f[ret_col].notna().any():
            top_pos = f.sort_values(ret_col, ascending=False).head(20)
            top_neg = f.sort_values(ret_col, ascending=True).head(20)

            st.caption(f"Top +{horizon}d returns")
            st.dataframe(
                top_pos[[c for c in ["event_date", "underlying_symbol", "option_symbol", "method", "score", "oi_diff", ret_col] if c in top_pos.columns]],
                use_container_width=True,
                height=280,
            )

            st.caption(f"Top -{horizon}d returns")
            st.dataframe(
                top_neg[[c for c in ["event_date", "underlying_symbol", "option_symbol", "method", "score", "oi_diff", ret_col] if c in top_neg.columns]],
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
