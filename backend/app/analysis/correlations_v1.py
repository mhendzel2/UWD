from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Sequence, cast

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.db import models
from app.ingest import bot_eod
from app.utils.underlying import derive_underlying


@dataclass(frozen=True)
class CorrelationsConfig:
    lookback_sessions: int = 60
    horizons: tuple[int, ...] = (1, 3, 5)
    method: str = "spearman"  # 'spearman' or 'pearson'
    version: str = "v1"


def _parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(v):
        return None
    return v


def _latest_rows_for_source(db: Session, session_id: str, source: models.RawSource) -> list[dict[str, Any]]:
    rf = (
        db.query(models.RawFile)
        .filter(models.RawFile.session_id == session_id, models.RawFile.source == source)
        .order_by(models.RawFile.imported_at.desc())
        .first()
    )
    if not rf:
        return []
    extras = cast(dict[str, Any] | None, getattr(rf, "extras", None))
    if isinstance(extras, dict) and isinstance(extras.get("rows"), list):
        return cast(list[dict[str, Any]], extras["rows"])
    return []


def _all_rows_for_source(db: Session, session_id: str, source: models.RawSource) -> list[dict[str, Any]]:
    rfs = (
        db.query(models.RawFile)
        .filter(models.RawFile.session_id == session_id, models.RawFile.source == source)
        .order_by(models.RawFile.imported_at.desc())
        .all()
    )
    rows: list[dict[str, Any]] = []
    for rf in rfs:
        extras = cast(dict[str, Any] | None, getattr(rf, "extras", None))
        if isinstance(extras, dict) and isinstance(extras.get("rows"), list):
            rows.extend(cast(list[dict[str, Any]], extras["rows"]))
    return rows


def _stock_factor_row(stock_row: dict[str, Any], session_date: date) -> dict[str, Any] | None:
    ticker = (stock_row.get("ticker") or derive_underlying(stock_row) or "").upper()
    if not ticker:
        return None

    close = _parse_float(stock_row.get("close"))
    if close is None or close <= 0:
        return None

    call_volume = _parse_float(stock_row.get("call_volume")) or 0.0
    put_volume = _parse_float(stock_row.get("put_volume")) or 0.0
    call_premium = _parse_float(stock_row.get("call_premium")) or 0.0
    put_premium = _parse_float(stock_row.get("put_premium")) or 0.0

    option_volume = call_volume + put_volume
    option_premium = call_premium + put_premium
    net_premium = call_premium - put_premium
    volume_imbalance = call_volume - put_volume

    marketcap = _parse_float(stock_row.get("marketcap"))
    total_volume = _parse_float(stock_row.get("total_volume"))

    put_call_ratio = _parse_float(stock_row.get("put_call_ratio"))
    call_oi = _parse_float(stock_row.get("call_open_interest"))
    put_oi = _parse_float(stock_row.get("put_open_interest"))

    iv_rank = _parse_float(stock_row.get("iv_rank"))
    iv30d = _parse_float(stock_row.get("iv30d"))
    iv30d_1d = _parse_float(stock_row.get("iv30d_1d"))

    out: dict[str, Any] = {
        "date": session_date,
        "ticker": ticker,
        "close": float(close),
        # STOCK_SCREENER flow
        "ss_call_volume": float(call_volume),
        "ss_put_volume": float(put_volume),
        "ss_option_volume": float(option_volume),
        "ss_volume_imbalance": float(volume_imbalance),
        "ss_call_premium": float(call_premium),
        "ss_put_premium": float(put_premium),
        "ss_option_premium": float(option_premium),
        "ss_net_premium": float(net_premium),
        "ss_put_call_ratio": float(put_call_ratio) if put_call_ratio is not None else None,
        # OI context
        "ss_call_open_interest": float(call_oi) if call_oi is not None else None,
        "ss_put_open_interest": float(put_oi) if put_oi is not None else None,
        # Volatility context
        "ss_iv_rank": float(iv_rank) if iv_rank is not None else None,
        "ss_iv30d": float(iv30d) if iv30d is not None else None,
        "ss_div30d_1d": (float(iv30d) - float(iv30d_1d)) if iv30d is not None and iv30d_1d is not None else None,
        # Normalizers
        "ss_marketcap": float(marketcap) if marketcap is not None else None,
        "ss_total_volume": float(total_volume) if total_volume is not None else None,
    }

    if marketcap and marketcap > 0:
        out["ss_net_premium_mcap"] = net_premium / marketcap
        out["ss_option_premium_mcap"] = option_premium / marketcap
    else:
        out["ss_net_premium_mcap"] = None
        out["ss_option_premium_mcap"] = None

    if close and close > 0:
        out["ss_net_premium_px"] = net_premium / close
        out["ss_volume_imbalance_px"] = volume_imbalance / close
    else:
        out["ss_net_premium_px"] = None
        out["ss_volume_imbalance_px"] = None

    if total_volume and total_volume > 0:
        out["ss_os_volume_ratio"] = option_volume / total_volume
    else:
        out["ss_os_volume_ratio"] = None

    if call_oi is not None and call_oi > 0 and put_oi is not None:
        out["ss_put_call_oi_ratio"] = put_oi / call_oi
    else:
        out["ss_put_call_oi_ratio"] = None

    return out


