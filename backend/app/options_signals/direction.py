from __future__ import annotations

from typing import Optional


def infer_trade_direction(
    *,
    price: Optional[float],
    side: Optional[str],
    nbbo_bid: Optional[float],
    nbbo_ask: Optional[float],
    ewma_nbbo_bid: Optional[float],
    ewma_nbbo_ask: Optional[float],
    eps: float = 0.01,
    eps2: float = 0.005,
) -> tuple[str, bool]:
    side_value = (side or "").strip().lower()
    if side_value in {"ask", "buy", "buyer"}:
        return "buyer_initiated", True
    if side_value in {"bid", "sell", "seller"}:
        return "seller_initiated", True

    bid = nbbo_bid if nbbo_bid and nbbo_bid > 0 else None
    ask = nbbo_ask if nbbo_ask and nbbo_ask > 0 else None
    if bid is None or ask is None:
        bid = ewma_nbbo_bid if ewma_nbbo_bid and ewma_nbbo_bid > 0 else None
        ask = ewma_nbbo_ask if ewma_nbbo_ask and ewma_nbbo_ask > 0 else None

    if bid is None or ask is None or price is None:
        return "unknown", False

    mid = (bid + ask) / 2.0
    if price >= ask - eps:
        return "buyer_initiated", True
    if price <= bid + eps:
        return "seller_initiated", True
    if price > mid + eps2:
        return "buyer_initiated", True
    if price < mid - eps2:
        return "seller_initiated", True
    return "unknown", True

