"""
Offline runner that ingests the sample_data CSVs, builds v0 features, classifies regimes,
and prints plans for SPX/SPXW, SPY, and QQQ without needing Postgres or the FastAPI server.
"""
from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Dict, Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.append(str(BACKEND_ROOT))

from app.features.build_v0 import build_feature_row  # type: ignore
from app.regime.classify_v0 import classify  # type: ignore
from app.plans.build_plan_v0 import build_plan  # type: ignore

TARGETS = {"SPX", "SPXW", "SPY", "QQQ"}
ASOF_DATE = date(2025, 12, 24)
SAMPLE_DIR = REPO_ROOT / "sample_data"


def is_call(option_symbol: str) -> bool:
    """Detect call/put from OCC option symbol suffix."""
    if not option_symbol:
        return False
    m = re.search(r"(C|P)\d{8}$", option_symbol)
    if m:
        return m.group(1) == "C"
    # fallback: last non-digit marker
    for ch in reversed(option_symbol):
        if ch in ("C", "P"):
            return ch == "C"
        if ch.isdigit():
            continue
    return False


def underlying_from_option_symbol(option_symbol: str | None) -> str | None:
    if not option_symbol:
        return None
    prefix = []
    for ch in option_symbol:
        if ch.isdigit():
            break
        prefix.append(ch)
    return "".join(prefix) or None


