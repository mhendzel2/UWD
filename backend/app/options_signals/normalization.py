from __future__ import annotations

import hashlib
from datetime import datetime, date
from typing import Iterable
from zoneinfo import ZoneInfo

import pandas as pd
from dateutil import parser

from app.options_signals.direction import infer_trade_direction


def _parse_timestamp(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return parser.parse(str(value))
    except (ValueError, TypeError):
        return None


def _parse_date(value: str | date | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return parser.parse(str(value), dayfirst=False).date()
    except (ValueError, TypeError):
        return None


def _hash_trade_id(values: Iterable[str]) -> str:
    joined = "|".join(str(v) for v in values)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def normalize_trades_frame(
    df: pd.DataFrame,
    *,
    market_tz: str,
    trusted_report_flags: set[str] | None = None,
) -> pd.DataFrame:
    out = df.copy()

    if "executed_at" not in out.columns:
        raise ValueError("executed_at column is required for options trade normalization")
    for col in ["underlying_symbol", "option_chain_id", "side", "option_type", "expiry", "report_flags"]:
        if col not in out.columns:
            out[col] = ""
    if "canceled" not in out.columns:
        out["canceled"] = False

    out["executed_at_utc"] = out["executed_at"].apply(_parse_timestamp)
    out = out.dropna(subset=["executed_at_utc"]).reset_index(drop=True)
    out["executed_at_utc"] = pd.to_datetime(out["executed_at_utc"], utc=True)
    market_zone = ZoneInfo(market_tz)
    out["executed_at_market"] = out["executed_at_utc"].dt.tz_convert(market_zone)
    out["trade_date"] = out["executed_at_market"].dt.date

    out["expiry_date"] = out["expiry"].apply(_parse_date)

    numeric_cols = [
        "strike",
        "underlying_price",
        "nbbo_bid",
        "nbbo_ask",
        "ewma_nbbo_bid",
        "ewma_nbbo_ask",
        "price",
        "premium",
        "implied_volatility",
        "delta",
        "theta",
        "gamma",
        "vega",
        "rho",
        "theo",
    ]
    for col in numeric_cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
        else:
            out[col] = pd.NA

    int_cols = ["size", "volume", "open_interest"]
    for col in int_cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
        else:
            out[col] = pd.NA

    out["underlying_symbol"] = out["underlying_symbol"].astype(str).str.upper()
    out["option_type"] = (
        out["option_type"]
        .astype(str)
        .str.lower()
        .map({"c": "call", "p": "put", "call": "call", "put": "put"})
        .fillna(out["option_type"])
    )

    canceled = out["canceled"].astype(str).str.lower().isin({"true", "t", "1", "yes", "y"})
    out["is_canceled"] = canceled

    trusted = None
    if trusted_report_flags:
        trusted = out["report_flags"].astype(str).isin(trusted_report_flags)
    else:
        trusted = pd.Series(True, index=out.index)
    out["report_trusted"] = trusted

    excluded_reason = pd.Series("", index=out.index, dtype=str)
    excluded_reason = excluded_reason.mask(out["is_canceled"], "canceled")
    excluded_reason = excluded_reason.mask(~out["report_trusted"], "report_flags")
    out["excluded_reason"] = excluded_reason.replace("", pd.NA)
    out["is_excluded"] = out["excluded_reason"].notna()

    directions = out.apply(
        lambda row: infer_trade_direction(
            price=row.get("price"),
            side=row.get("side"),
            nbbo_bid=row.get("nbbo_bid"),
            nbbo_ask=row.get("nbbo_ask"),
            ewma_nbbo_bid=row.get("ewma_nbbo_bid"),
            ewma_nbbo_ask=row.get("ewma_nbbo_ask"),
        ),
        axis=1,
    )
    out["trade_direction"] = [d[0] for d in directions]
    out["nbbo_valid"] = [d[1] for d in directions]

    out["trade_id"] = [
        _hash_trade_id(
            [
                row.get("executed_at_utc"),
                row.get("underlying_symbol"),
                row.get("option_chain_id"),
                row.get("price"),
                row.get("size"),
                row.get("premium"),
            ]
        )
        for _, row in out.iterrows()
    ]
    return out
