"""Run outlier detection over loaded sessions and fetch historical prices to evaluate forward performance.

This script expects sessions + OI_DIFF raw_files already in the DB (e.g. loaded from sample_data).

Outputs:
- backend/tmp/outlier_events.csv: per-event per-symbol forward returns
- backend/tmp/outlier_summary.csv: aggregate forward-return stats by method/horizon

Example:
  $env:UW_DATABASE_URL="postgresql+psycopg2://uw_app:uw_password@127.0.0.1:5433/uw_eod"
  C:/Users/mjhen/Github/UWD/.venv/Scripts/python.exe -u scripts/outlier_performance_report.py --baseline-days 20 --top-n 10

Price source:
- Uses Stooq daily CSV (no API key). If a symbol can't be fetched, it is skipped.
"""

from __future__ import annotations

import argparse
import csv
import time
from dataclasses import dataclass
from datetime import date, datetime
from io import StringIO
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import urlopen, Request

import pandas as pd

from app.analysis.outlier_detection import analyze_from_session_data
from app.db import models
from app.db.engine import session_scope


@dataclass(frozen=True)
class OutlierEvent:
    session_id: str
    event_date: date
    method: str
    underlying_symbol: str
    score: float
    oi_diff: float


def _iter_oi_rows(db, session_id: str) -> list[dict[str, Any]]:
    files = (
        db.query(models.RawFile)
        .filter(models.RawFile.session_id == session_id, models.RawFile.source == models.RawSource.OI_DIFF)
        .all()
    )
    rows: list[dict[str, Any]] = []
    for rf in files:
        if rf.extras and "rows" in rf.extras:
            rows.extend(rf.extras["rows"])
    return rows


def _iter_baseline_rows(db, session_date: date, baseline_days: int) -> list[dict[str, Any]]:
    if baseline_days <= 0:
        return []
    start = session_date - pd.Timedelta(days=baseline_days)
    sessions = (
        db.query(models.Session)
        .filter(models.Session.date >= start, models.Session.date < session_date)
        .order_by(models.Session.date.asc())
        .all()
    )
    baseline: list[dict[str, Any]] = []
    for s in sessions:
        baseline.extend(_iter_oi_rows(db, str(s.session_id)))
    return baseline


def _stooq_symbol(sym: str) -> list[str]:
    s = sym.strip().upper()
    if not s or s == "N/A":
        return []

    # Common index symbols that Stooq may not serve directly.
    index_map = {
        "SPX": "^spx",
        "SPXW": "^spx",
        "NDX": "^ndx",
        "RUT": "^rut",
        "VIX": "^vix",
    }
    if s in index_map:
        return [index_map[s]]

    # Try US equity/ETF conventions.
    base = s.lower()
    return [f"{base}.us", base]


