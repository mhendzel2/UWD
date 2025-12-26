from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from app.analysis.strike_analysis import build_strike_levels_for_session
from app.db import models
from app.utils.underlying import derive_underlying

BRIEF_VERSION = "v1"
TOP_N = 10
FLOW_MIN_VOLUME = 1_000_000
FLOW_MIN_MARKETCAP = 1_000_000_000
VOL_LIQUIDITY_MIN = 500_000
EARNINGS_BLACKOUT_DAYS = 7


def _parse_float(row: Dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, default) or default)
    except (ValueError, TypeError):
        return default


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _load_stock_rows(session_id: str, db: Session) -> List[Dict[str, Any]]:
    files = (
        db.query(models.RawFile)
        .filter(models.RawFile.session_id == session_id, models.RawFile.source == models.RawSource.STOCK_SCREENER)
        .all()
    )
    rows: list[dict[str, Any]] = []
    for rf in files:
        if rf.extras and "rows" in rf.extras:
            rows.extend(rf.extras["rows"])
    if not rows:
        raise ValueError("No stock screener rows available for session")
    return rows


def _filter_universe(row: Dict[str, Any], asof_date: date, liquidity_floor: float) -> bool:
    issue_type = str(row.get("issue_type") or "").lower()
    total_volume = _parse_float(row, "total_volume")
    marketcap = _parse_float(row, "marketcap")
    next_earnings = _parse_date(row.get("next_earnings_date"))
    if next_earnings and abs((next_earnings - asof_date).days) <= EARNINGS_BLACKOUT_DAYS:
        return False
    liquid = (total_volume and total_volume >= liquidity_floor) or (marketcap and marketcap >= FLOW_MIN_MARKETCAP)
    return issue_type in {"common stock", "etf"} and liquid


def _infer_universe(row: Dict[str, Any]) -> models.UnderlyingUniverse:
    issue_type = str(row.get("issue_type") or "").upper()
    is_index = str(row.get("is_index") or "").lower() in {"t", "true", "1", "yes"}
    if is_index or issue_type == "ETF":
        return models.UnderlyingUniverse.INDEX
    return models.UnderlyingUniverse.EQUITY


def _build_flow_entries(rows: List[Dict[str, Any]], asof_date: date) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str]:
    bullish: list[dict[str, Any]] = []
    bearish: list[dict[str, Any]] = []
    for row in rows:
        if not _filter_universe(row, asof_date, FLOW_MIN_VOLUME):
            continue
        ticker = row.get("ticker") or derive_underlying(row)
        call_volume = _parse_float(row, "call_volume")
        put_volume = _parse_float(row, "put_volume")
        call_premium = _parse_float(row, "call_premium")
        put_premium = _parse_float(row, "put_premium")
        volume_imbalance = call_volume - put_volume
        premium_imbalance = call_premium - put_premium
        call_premium_share = call_premium / (call_premium + put_premium) if (call_premium + put_premium) else 0
        implied_move_perc = _parse_float(row, "implied_move_perc")
        iv_rank = _parse_float(row, "iv_rank")
        bias = "BULLISH" if volume_imbalance > 0 and premium_imbalance > 0 else "BEARISH"
        entry = {
            "ticker": ticker,
            "bias": bias,
            "call_volume": call_volume,
            "put_volume": put_volume,
            "volume_imbalance": volume_imbalance,
            "call_premium": call_premium,
            "put_premium": put_premium,
            "premium_imbalance": premium_imbalance,
            "call_premium_share": call_premium_share,
            "implied_move_perc": implied_move_perc,
            "iv_rank": iv_rank,
            "requires_regime_permission": True,
            "suggested_structures": ["debit spread", "credit spread", "defined-risk vertical"],
            "confidence_note": f"imbalance {volume_imbalance:,.0f} vol / {premium_imbalance:,.0f} prem",
            "disclaimer": "Candidate only; requires regime permission.",
        }
        if bias == "BULLISH":
            bullish.append(entry)
        else:
            bearish.append(entry)

    score_key = lambda e: (abs(e["volume_imbalance"]), abs(e["premium_imbalance"]))
    bullish_sorted = sorted(bullish, key=score_key, reverse=True)[:TOP_N]
    bearish_sorted = sorted(bearish, key=score_key, reverse=True)[:TOP_N]
    note = "No bearish candidates after filters" if not bearish_sorted else ""
    return bullish_sorted, bearish_sorted, note