def _merge_bot_metrics(df: pd.DataFrame, bot_metrics_by_ticker: dict[str, dict[str, float]]) -> pd.DataFrame:
    if df.empty:
        return df

    def _get(ticker: str, key: str) -> float | None:
        m = bot_metrics_by_ticker.get(str(ticker).upper())
        if not m:
            return None
        v = m.get(key)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    df = df.copy()
    df["bot_total_premium"] = df["ticker"].map(lambda t: _get(t, "total_premium"))
    df["bot_bullish_premium"] = df["ticker"].map(lambda t: _get(t, "bullish_premium"))
    df["bot_bearish_premium"] = df["ticker"].map(lambda t: _get(t, "bearish_premium"))
    df["bot_net_bullish_premium"] = df["ticker"].map(lambda t: _get(t, "net_bullish_premium"))
    df["bot_sentiment_score"] = df["ticker"].map(lambda t: _get(t, "sentiment_score"))
    df["bot_ask_count"] = df["ticker"].map(lambda t: _get(t, "ask_count"))
    df["bot_bid_count"] = df["ticker"].map(lambda t: _get(t, "bid_count"))
    df["bot_call_premium"] = df["ticker"].map(lambda t: _get(t, "call_premium"))
    df["bot_put_premium"] = df["ticker"].map(lambda t: _get(t, "put_premium"))

    # Normalizations
    mcap = pd.to_numeric(df["ss_marketcap"], errors="coerce") if "ss_marketcap" in df.columns else np.nan
    df["bot_total_premium_mcap"] = np.where(mcap > 0, df["bot_total_premium"] / mcap, np.nan)
    df["bot_net_bullish_premium_mcap"] = np.where(mcap > 0, df["bot_net_bullish_premium"] / mcap, np.nan)

    return df


def _compute_forward_returns(panel: pd.DataFrame, horizons: Sequence[int]) -> pd.DataFrame:
    if panel.empty:
        return panel

    df = panel.copy()
    df = df.sort_values(["ticker", "date"], ascending=[True, True])
    for h in horizons:
        col = f"fwd_ret_{int(h)}"
        future_close = df.groupby("ticker", dropna=False)["close"].shift(-int(h))
        df[col] = future_close / df["close"] - 1.0
    return df


def _corr(x: pd.Series, y: pd.Series, method: str) -> tuple[float | None, int]:
    xy = pd.concat([x, y], axis=1)
    xy = xy.replace([np.inf, -np.inf], np.nan).dropna()
    if len(xy) < 3:
        return None, int(len(xy))
    try:
        corr_method: str = "spearman" if method == "spearman" else "pearson"
        c = float(xy.iloc[:, 0].corr(xy.iloc[:, 1], method=corr_method))
    except Exception:
        return None, int(len(xy))
    if not np.isfinite(c):
        return None, int(len(xy))
    return c, int(len(xy))