def stream_csv(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield {k: (v if v not in ("", None) else None) for k, v in row.items()}


def ingest_oi(path: Path) -> Dict[str, Dict[str, float]]:
    metrics = defaultdict(lambda: {"call_oi": 0.0, "put_oi": 0.0, "multileg_oi": 0.0})
    for row in stream_csv(path):
        underlying = (
            row.get("underlying_symbol")
            or row.get("ticker")
            or row.get("underlying")
            or row.get("symbol")
            or underlying_from_option_symbol(row.get("option_symbol"))
        )
        if not underlying or underlying not in TARGETS:
            continue
        sym = row.get("option_symbol") or row.get("option_chain_id") or ""
        curr_oi = float(row.get("curr_oi") or row.get("open_interest") or 0) or 0.0
        if is_call(sym):
            metrics[underlying]["call_oi"] += curr_oi
        else:
            metrics[underlying]["put_oi"] += curr_oi
        multileg = float(row.get("prev_multi_leg_volume") or row.get("stock_multi_leg_volume") or row.get("multileg_volume") or 0) or 0.0
        metrics[underlying]["multileg_oi"] += multileg
    return metrics


def ingest_hot_chains(path: Path) -> Dict[str, Dict[str, float]]:
    metrics = defaultdict(lambda: {
        "turnover_notional": 0.0,
        "sweep_count": 0.0,
        "multileg_count": 0.0,
        "buy_volume": 0.0,
        "sell_volume": 0.0,
    })
    for row in stream_csv(path):
        underlying = row.get("underlying_symbol") or row.get("ticker") or underlying_from_option_symbol(row.get("option_symbol"))
        if not underlying or underlying not in TARGETS:
            continue
        turnover = float(row.get("premium") or 0) or 0.0
        sweep = float(row.get("sweep_volume") or 0) or 0.0
        multileg = float(row.get("multileg_volume") or 0) or 0.0
        buy_side = float(row.get("ask_side_volume") or 0) or 0.0
        sell_side = float(row.get("bid_side_volume") or 0) or 0.0
        metrics[underlying]["turnover_notional"] += turnover
        metrics[underlying]["sweep_count"] += sweep
        metrics[underlying]["multileg_count"] += multileg
        metrics[underlying]["buy_volume"] += buy_side
        metrics[underlying]["sell_volume"] += sell_side
    return metrics


def ingest_bot(path: Path) -> Dict[str, Dict[str, float]]:
    metrics = defaultdict(lambda: {"overpay_count": 0, "aggressive_count": 0, "gamma_exposure": 0.0})
    for row in stream_csv(path):
        underlying = row.get("underlying_symbol") or row.get("ticker")
        if not underlying or underlying not in TARGETS:
            continue
        nbbo_ask = float(row.get("nbbo_ask") or 0) or 0.0
        nbbo_bid = float(row.get("nbbo_bid") or 0) or 0.0
        price = float(row.get("price") or 0) or 0.0
        side = (row.get("side") or "").lower()
        gamma = float(row.get("gamma") or 0) or 0.0
        premium = float(row.get("premium") or 0) or 0.0
        if nbbo_ask and price > nbbo_ask * 1.01:
            metrics[underlying]["overpay_count"] += 1
        if side in {"ask", "bid"}:
            metrics[underlying]["aggressive_count"] += 1
        metrics[underlying]["gamma_exposure"] += abs(premium * gamma)
    return metrics


def ingest_stock_screener(path: Path) -> Dict[str, Dict[str, float]]:
    metrics = defaultdict(lambda: {"implied_move": 0.0, "directional_skew": 0.0, "iv_percentile": 0.0})
    for row in stream_csv(path):
        underlying = row.get("ticker")
        if not underlying or underlying not in TARGETS:
            continue
        implied = float(row.get("implied_move_perc") or row.get("implied_move") or 0) or 0.0
        bull = float(row.get("bullish_premium") or 0) or 0.0
        bear = float(row.get("bearish_premium") or 0) or 0.0
        skew = 0.0
        if bull or bear:
            skew = (bull - bear) / (bull + bear)
        iv_rank = row.get("iv_rank")
        iv_val = float(iv_rank or 0) if iv_rank is not None else 0.0
        if iv_val > 1:
            iv_val = iv_val / 100.0
        metrics[underlying]["implied_move"] = max(metrics[underlying]["implied_move"], implied)
        metrics[underlying]["directional_skew"] = max(metrics[underlying]["directional_skew"], skew)
        metrics[underlying]["iv_percentile"] = max(metrics[underlying]["iv_percentile"], iv_val)
    return metrics


def ingest_darkpool(path: Path) -> Dict[str, Dict[str, float]]:
    metrics = defaultdict(lambda: {"notional": 0.0, "buy_notional": 0.0, "sell_notional": 0.0})
    for row in stream_csv(path):
        underlying = row.get("ticker")
        if not underlying or underlying not in TARGETS:
            continue
        notional = float(row.get("premium") or row.get("volume") or 0) or 0.0
        metrics[underlying]["notional"] += notional
    return metrics


def merge_aggregates(parts: Dict[str, Dict[str, Dict[str, float]]]) -> Dict[str, Dict[str, Dict[str, float]]]:
    combined: Dict[str, Dict[str, Dict[str, float]]] = {}
    for source, agg in parts.items():
        for underlying, metrics in agg.items():
            combined.setdefault(underlying, {})
            combined[underlying][source] = metrics
    return combined


def run() -> None:
    sources = {
        "oi": ingest_oi(SAMPLE_DIR / "chain-oi-changes-2025-12-24.csv"),
        "hot_chains": ingest_hot_chains(SAMPLE_DIR / "hot-chains-2025-12-24.csv"),
        "bot": ingest_bot(SAMPLE_DIR / "bot-eod-report-2025-12-24.csv"),
        "stock_screener": ingest_stock_screener(SAMPLE_DIR / "stock-screener-2025-12-24.csv"),
        "darkpool": ingest_darkpool(SAMPLE_DIR / "dp-eod-report-2025-12-24.csv"),
    }
    aggregates = merge_aggregates(sources)
    results = []
    for underlying, agg in aggregates.items():
        feature = build_feature_row("offline-session", underlying, ASOF_DATE, agg)
        decision = classify(feature)
        plan = build_plan(decision, trade_date=ASOF_DATE)
        results.append(
            {
                "underlying": underlying,
                "features": feature.numeric_context,
                "regime": decision.regime_label.value,
                "confidence": decision.confidence_tier.value,
                "plan_type": plan.plan_type.value,
            }
        )
    results = sorted(results, key=lambda r: r["underlying"])
    print("Offline v0 run (filtered to SPX/SPXW, SPY, QQQ) for 2025-12-24")
    for r in results:
        print(f"- {r['underlying']}: regime={r['regime']} conf={r['confidence']} plan={r['plan_type']}")
        print(f"  hot_chains={r['features'].get('hot_chains', {})}")
        print(f"  oi={r['features'].get('oi', {})}")
        print(f"  stock_screener={r['features'].get('stock_screener', {})}")
        print(f"  darkpool={r['features'].get('darkpool', {})}")


if __name__ == "__main__":
    run()
