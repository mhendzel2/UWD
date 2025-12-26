from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from app.db import models
from app.utils.underlying import derive_underlying


def _option_type(row: Dict[str, Any]) -> str | None:
    opt_type = (row.get("option_type") or row.get("type") or "").lower()
    if opt_type in {"call", "c"}:
        return "CALL"
    if opt_type in {"put", "p"}:
        return "PUT"
    symbol = row.get("option_symbol") or row.get("symbol") or ""
    for marker in ("C", "P"):
        if marker in symbol:
            return "CALL" if marker == "C" else "PUT"
    return None


def _strike_price(row: Dict[str, Any]) -> float | None:
    try:
        if "strike" in row:
            return float(row.get("strike") or 0)
    except (ValueError, TypeError):
        pass
    symbol = row.get("option_symbol") or ""
    digits = "".join(ch for ch in str(symbol) if ch.isdigit())
    if digits:
        try:
            return float(digits) / 1000.0
        except ValueError:
            return None
    return None


def _parse_float(val: Any) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _load_rows(db: Session, session_id: str, source: models.RawSource) -> List[Dict[str, Any]]:
    rf = (
        db.query(models.RawFile)
        .filter(models.RawFile.session_id == session_id, models.RawFile.source == source)
        .order_by(models.RawFile.imported_at.desc())
        .first()
    )
    if rf and rf.extras and "rows" in rf.extras:
        return rf.extras["rows"]
    return []


def compute_strike_levels(
    oi_rows: List[Dict[str, Any]],
    hot_rows: List[Dict[str, Any]],
    bot_rows: List[Dict[str, Any]],
    top_n: int = 5,
) -> Dict[str, Dict[str, Any]]:
    metrics: dict[str, dict[float, dict[str, float]]] = defaultdict(lambda: defaultdict(lambda: {
        "call_oi": 0.0,
        "put_oi": 0.0,
        "call_premium": 0.0,
        "put_premium": 0.0,
        "net_gamma": 0.0,
        "net_delta": 0.0,
    }))

    for row in oi_rows:
        under = derive_underlying(row).upper()
        strike = _strike_price(row)
        if strike is None:
            continue
        side = _option_type(row)
        curr_oi = _parse_float(row.get("curr_oi") or row.get("open_interest") or row.get("curr_open_interest"))
        if side == "CALL":
            metrics[under][strike]["call_oi"] += curr_oi
        elif side == "PUT":
            metrics[under][strike]["put_oi"] += curr_oi

    for row in hot_rows:
        under = derive_underlying(row).upper()
        strike = _strike_price(row)
        if strike is None:
            continue
        side = _option_type(row)
        premium = _parse_float(row.get("premium"))
        if side == "CALL":
            metrics[under][strike]["call_premium"] += premium
        elif side == "PUT":
            metrics[under][strike]["put_premium"] += premium

    for row in bot_rows:
        under = derive_underlying(row).upper()
        strike = _strike_price(row)
        if strike is None:
            continue
        side = _option_type(row)
        premium = _parse_float(row.get("premium"))
        gamma = _parse_float(row.get("gamma"))
        delta = _parse_float(row.get("delta"))
        trade_side = str(row.get("side") or "").lower()
        sign = 1.0 if trade_side == "ask" else -1.0 if trade_side == "bid" else 0.0
        if side == "CALL":
            metrics[under][strike]["call_premium"] += premium
        elif side == "PUT":
            metrics[under][strike]["put_premium"] += premium
        metrics[under][strike]["net_gamma"] += gamma * sign
        metrics[under][strike]["net_delta"] += delta * sign

    summaries: dict[str, dict[str, Any]] = {}
    for under, strike_map in metrics.items():
        walls = []
        premiums = []
        gamma_spots = []
        net_delta_total = 0.0
        for strike, vals in strike_map.items():
            total_oi = vals["call_oi"] + vals["put_oi"]
            total_premium = vals["call_premium"] + vals["put_premium"]
            walls.append({"strike": strike, "total_oi": total_oi, "call_oi": vals["call_oi"], "put_oi": vals["put_oi"]})
            premiums.append({"strike": strike, "total_premium": total_premium, "call_premium": vals["call_premium"], "put_premium": vals["put_premium"]})
            gamma_spots.append({"strike": strike, "net_gamma": vals["net_gamma"]})
            net_delta_total += vals["net_delta"]

        walls_sorted = sorted(walls, key=lambda x: x["total_oi"], reverse=True)[:top_n]
        prem_sorted = sorted(premiums, key=lambda x: x["total_premium"], reverse=True)[:top_n]
        gamma_sorted = sorted(gamma_spots, key=lambda x: abs(x["net_gamma"]), reverse=True)[:top_n]
        summaries[under] = {
            "oi_walls": walls_sorted,
            "premium_pockets": prem_sorted,
            "gamma_hotspots": gamma_sorted,
            "net_delta_tilt": net_delta_total,
        }
    return summaries


def build_strike_levels_for_session(db: Session, session_id: str) -> Dict[str, Dict[str, Any]]:
    oi_rows = _load_rows(db, session_id, models.RawSource.OI_DIFF)
    hot_rows = _load_rows(db, session_id, models.RawSource.HOT_CHAINS)
    bot_rows = _load_rows(db, session_id, models.RawSource.BOT_EOD)
    return compute_strike_levels(oi_rows, hot_rows, bot_rows)
