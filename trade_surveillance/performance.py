from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from pathlib import Path

import numpy as np
import pandas as pd

from trade_surveillance.io import write_parquet
from trade_surveillance.options_pricing import BlackScholesInputs, black_scholes_fair_value


@dataclass(frozen=True)
class PerformanceConfig:
    top_k: int = 5
    lookback_days: int = 5
    forward_days: int = 10
    tz: str = "America/New_York"

    # Option fair-value settings
    option_type: str = "CALL"
    option_dte: int = 30
    option_iv: float = 0.50
    option_rate: float = 0.04
    option_dividend_yield: float = 0.0
    option_strike_round: float = 1.0


def _default_prices_dir() -> Path:
    # Repo root / backend/.cache/prices
    here = Path(__file__).resolve()
    repo = here.parents[1]
    return repo / "backend" / ".cache" / "prices"


def _symbol_price_file(symbol: str) -> str:
    # Matches existing cache naming convention seen in backend/.cache/prices
    return f"{symbol.lower()}.us.csv"


def _read_prices(prices_dir: Path, symbol: str) -> pd.DataFrame | None:
    p = prices_dir / _symbol_price_file(symbol)
    if not p.exists():
        return None

    df = pd.read_csv(p)
    # Expected: date,open,high,low,close,volume
    if "date" not in df.columns or "close" not in df.columns:
        return None

    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    for c in ["open", "high", "low", "close", "volume"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _session_date(ts: pd.Series, tz: str) -> pd.Series:
    t = pd.to_datetime(ts, utc=True, errors="coerce")
    try:
        t = t.dt.tz_convert(tz)
    except Exception:
        # If tz conversion fails, just use UTC date.
        pass
    return t.dt.date


def select_top_k_per_day(scores: pd.DataFrame, *, top_k: int, tz: str) -> pd.DataFrame:
    if scores.empty:
        return scores

    if "timestamp" not in scores.columns:
        raise ValueError("scores must include 'timestamp'")
    if "symbol" not in scores.columns:
        raise ValueError("scores must include 'symbol'")

    if "ensemble_pct" in scores.columns:
        rank_col = "ensemble_pct"
    elif "ensemble_score" in scores.columns:
        rank_col = "ensemble_score"
    else:
        raise ValueError("scores must include 'ensemble_pct' or 'ensemble_score'")

    s = scores.copy()
    s["session_date"] = _session_date(s["timestamp"], tz)
    s[rank_col] = pd.to_numeric(s[rank_col], errors="coerce")
    s = s.dropna(subset=["session_date", rank_col])

    s = s.sort_values(["session_date", rank_col], ascending=[True, False])
    s["daily_rank"] = s.groupby("session_date").cumcount() + 1
    s = s[s["daily_rank"] <= int(top_k)].copy()

    # Stable signal_id for joining.
    def _mk_id(row: pd.Series) -> str:
        raw = f"{row['session_date']}|{row['symbol']}|{row.get('timestamp','')}|{row['daily_rank']}".encode("utf-8")
        return sha1(raw).hexdigest()[:16]

    s["signal_id"] = s.apply(_mk_id, axis=1)
    return s


def build_price_windows(
    signals: pd.DataFrame,
    *,
    prices_dir: Path,
    lookback_days: int,
    forward_days: int,
    option_type: str = "CALL",
    option_dte: int = 30,
    option_iv: float = 0.50,
    option_rate: float = 0.04,
    option_dividend_yield: float = 0.0,
    option_strike_round: float = 1.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (windows, summary).

    windows: one row per signal per day in window, includes rel_day and returns from entry.
    summary: one row per signal with forward returns features.
    """

    if signals.empty:
        return (
            pd.DataFrame(columns=["signal_id", "symbol", "date", "rel_day", "close", "ret_from_entry"]),
            pd.DataFrame(columns=["signal_id", "symbol", "session_date"]),
        )

    out_rows: list[dict] = []
    summary_rows: list[dict] = []

    for (signal_id, symbol, session_date) in signals[["signal_id", "symbol", "session_date"]].itertuples(index=False):
        pdf = _read_prices(prices_dir, str(symbol))
        if pdf is None or pdf.empty:
            summary_rows.append({
                "signal_id": signal_id,
                "symbol": symbol,
                "session_date": session_date,
                "has_prices": False,
            })
            continue

        dates = pdf["date"].to_list()
        try:
            i0 = dates.index(session_date)
        except ValueError:
            summary_rows.append({
                "signal_id": signal_id,
                "symbol": symbol,
                "session_date": session_date,
                "has_prices": False,
            })
            continue

        start = max(0, i0 - int(lookback_days))
        end = min(len(pdf) - 1, i0 + int(forward_days))
        win = pdf.iloc[start : end + 1].copy().reset_index(drop=True)

        entry_close = float(win.loc[win["date"] == session_date, "close"].iloc[0])
        if not np.isfinite(entry_close) or entry_close == 0:
            entry_close = float(win["close"].iloc[0])

        # Default strike: ATM-ish rounded.
        strike_round = float(option_strike_round)
        if not np.isfinite(strike_round) or strike_round <= 0:
            strike_round = 1.0
        strike = round(entry_close / strike_round) * strike_round

        # rel_day is trading-day offset in the window slice
        rel0 = i0 - start
        for j, row in win.iterrows():
            close = float(row["close"]) if np.isfinite(row["close"]) else np.nan
            ret = (close / entry_close - 1.0) if np.isfinite(close) and entry_close else np.nan

            # Theoretical option fair value using underlying close as spot.
            # Treat rel_day as trading-day offset and convert to years (252 trading days).
            rel_day = int(j - rel0)
            t_years = max(0.0, (float(option_dte) - float(rel_day)) / 252.0)
            opt = black_scholes_fair_value(
                params=BlackScholesInputs(
                    spot=close,
                    strike=strike,
                    t_years=t_years,
                    rate=float(option_rate),
                    dividend_yield=float(option_dividend_yield),
                    iv=float(option_iv),
                ),
                option_type=str(option_type),
            )
            entry_opt = black_scholes_fair_value(
                params=BlackScholesInputs(
                    spot=entry_close,
                    strike=strike,
                    t_years=max(0.0, float(option_dte) / 252.0),
                    rate=float(option_rate),
                    dividend_yield=float(option_dividend_yield),
                    iv=float(option_iv),
                ),
                option_type=str(option_type),
            )
            opt_ret = (opt / entry_opt - 1.0) if np.isfinite(opt) and np.isfinite(entry_opt) and entry_opt != 0 else np.nan
            out_rows.append(
                {
                    "signal_id": signal_id,
                    "symbol": symbol,
                    "session_date": session_date,
                    "date": row["date"],
                    "rel_day": rel_day,
                    "close": close,
                    "ret_from_entry": float(ret) if np.isfinite(ret) else np.nan,
                    "theo_option_price": float(opt) if np.isfinite(opt) else np.nan,
                    "theo_option_ret": float(opt_ret) if np.isfinite(opt_ret) else np.nan,
                    "theo_option_strike": float(strike),
                }
            )

        # Summary forward returns at a few horizons (in trading days)
        horizons = [1, 3, 5, 10]
        summ = {
            "signal_id": signal_id,
            "symbol": symbol,
            "session_date": session_date,
            "has_prices": True,
            "entry_close": entry_close,
            "theo_option_strike": float(strike),
        }
        for h in horizons:
            idx = i0 + int(h)
            if idx < len(pdf):
                c = float(pdf.loc[idx, "close"])
                summ[f"ret_{h}d"] = (c / entry_close - 1.0) if entry_close else np.nan
            else:
                summ[f"ret_{h}d"] = np.nan
        summary_rows.append(summ)

    windows = pd.DataFrame(out_rows)
    summary = pd.DataFrame(summary_rows)
    return windows, summary


def analyze_top_signals_vs_price(
    *,
    scores_path: str,
    prices_dir: str | None,
    out_dir: str,
    top_k: int = 5,
    lookback_days: int = 5,
    forward_days: int = 10,
    tz: str = "America/New_York",
    option_type: str = "CALL",
    option_dte: int = 30,
    option_iv: float = 0.50,
    option_rate: float = 0.04,
    option_dividend_yield: float = 0.0,
    option_strike_round: float = 1.0,
) -> None:
    cfg = PerformanceConfig(
        top_k=int(top_k),
        lookback_days=int(lookback_days),
        forward_days=int(forward_days),
        tz=str(tz),
        option_type=str(option_type),
        option_dte=int(option_dte),
        option_iv=float(option_iv),
        option_rate=float(option_rate),
        option_dividend_yield=float(option_dividend_yield),
        option_strike_round=float(option_strike_round),
    )

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    scores = pd.read_parquet(scores_path)
    signals = select_top_k_per_day(scores, top_k=cfg.top_k, tz=cfg.tz)

    prices_path = Path(prices_dir) if prices_dir else _default_prices_dir()
    windows, summary = build_price_windows(
        signals,
        prices_dir=prices_path,
        lookback_days=cfg.lookback_days,
        forward_days=cfg.forward_days,
        option_type=cfg.option_type,
        option_dte=cfg.option_dte,
        option_iv=cfg.option_iv,
        option_rate=cfg.option_rate,
        option_dividend_yield=cfg.option_dividend_yield,
        option_strike_round=cfg.option_strike_round,
    )

    # Keep a compact set of signal columns to join later for training.
    keep = [
        c
        for c in [
            "signal_id",
            "timestamp",
            "session_date",
            "daily_rank",
            "symbol",
            "venue",
            "trader_id",
            "side",
            "ensemble_score",
            "ensemble_pct",
            "reason",
        ]
        if c in signals.columns
    ]
    signals_out = signals[keep].copy()

    write_parquet(signals_out, str(out / "signals.parquet"))
    write_parquet(windows, str(out / "signal_price_windows.parquet"))
    write_parquet(summary, str(out / "signal_return_summary.parquet"))