def _build_vol_sell(rows: List[Dict[str, Any]], asof_date: date) -> Tuple[List[Dict[str, Any]], str]:
    entries: list[dict[str, Any]] = []
    for row in rows:
        if not _filter_universe(row, asof_date, VOL_LIQUIDITY_MIN):
            continue
        ticker = row.get("ticker") or derive_underlying(row)
        iv_rank = _parse_float(row, "iv_rank")
        iv30d = _parse_float(row, "iv30d")
        implied_move_perc = _parse_float(row, "implied_move_perc")
        if iv_rank <= 0:
            continue
        entries.append(
            {
                "ticker": ticker,
                "iv_rank": iv_rank,
                "iv30d": iv30d,
                "implied_move_perc": implied_move_perc,
                "suggested_structures": ["iron condor", "short strangle (defined risk preferred)"],
                "risk_note": "Monitor borrow/locate and event calendar.",
                "requires_regime_permission": True,
                "disclaimer": "Watchlist only; not a trade signal.",
            }
        )
    sorted_entries = sorted(entries, key=lambda e: e["iv_rank"], reverse=True)[:TOP_N]
    note = "Filtered by iv_rank descending and liquidity."
    return sorted_entries, note


def _build_vol_buy(rows: List[Dict[str, Any]], asof_date: date) -> Tuple[List[Dict[str, Any]], str]:
    entries: list[dict[str, Any]] = []
    for row in rows:
        if not _filter_universe(row, asof_date, VOL_LIQUIDITY_MIN):
            continue
        iv_rank = _parse_float(row, "iv_rank")
        if iv_rank > 0.15:
            continue
        ticker = row.get("ticker") or derive_underlying(row)
        implied_move_perc = _parse_float(row, "implied_move_perc")
        entries.append(
            {
                "ticker": ticker,
                "iv_rank": iv_rank,
                "implied_move_perc": implied_move_perc,
                "suggested_structures": ["calendar", "diagonal", "straddle/strangle into catalyst"],
                "note": "Not immediate; catalyst-driven only.",
                "requires_regime_permission": True,
                "disclaimer": "Exploratory candidate; confirm catalyst and regime.",
            }
        )
    sorted_entries = sorted(entries, key=lambda e: e["iv_rank"])[:TOP_N]
    note = "Low IV rank candidates (<=15th percentile)."
    return sorted_entries, note


def _persist_brief(
    db: Session,
    session_id: str,
    asof_date: date,
    brief_type: models.BriefType,
    universe: models.UnderlyingUniverse,
    entries: list[dict[str, Any]] | dict[str, Any],
    note: str,
) -> models.DailyBrief:
    db.query(models.DailyBrief).filter(
        models.DailyBrief.session_id == session_id,
        models.DailyBrief.date == asof_date,
        models.DailyBrief.brief_type == brief_type,
    ).delete()
    brief = models.DailyBrief(
        session_id=session_id,
        date=asof_date,
        brief_type=brief_type,
        underlying_universe=universe,
        entries={"items": entries, "note": note},
        generated_at=datetime.utcnow(),
        brief_version=BRIEF_VERSION,
    )
    db.add(brief)
    return brief


def generate_briefs(db: Session, session: models.Session, asof_date: date | None = None) -> list[models.DailyBrief]:
    asof_date = asof_date or session.date
    rows = _load_stock_rows(str(session.session_id), db)
    strike_levels = build_strike_levels_for_session(db, str(session.session_id))
    universe = models.UnderlyingUniverse.MIXED

    bullish, bearish, flow_note = _build_flow_entries(rows, asof_date)
    for entry in bullish + bearish:
        entry["strike_levels"] = strike_levels.get((entry.get("ticker") or "").upper())
    flow_entries = {"bullish": bullish, "bearish": bearish}
    flow_brief = _persist_brief(
        db=db,
        session_id=str(session.session_id),
        asof_date=asof_date,
        brief_type=models.BriefType.FLOW_SHORT_TERM,
        universe=universe,
        entries=flow_entries,
        note=flow_note,
    )

    vol_sell, sell_note = _build_vol_sell(rows, asof_date)
    for entry in vol_sell:
        entry["strike_levels"] = strike_levels.get((entry.get("ticker") or "").upper())
    vol_sell_brief = _persist_brief(
        db=db,
        session_id=str(session.session_id),
        asof_date=asof_date,
        brief_type=models.BriefType.VOL_SELL_PREMIUM,
        universe=universe,
        entries=vol_sell,
        note=sell_note,
    )

    vol_buy, buy_note = _build_vol_buy(rows, asof_date)
    for entry in vol_buy:
        entry["strike_levels"] = strike_levels.get((entry.get("ticker") or "").upper())
    vol_buy_brief = _persist_brief(
        db=db,
        session_id=str(session.session_id),
        asof_date=asof_date,
        brief_type=models.BriefType.VOL_BUY_PREMIUM,
        universe=universe,
        entries=vol_buy,
        note=buy_note,
    )

    return [flow_brief, vol_sell_brief, vol_buy_brief]