def _fetch_stooq_daily(symbol: str) -> pd.DataFrame | None:
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    req = Request(url, headers={"User-Agent": "UWD/1.0"})
    try:
        with urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError):
        return None

    if not raw.strip() or raw.strip().startswith("404"):
        return None

    df = pd.read_csv(StringIO(raw))
    if df.empty or "Date" not in df.columns:
        return None

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"]).sort_values("Date")
    df = df.rename(
        columns={
            "Date": "date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    df["date"] = df["date"].dt.date
    return df[["date", "open", "high", "low", "close", "volume"]]


def _load_price_history_cached(cache_dir: Path, sym: str, throttle_s: float = 0.25) -> pd.DataFrame | None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe = sym.replace("/", "_").replace("\\", "_")
    cache_path = cache_dir / f"{safe}.csv"

    if cache_path.exists():
        try:
            df = pd.read_csv(cache_path)
            df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
            return df.dropna(subset=["date"]).sort_values("date")
        except Exception:
            cache_path.unlink(missing_ok=True)

    df = _fetch_stooq_daily(sym)
    if df is None:
        return None

    df.to_csv(cache_path, index=False)
    time.sleep(throttle_s)
    return df


def _get_close_on_or_next(df: pd.DataFrame, d: date) -> tuple[date, float] | None:
    # Find first trading day >= d
    mask = df["date"] >= d
    if not mask.any():
        return None
    row = df.loc[mask].iloc[0]
    return row["date"], float(row["close"])


def _forward_close(df: pd.DataFrame, anchor_date: date, trading_days_forward: int) -> tuple[date, float] | None:
    idx = df.index[df["date"] == anchor_date]
    if len(idx) == 0:
        return None
    i = int(idx[0]) + trading_days_forward
    if i < 0 or i >= len(df):
        return None
    row = df.iloc[i]
    return row["date"], float(row["close"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-days", type=int, default=20)
    parser.add_argument("--top-n", type=int, default=10, help="Top N results per method per session")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--horizons", default="1,5,20", help="Comma-separated trading-day horizons")
    args = parser.parse_args()

    start = datetime.strptime(args.start_date, "%Y-%m-%d").date() if args.start_date else None
    end = datetime.strptime(args.end_date, "%Y-%m-%d").date() if args.end_date else None
    horizons = [int(x.strip()) for x in args.horizons.split(",") if x.strip()]

    out_dir = Path(__file__).resolve().parents[1] / "tmp"
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = Path(__file__).resolve().parents[1] / ".cache" / "prices"

    events: list[OutlierEvent] = []

    with session_scope() as db:
        sessions_q = db.query(models.Session).order_by(models.Session.date.asc())
        if start:
            sessions_q = sessions_q.filter(models.Session.date >= start)
        if end:
            sessions_q = sessions_q.filter(models.Session.date <= end)

        sessions = sessions_q.all()
        print(f"Sessions in range: {len(sessions)}")

        for s in sessions:
            sid = str(s.session_id)
            # Skip sessions without OI_DIFF
            oi_files = (
                db.query(models.RawFile)
                .filter(models.RawFile.session_id == sid, models.RawFile.source == models.RawSource.OI_DIFF)
                .count()
            )
            if oi_files == 0:
                continue

            oi_rows = _iter_oi_rows(db, sid)
            baseline_rows = _iter_baseline_rows(db, s.date, args.baseline_days)

            print(f"Outliers {s.date} (rows={len(oi_rows)} baseline_rows={len(baseline_rows)})", flush=True)
            res = analyze_from_session_data(
                oi_rows,
                baseline_oi_data=baseline_rows if baseline_rows else None,
            )

            for key, method_name in (("zscore", "Z-Score"), ("iqr", "IQR"), ("preevent", "Pre-Event")):
                block = res.get(key, {})
                rlist = block.get("results", [])
                # Sort by score desc (already mostly), then take top-n
                rlist = sorted(rlist, key=lambda r: float(r.get("score", 0) or 0), reverse=True)[: args.top_n]
                for r in rlist:
                    events.append(
                        OutlierEvent(
                            session_id=sid,
                            event_date=s.date,
                            method=method_name,
                            underlying_symbol=str(r.get("underlying_symbol") or "").strip().upper(),
                            score=float(r.get("score", 0) or 0),
                            oi_diff=float(r.get("oi_diff", 0) or 0),
                        )
                    )

    if not events:
        print("No outlier events found.")
        return 0

    print(f"Total outlier events (top-n per method per session): {len(events)}")

    # Fetch prices and compute forward returns
    prices: dict[str, pd.DataFrame] = {}

    def get_price_df(symbol: str) -> pd.DataFrame | None:
        if symbol in prices:
            return prices[symbol]
        for candidate in _stooq_symbol(symbol):
            df = _load_price_history_cached(cache_dir, candidate)
            if df is not None and not df.empty:
                prices[symbol] = df
                return df
        prices[symbol] = None  # type: ignore[assignment]
        return None

    rows_out: list[dict[str, Any]] = []

    for ev in events:
        sym = ev.underlying_symbol
        if not sym or sym == "UNKNOWN":
            continue
        df = get_price_df(sym)
        if df is None or df.empty:
            continue

        anchor = _get_close_on_or_next(df, ev.event_date)
        if anchor is None:
            continue
        anchor_date, close0 = anchor

        row_base: dict[str, Any] = {
            "event_date": ev.event_date.isoformat(),
            "anchor_date": anchor_date.isoformat(),
            "session_id": ev.session_id,
            "symbol": sym,
            "method": ev.method,
            "score": ev.score,
            "oi_diff": ev.oi_diff,
            "close_0": close0,
        }

        for h in horizons:
            fwd = _forward_close(df, anchor_date, h)
            if fwd is None:
                row_base[f"close_{h}"] = ""
                row_base[f"ret_{h}"] = ""
                continue
            d_h, close_h = fwd
            row_base[f"date_{h}"] = d_h.isoformat()
            row_base[f"close_{h}"] = close_h
            row_base[f"ret_{h}"] = (close_h / close0) - 1.0 if close0 else ""

        rows_out.append(row_base)

    events_csv = out_dir / "outlier_events.csv"
    if rows_out:
        with events_csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=sorted(rows_out[0].keys()))
            w.writeheader()
            w.writerows(rows_out)

    print(f"Wrote {len(rows_out)} rows to {events_csv}")

    # Summary stats
    df_ev = pd.DataFrame(rows_out)
    summary_rows: list[dict[str, Any]] = []
    for method in sorted(df_ev["method"].dropna().unique()):
        df_m = df_ev[df_ev["method"] == method]
        for h in horizons:
            col = f"ret_{h}"
            if col not in df_m.columns:
                continue
            vals = pd.to_numeric(df_m[col], errors="coerce").dropna()
            if vals.empty:
                continue
            summary_rows.append(
                {
                    "method": method,
                    "horizon_trading_days": h,
                    "n": int(vals.shape[0]),
                    "mean": float(vals.mean()),
                    "median": float(vals.median()),
                    "p25": float(vals.quantile(0.25)),
                    "p75": float(vals.quantile(0.75)),
                }
            )

    summary_csv = out_dir / "outlier_summary.csv"
    if summary_rows:
        pd.DataFrame(summary_rows).to_csv(summary_csv, index=False)
        print(f"Wrote summary to {summary_csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
