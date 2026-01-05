from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from trade_surveillance.io import write_csv


@dataclass(frozen=True)
class DemoSpec:
    symbols: tuple[str, ...] = ("SPY", "AAPL", "NVDA", "TSLA", "MSFT")
    venues: tuple[str, ...] = ("ARCA", "NASDAQ", "NYSE")
    traders: tuple[str, ...] = ("T1", "T2", "T3")


def _market_session_times_utc(d: datetime) -> tuple[pd.Timestamp, pd.Timestamp]:
    # Keep it simple: generate trades over a fixed intraday window in UTC.
    # Assumption documented later: timestamps are UTC and span a single day.
    start = pd.Timestamp(datetime(d.year, d.month, d.day, 14, 30, tzinfo=timezone.utc))
    end = pd.Timestamp(datetime(d.year, d.month, d.day, 21, 0, tzinfo=timezone.utc))
    return start, end


def _gen_quotes_for_symbol(rng: np.random.Generator, sym: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    idx = pd.date_range(start=start, end=end, freq="1s", tz="UTC")
    n = len(idx)

    base = {
        "SPY": 470.0,
        "AAPL": 190.0,
        "NVDA": 490.0,
        "TSLA": 240.0,
        "MSFT": 410.0,
    }.get(sym, 100.0)

    # Random walk mid with mild intraday vol.
    rets = rng.normal(loc=0.0, scale=0.00015, size=n)
    mid = base * np.exp(np.cumsum(rets))

    # Spread regime: mostly tight, occasional wider periods.
    spread_bps = rng.choice([2.0, 4.0, 8.0, 15.0], size=n, p=[0.70, 0.20, 0.08, 0.02])
    spread = mid * (spread_bps / 10000.0)
    bid = mid - 0.5 * spread
    ask = mid + 0.5 * spread

    return pd.DataFrame(
        {
            "timestamp": idx,
            "symbol": sym,
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "spread_bps": spread_bps,
        }
    )


def _sample_trades_from_quotes(
    rng: np.random.Generator,
    quotes: pd.DataFrame,
    venue: str,
    trader_id: str,
    n_trades: int,
) -> pd.DataFrame:
    q = quotes
    ts = q["timestamp"].to_numpy()
    idx = rng.integers(0, len(ts), size=n_trades)
    idx.sort()

    side = rng.choice(["BUY", "SELL"], size=n_trades)
    qty = rng.lognormal(mean=5.0, sigma=0.6, size=n_trades)  # around a few hundred
    qty = np.round(qty).astype(float)

    mid = q["mid"].to_numpy()[idx]
    spread = (q["ask"].to_numpy()[idx] - q["bid"].to_numpy()[idx])
    # Trade price close to mid with a small slippage.
    slip = rng.normal(loc=0.0, scale=0.10, size=n_trades) * (spread / 2.0)
    price = mid + slip

    out = pd.DataFrame(
        {
            "timestamp": ts[idx],
            "symbol": q["symbol"].iloc[0],
            "venue": venue,
            "trader_id": trader_id,
            "side": side,
            "price": price,
            "qty": qty,
            "bid": q["bid"].to_numpy()[idx],
            "ask": q["ask"].to_numpy()[idx],
            "mid_price": mid,
        }
    )
    return out


def _inject_anomalies(rng: np.random.Generator, trades: pd.DataFrame, quotes: pd.DataFrame | None) -> None:
    # Inject anomalies in-place.
    n = len(trades)
    if n < 100:
        return

    # 1) Huge size in quiet regime
    quiet_mask = trades["symbol"].isin(["SPY", "MSFT"])  # typically tighter spreads
    quiet_idx = trades.index[quiet_mask]
    if len(quiet_idx) > 0:
        pick = rng.choice(quiet_idx, size=max(3, n // 5000), replace=False)
        trades.loc[pick, "qty"] *= 50

    # 2) Extreme price_vs_mid (crossed prints)
    pick = rng.choice(trades.index, size=max(5, n // 4000), replace=False)
    # Push price away from mid by 50-150 bps.
    bps = rng.uniform(50, 150, size=len(pick)) * rng.choice([-1, 1], size=len(pick))
    trades.loc[pick, "price"] = trades.loc[pick, "mid_price"] * (1.0 + bps / 10000.0)

    # 3) Bursty trading intensity (short intertrade gaps)
    burst_start = int(rng.integers(0, n - 50))
    burst_idx = trades.index[burst_start : burst_start + 50]
    base_ts = pd.to_datetime(trades.loc[burst_idx[0], "timestamp"], utc=True)
    burst_ts = [base_ts + pd.Timedelta(milliseconds=int(i * rng.integers(10, 80))) for i in range(len(burst_idx))]
    trades.loc[burst_idx, "timestamp"] = burst_ts

    # 4) Regime shift in spread residual: widen spreads for one symbol late in day
    if quotes is not None and not quotes.empty:
        sym = trades["symbol"].iloc[0]
        late_mask = trades["timestamp"] >= trades["timestamp"].max() - pd.Timedelta(minutes=30)
        late_idx = trades.index[late_mask & (trades["symbol"] == sym)]
        if len(late_idx) > 0:
            # Make prices more aggressive vs mid (proxy for spread residual shift)
            trades.loc[late_idx, "price"] = trades.loc[late_idx, "mid_price"] * (1.0 + 0.0025)


def generate_demo_data(*, out_dir: str, n_trades: int, with_quotes: bool, seed: int) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(seed)
    spec = DemoSpec()

    day = datetime(2026, 1, 2, tzinfo=timezone.utc)
    start, end = _market_session_times_utc(day)

    all_quotes: list[pd.DataFrame] = []
    all_trades: list[pd.DataFrame] = []

    # Distribute trades roughly evenly across symbols.
    per_symbol = max(1, int(n_trades // len(spec.symbols)))
    for sym in spec.symbols:
        qdf = _gen_quotes_for_symbol(rng, sym, start, end)
        v = rng.choice(spec.venues)
        t = rng.choice(spec.traders)
        tdf = _sample_trades_from_quotes(rng, qdf, venue=str(v), trader_id=str(t), n_trades=per_symbol)
        _inject_anomalies(rng, tdf, qdf if with_quotes else None)
        all_trades.append(tdf)
        if with_quotes:
            all_quotes.append(qdf[["timestamp", "symbol", "bid", "ask"]])

    trades = pd.concat(all_trades, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
    trades["timestamp"] = pd.to_datetime(trades["timestamp"], utc=True)

    write_csv(trades, str(out / "trades.csv"))

    if with_quotes:
        quotes = pd.concat(all_quotes, ignore_index=True).sort_values(["symbol", "timestamp"]).reset_index(drop=True)
        quotes["timestamp"] = pd.to_datetime(quotes["timestamp"], utc=True)
        write_csv(quotes, str(out / "quotes.csv"))