def compute_and_persist_correlations_v1(
    db: Session,
    session: models.Session,
    *,
    lookback_sessions: int = 60,
    horizons: Sequence[int] = (1, 3, 5),
    method: str = "spearman",
) -> dict[str, Any]:
    """Compute factor↔future-return correlations and persist to correlation_runs.

    Uses per-session STOCK_SCREENER rows as the baseline panel (close + marketcap + flow metrics),
    and enriches with BOT_EOD aggregated sentiment metrics.

    Forward returns are computed by shifting closes across sessions per ticker.
    """

    method = (method or "spearman").lower().strip()
    if method not in {"spearman", "pearson"}:
        raise ValueError("method must be 'spearman' or 'pearson'")

    horizons = [int(h) for h in horizons if int(h) > 0]
    if not horizons:
        horizons = [1, 3, 5]

    lookback = max(0, min(int(lookback_sessions), 180))

    sessions = (
        db.query(models.Session)
        .filter(models.Session.date <= session.date)
        .order_by(models.Session.date.desc())
        .limit(lookback)
        .all()
    )
    sessions = list(reversed(sessions))

    rows_out: list[dict[str, Any]] = []
    for sess in sessions:
        sess_id = str(sess.session_id)
        sess_date = cast(date, getattr(sess, "date"))
        srows = _all_rows_for_source(db, sess_id, models.RawSource.STOCK_SCREENER)
        if not srows:
            continue

        bot_rows = _latest_rows_for_source(db, sess_id, models.RawSource.BOT_EOD)
        bot_metrics = bot_eod.aggregate(bot_rows) if bot_rows else {}

        for r in srows:
            row = _stock_factor_row(r, sess_date)
            if not row:
                continue
            rows_out.append({**row, "_bot_metrics": bot_metrics})

    if not rows_out:
        raise ValueError("No STOCK_SCREENER rows available in lookback window")

    panel = pd.DataFrame(rows_out)
    # Ensure python datetime.date keys (avoid numpy scalars breaking dict lookups)
    panel["date"] = pd.to_datetime(panel["date"], errors="coerce").dt.date
    # Extract bot metrics dict once; they were duplicated for each row in a session
    bot_metrics_col = panel.pop("_bot_metrics")

    # Build mapping from date to bot metrics (per session)
    bot_by_date: dict[date, dict[str, dict[str, float]]] = {}
    for d, m in zip(panel["date"], bot_metrics_col, strict=False):
        if d not in bot_by_date and isinstance(m, dict):
            bot_by_date[d] = m

    # Apply bot metrics per date
    merged_frames: list[pd.DataFrame] = []
    for d_raw, day_df in panel.groupby("date", dropna=False, sort=True):
        d_key = cast(date, d_raw)
        bm = bot_by_date.get(d_key, {})
        merged_frames.append(_merge_bot_metrics(day_df, bm))
    panel = pd.concat(merged_frames, ignore_index=True) if merged_frames else panel

    panel = _compute_forward_returns(panel, horizons)

    exclude_prefixes = {"_"}
    base_cols = {"date", "ticker", "close"}
    factor_cols = [
        c
        for c in panel.columns
        if c not in base_cols
        and not any(c.startswith(p) for p in exclude_prefixes)
        and not c.startswith("fwd_ret_")
    ]

    # Correlation results
    results: dict[str, Any] = {
        "version": "v1",
        "method": method,
        "horizons": horizons,
        "computed_at": datetime.utcnow().isoformat() + "Z",
        "lookback_sessions": lookback,
        "session_window": {
            "start": str(sessions[0].date) if sessions else None,
            "end": str(sessions[-1].date) if sessions else None,
            "count": len(sessions),
        },
        "factors": factor_cols,
        "by_horizon": {},
    }

    for h in horizons:
        ret_col = f"fwd_ret_{int(h)}"
        out_h: dict[str, Any] = {}
        for f in factor_cols:
            c, n = _corr(pd.to_numeric(panel[f], errors="coerce"), pd.to_numeric(panel[ret_col], errors="coerce"), method)
            out_h[f] = {"corr": c, "n": n}
        results["by_horizon"][str(int(h))] = out_h

    # Persist (replace) for this session/date/version
    db.query(models.CorrelationRun).filter(
        models.CorrelationRun.session_id == session.session_id,
        models.CorrelationRun.asof_date == session.date,
        models.CorrelationRun.version == "v1",
    ).delete()

    run = models.CorrelationRun(
        session_id=session.session_id,
        asof_date=session.date,
        version="v1",
        computed_at=datetime.utcnow(),
        params={
            "lookback_sessions": lookback,
            "horizons": horizons,
            "method": method,
            "sources": ["STOCK_SCREENER", "BOT_EOD"],
        },
        results=results,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    return {
        "run_id": str(run.run_id),
        "session_id": str(session.session_id),
        "asof_date": str(session.date),
        "version": run.version,
        "params": run.params,
        "results": run.results,
    }
