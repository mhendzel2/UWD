import math
import statistics
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.db import models
from app.utils.underlying import derive_underlying


Number = float | int


@dataclass
class FeatureStat:
    center: float
    scale: float
    sorted_values: List[float]


@dataclass
class EventCandidate:
    source: models.RawSource
    ticker: str
    event_key: str
    features: Dict[str, Optional[float]]
    raw_ref: Dict[str, Any]


@dataclass
class ScoredAnomaly:
    source: models.RawSource
    ticker: str
    event_key: str
    severity_score: float
    ensemble_score: float
    reason_codes: List[str]
    feature_payload: Dict[str, Dict[str, float]]
    raw_ref: Dict[str, Any]


@dataclass
class TickerRollup:
    ticker: str
    severity_score: float
    ensemble_score: float
    reason_codes: List[str]
    feature_payload: Dict[str, Any]
    raw_ref: Dict[str, Any]


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def robust_center_scale(values: Iterable[Number], epsilon: float = 1e-6) -> Tuple[float, float]:
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return 0.0, 1.0
    center = statistics.median(clean)
    mad = statistics.median(abs(v - center) for v in clean)
    return center, max(mad, epsilon)


def percentile_rank(value: float, sorted_values: Sequence[float]) -> float:
    if not sorted_values:
        return 0.5
    idx = bisect_right(sorted_values, value)
    pct = idx / len(sorted_values)
    return max(0.0, min(1.0, pct))


def _feature_labels(source: models.RawSource) -> Dict[str, str]:
    if source == models.RawSource.OI_DIFF:
        return {
            "oi_diff_plain": "OI change (contracts)",
            "oi_change": "OI change %",
            "volume": "Volume",
            "trades": "Trades count",
            "percentage_of_total": "% of chain",
            "curr_oi": "Current OI",
            "last_oi": "Prev OI",
            "oi_diff_perc": "OI % delta",
            "volume_vs_prev": "Volume vs prev day",
            "stock_price": "Stock price",
            "dte": "DTE",
        }
    if source == models.RawSource.HOT_CHAINS:
        return {
            "volume": "Volume",
            "open_interest": "Open interest",
            "premium": "Premium",
            "trades": "Trades",
            "ask_side_volume_frac": "Ask-side %",
            "bid_side_volume_frac": "Bid-side %",
            "sweep_volume_frac": "Sweep %",
            "cross_volume_frac": "Cross %",
            "premium_per_trade": "Premium per trade",
            "premium_per_contract": "Premium per contract",
        }
    if source == models.RawSource.DARKPOOL_EOD:
        return {
            "size": "Darkpool size",
            "premium": "Darkpool premium",
            "price": "Fill price",
            "nbbo_bid": "NBBO bid",
            "nbbo_ask": "NBBO ask",
            "nbbo_mid": "NBBO mid",
            "price_vs_mid_bps": "Price vs mid (bps)",
            "spread_bps": "Spread (bps)",
            "pct_into_spread": "% into spread",
            "time_of_day_bin": "Time of day bin",
        }
    if source == models.RawSource.STOCK_SCREENER:
        return {
            "call_volume": "Call volume",
            "put_volume": "Put volume",
            "call_premium": "Call premium",
            "put_premium": "Put premium",
            "put_call_ratio": "Put/Call ratio",
            "net_call_premium": "Net call premium",
            "net_put_premium": "Net put premium",
            "total_open_interest": "Total OI",
            "iv_rank": "IV rank",
            "implied_move_perc": "Implied move %",
            "call_minus_put_premium": "Call - Put premium",
            "call_minus_put_volume": "Call - Put volume",
            "marketcap": "Market cap",
        }
    return {}


def _time_of_day_bin(ts: Optional[str]) -> Optional[int]:
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    hour = parsed.hour
    if hour < 12:
        return 0
    if hour < 15:
        return 1
    return 2


def _build_oi_candidates(rows: List[Mapping[str, Any]], file_id: str) -> List[EventCandidate]:
    candidates: list[EventCandidate] = []
    for row in rows:
        ticker = derive_underlying(row)
        option_symbol = row.get("option_symbol") or row.get("optionsymbol")
        strike = row.get("strike")
        dte = row.get("dte")
        curr_date = row.get("curr_date") or row.get("date")
        event_key = str(option_symbol or f"{ticker}|{strike or 'UNK'}|{dte or curr_date or 'NA'}")

        curr_oi = _to_float(row.get("curr_oi"))
        last_oi = _to_float(row.get("last_oi"))
        curr_vol = _to_float(row.get("curr_vol")) or _to_float(row.get("volume"))
        prev_vol = _to_float(row.get("prev_vol"))
        oi_diff_plain = _to_float(row.get("oi_diff_plain") or row.get("oi_diff"))
        oi_diff_perc = None
        if curr_oi is not None and last_oi is not None:
            oi_diff_perc = (curr_oi - last_oi) / max(last_oi, 1.0)
        volume_vs_prev = None
        if curr_vol is not None and prev_vol not in (None, 0):
            volume_vs_prev = curr_vol / max(prev_vol, 1.0)

        features = {
            "oi_diff_plain": oi_diff_plain,
            "oi_change": _to_float(row.get("oi_change")),
            "volume": curr_vol,
            "trades": _to_float(row.get("trades")),
            "percentage_of_total": _to_float(row.get("percentage_of_total")),
            "curr_oi": curr_oi,
            "last_oi": last_oi,
            "oi_diff_perc": oi_diff_perc,
            "volume_vs_prev": volume_vs_prev,
            "dte": _to_float(dte),
            "stock_price": _to_float(row.get("stock_price")),
        }
        raw_ref = {
            "file_id": file_id,
            "option_symbol": option_symbol,
            "strike": strike,
            "dte": dte,
            "curr_date": curr_date,
        }
        candidates.append(
            EventCandidate(
                source=models.RawSource.OI_DIFF,
                ticker=ticker,
                event_key=event_key,
                features=features,
                raw_ref=raw_ref,
            )
        )
    return candidates


def _safe_frac(num: Optional[float], denom: Optional[float]) -> Optional[float]:
    if num is None or denom in (None, 0):
        return None
    return num / denom


def _build_hot_chain_candidates(rows: List[Mapping[str, Any]], file_id: str) -> List[EventCandidate]:
    candidates: list[EventCandidate] = []
    for idx, row in enumerate(rows):
        ticker = derive_underlying(row)
        option_symbol = row.get("option_symbol")
        date = row.get("date")
        event_key = str(option_symbol or f"{ticker}|{date}|{idx}")
        volume = _to_float(row.get("volume"))
        premium = _to_float(row.get("premium"))
        trades = _to_float(row.get("trades"))
        features = {
            "volume": volume,
            "open_interest": _to_float(row.get("open_interest")),
            "premium": premium,
            "trades": trades,
            "ask_side_volume_frac": _safe_frac(_to_float(row.get("ask_side_volume")), volume),
            "bid_side_volume_frac": _safe_frac(_to_float(row.get("bid_side_volume")), volume),
            "sweep_volume_frac": _safe_frac(_to_float(row.get("sweep_volume")), volume),
            "cross_volume_frac": _safe_frac(_to_float(row.get("cross_volume")), volume),
            "premium_per_trade": _safe_frac(premium, trades),
            "premium_per_contract": _safe_frac(premium, volume),
        }
        raw_ref = {
            "file_id": file_id,
            "option_symbol": option_symbol,
            "date": date,
            "sector": row.get("sector"),
        }
        candidates.append(
            EventCandidate(
                source=models.RawSource.HOT_CHAINS,
                ticker=ticker,
                event_key=event_key,
                features=features,
                raw_ref=raw_ref,
            )
        )
    return candidates


def _build_darkpool_candidates(rows: List[Mapping[str, Any]], file_id: str) -> List[EventCandidate]:
    candidates: list[EventCandidate] = []
    for idx, row in enumerate(rows):
        ticker = derive_underlying(row)
        executed_at = row.get("executed_at")
        event_key = f"{ticker}|{executed_at or row.get('date') or 'ts'}|{idx}"
        nbbo_bid = _to_float(row.get("nbbo_bid"))
        nbbo_ask = _to_float(row.get("nbbo_ask"))
        price = _to_float(row.get("price"))
        mid = None
        if nbbo_bid is not None and nbbo_ask is not None:
            mid = (nbbo_bid + nbbo_ask) / 2.0
        spread_bps = None
        pct_into_spread = None
        if mid not in (None, 0) and nbbo_bid is not None and nbbo_ask is not None:
            spread_bps = ((nbbo_ask - nbbo_bid) / mid) * 10000.0
            if price is not None and nbbo_ask != nbbo_bid:
                pct_into_spread = (price - nbbo_bid) / (nbbo_ask - nbbo_bid)
        price_vs_mid_bps = None
        if mid not in (None, 0) and price is not None:
            price_vs_mid_bps = ((price - mid) / mid) * 10000.0
        features = {
            "size": _to_float(row.get("size") or row.get("volume")),
            "premium": _to_float(row.get("premium")),
            "price": price,
            "nbbo_bid": nbbo_bid,
            "nbbo_ask": nbbo_ask,
            "nbbo_mid": mid,
            "price_vs_mid_bps": price_vs_mid_bps,
            "spread_bps": spread_bps,
            "pct_into_spread": pct_into_spread,
            "time_of_day_bin": _to_float(_time_of_day_bin(executed_at)),
        }
        raw_ref = {
            "file_id": file_id,
            "executed_at": executed_at,
            "trade_code": row.get("trade_code"),
        }
        candidates.append(
            EventCandidate(
                source=models.RawSource.DARKPOOL_EOD,
                ticker=ticker,
                event_key=event_key,
                features=features,
                raw_ref=raw_ref,
            )
        )
    return candidates


def _build_stock_screener_candidates(rows: List[Mapping[str, Any]], file_id: str) -> List[EventCandidate]:
    candidates: list[EventCandidate] = []
    for idx, row in enumerate(rows):
        ticker = derive_underlying(row)
        date = row.get("date")
        event_key = f"{ticker}|{date}|{idx}"
        call_volume = _to_float(row.get("call_volume"))
        put_volume = _to_float(row.get("put_volume"))
        call_premium = _to_float(row.get("call_premium"))
        put_premium = _to_float(row.get("put_premium"))
        net_call_premium = _to_float(row.get("net_call_premium"))
        net_put_premium = _to_float(row.get("net_put_premium"))
        features = {
            "call_volume": call_volume,
            "put_volume": put_volume,
            "call_premium": call_premium,
            "put_premium": put_premium,
            "put_call_ratio": _to_float(row.get("put_call_ratio")),
            "net_call_premium": net_call_premium,
            "net_put_premium": net_put_premium,
            "total_open_interest": _to_float(row.get("total_open_interest")),
            "iv_rank": _to_float(row.get("iv_rank")),
            "implied_move_perc": _to_float(row.get("implied_move_perc")),
            "call_minus_put_premium": (call_premium - put_premium) if call_premium is not None and put_premium is not None else None,
            "call_minus_put_volume": (call_volume - put_volume) if call_volume is not None and put_volume is not None else None,
            "marketcap": _to_float(row.get("marketcap")),
        }
        raw_ref = {
            "file_id": file_id,
            "date": date,
            "sector": row.get("sector"),
            "issue_type": row.get("issue_type"),
            "is_index": row.get("is_index"),
        }
        candidates.append(
            EventCandidate(
                source=models.RawSource.STOCK_SCREENER,
                ticker=ticker,
                event_key=event_key,
                features=features,
                raw_ref=raw_ref,
            )
        )
    return candidates


def _build_candidates_for_files(files: Iterable[models.RawFile]) -> List[EventCandidate]:
    candidates: list[EventCandidate] = []
    for rf in files:
        if not rf.extras or "rows" not in rf.extras:
            continue
        rows = rf.extras.get("rows") or []
        file_id = str(rf.file_id)
        if rf.source == models.RawSource.OI_DIFF:
            candidates.extend(_build_oi_candidates(rows, file_id))
        elif rf.source == models.RawSource.HOT_CHAINS:
            candidates.extend(_build_hot_chain_candidates(rows, file_id))
        elif rf.source == models.RawSource.DARKPOOL_EOD:
            candidates.extend(_build_darkpool_candidates(rows, file_id))
        elif rf.source == models.RawSource.STOCK_SCREENER:
            candidates.extend(_build_stock_screener_candidates(rows, file_id))
        else:
            continue
    return candidates


def _build_bucket_stats(candidates: Iterable[EventCandidate]) -> Dict[Tuple[models.RawSource, str], Dict[str, FeatureStat]]:
    buckets: dict[tuple[models.RawSource, str], dict[str, list[float]]] = {}
    for cand in candidates:
        bucket_key = (cand.source, cand.ticker)
        buckets.setdefault(bucket_key, {})
        for feat, value in cand.features.items():
            if value is None:
                continue
            buckets[bucket_key].setdefault(feat, []).append(value)

    stats: dict[tuple[models.RawSource, str], dict[str, FeatureStat]] = {}
    for bucket_key, feat_map in buckets.items():
        stats[bucket_key] = {}
        for feat, values in feat_map.items():
            center, scale = robust_center_scale(values)
            stats[bucket_key][feat] = FeatureStat(center=center, scale=scale, sorted_values=sorted(values))
    return stats


def _risk_weight(cand: EventCandidate) -> float:
    feats = cand.features
    if cand.source == models.RawSource.DARKPOOL_EOD:
        size = feats.get("size") or 0.0
        prem = feats.get("premium") or 0.0
        return max(1.0, math.log1p(max(prem, size)))
    if cand.source in (models.RawSource.OI_DIFF, models.RawSource.HOT_CHAINS):
        magnitude = abs(feats.get("oi_diff_plain") or 0.0)
        volume = feats.get("volume") or 0.0
        prem = feats.get("premium") or 0.0
        trades = feats.get("trades") or 0.0
        return max(1.0, math.log1p(magnitude + volume + prem + trades))
    if cand.source == models.RawSource.STOCK_SCREENER:
        net_prem = abs(feats.get("call_minus_put_premium") or 0.0)
        cap = feats.get("marketcap") or 0.0
        cap_weight = 0.6 if cap and cap < 2_000_000_000 else 1.0
        if cap and cap > 50_000_000_000:
            cap_weight = 1.1
        return max(1.0, cap_weight * math.log1p(net_prem + abs(feats.get("net_call_premium") or 0.0) + abs(feats.get("net_put_premium") or 0.0)))
    return 1.0


def _score_candidate(cand: EventCandidate, stats: Dict[Tuple[models.RawSource, str], Dict[str, FeatureStat]]) -> ScoredAnomaly:
    bucket_key = (cand.source, cand.ticker)
    bucket_stats = stats.get(bucket_key, {})
    feature_payload: dict[str, dict[str, float]] = {}
    percentiles: list[float] = []
    z_scores_for_reason: list[tuple[str, float, float]] = []

    for feat, val in cand.features.items():
        if val is None:
            continue
        stat = bucket_stats.get(feat) or FeatureStat(center=0.0, scale=1.0, sorted_values=[val])
        z = (val - stat.center) / stat.scale if stat.scale else 0.0
        pct = percentile_rank(val, stat.sorted_values)
        feature_payload[feat] = {
            "value": float(val),
            "robust_z": float(z),
            "percentile": float(pct),
            "center": float(stat.center),
            "scale": float(stat.scale),
        }
        percentiles.append(float(pct))
        z_scores_for_reason.append((feat, z, pct))

    ensemble_score = float(sum(percentiles) / len(percentiles)) if percentiles else 0.0
    risk_weight = _risk_weight(cand)
    severity_score = float(ensemble_score * risk_weight)

    labels = _feature_labels(cand.source)
    z_scores_for_reason.sort(key=lambda t: abs(t[1]), reverse=True)
    reason_codes: list[str] = []
    for feat, z, pct in z_scores_for_reason[:5]:
        label = labels.get(feat, feat)
        reason_codes.append(f"{label}: z={z:.2f}, pct={pct:.2f}")

    return ScoredAnomaly(
        source=cand.source,
        ticker=cand.ticker,
        event_key=cand.event_key,
        severity_score=severity_score,
        ensemble_score=ensemble_score,
        reason_codes=reason_codes,
        feature_payload=feature_payload,
        raw_ref=cand.raw_ref,
    )


def _build_rollups(events: List[ScoredAnomaly]) -> List[TickerRollup]:
    per_ticker: dict[str, dict[str, Any]] = {}
    for ev in events:
        entry = per_ticker.setdefault(ev.ticker, {"sources": {}, "events": []})
        src = ev.source.value
        entry["events"].append(ev)
        if src not in entry["sources"]:
            entry["sources"][src] = {"max_severity": ev.severity_score, "count": 1, "ensemble": ev.ensemble_score}
        else:
            entry["sources"][src]["max_severity"] = max(entry["sources"][src]["max_severity"], ev.severity_score)
            entry["sources"][src]["count"] += 1
            entry["sources"][src]["ensemble"] = max(entry["sources"][src]["ensemble"], ev.ensemble_score)

    rollups: list[TickerRollup] = []
    for ticker, payload in per_ticker.items():
        sources = payload["sources"]
        unique_sources = len(sources)
        max_severity = max(s["max_severity"] for s in sources.values())
        ensemble_score = sum(s["ensemble"] for s in sources.values()) / unique_sources if unique_sources else 0.0
        agreement = unique_sources / 4.0 if unique_sources else 0.0
        severity_score = float(max_severity * (1 + agreement))

        reason_codes = [f"{src}: max_sev={vals['max_severity']:.2f}, count={vals['count']}" for src, vals in sources.items()]
        if unique_sources > 1:
            reason_codes.append(f"Cross-source corroboration: {unique_sources} sources (agreement={agreement:.2f})")

        feature_payload = {
            "per_source": sources,
            "top_events": [
                {
                    "source": ev.source.value,
                    "event_key": ev.event_key,
                    "severity": ev.severity_score,
                    "ensemble": ev.ensemble_score,
                    "reason_codes": ev.reason_codes,
                }
                for ev in sorted(payload["events"], key=lambda e: e.severity_score, reverse=True)[:5]
            ],
        }
        raw_ref = {"event_keys": [ev.event_key for ev in payload["events"]]}
        rollups.append(
            TickerRollup(
                ticker=ticker,
                severity_score=severity_score,
                ensemble_score=float(ensemble_score),
                reason_codes=reason_codes,
                feature_payload=feature_payload,
                raw_ref=raw_ref,
            )
        )
    rollups.sort(key=lambda r: r.severity_score, reverse=True)
    return rollups


def compute_anomalies_for_session(
    db: Session,
    session: models.Session,
    lookback_sessions: int = 30,
) -> Dict[str, Any]:
    target_session_id = session.session_id
    ctx_query = db.query(models.Session).filter(models.Session.date < session.date).order_by(models.Session.date.desc())
    if lookback_sessions > 0:
        ctx_query = ctx_query.limit(lookback_sessions)
    prior_sessions = ctx_query.all() if lookback_sessions else []
    session_ids = [target_session_id] + [s.session_id for s in prior_sessions]

    files = (
        db.query(models.RawFile)
        .filter(models.RawFile.session_id.in_(session_ids))
        .filter(models.RawFile.source.in_([
            models.RawSource.OI_DIFF,
            models.RawSource.HOT_CHAINS,
            models.RawSource.DARKPOOL_EOD,
            models.RawSource.STOCK_SCREENER,
        ]))
        .all()
    )

    files_by_session: dict[Any, list[models.RawFile]] = {}
    for rf in files:
        files_by_session.setdefault(rf.session_id, []).append(rf)

    bucket_candidates: list[EventCandidate] = []
    for sid in session_ids:
        bucket_candidates.extend(_build_candidates_for_files(files_by_session.get(sid, [])))
    stats = _build_bucket_stats(bucket_candidates)

    target_candidates = _build_candidates_for_files(files_by_session.get(target_session_id, []))
    scored_events = [_score_candidate(c, stats) for c in target_candidates if any(v is not None for v in c.features.values())]
    scored_events.sort(key=lambda ev: ev.severity_score, reverse=True)

    rollups = _build_rollups(scored_events)

    # Replace existing persisted rows for this session
    db.query(models.AnomalyEvent).filter(models.AnomalyEvent.session_id == target_session_id).delete(synchronize_session=False)
    db.query(models.AnomalyTickerRollup).filter(models.AnomalyTickerRollup.session_id == target_session_id).delete(synchronize_session=False)

    event_models = [
        models.AnomalyEvent(
            session_id=target_session_id,
            source=ev.source,
            event_key=ev.event_key,
            ticker=ev.ticker,
            severity_score=ev.severity_score,
            ensemble_score=ev.ensemble_score,
            reason_codes=ev.reason_codes,
            feature_payload=ev.feature_payload,
            raw_ref=ev.raw_ref,
        )
        for ev in scored_events
    ]
    rollup_models = [
        models.AnomalyTickerRollup(
            session_id=target_session_id,
            ticker=ru.ticker,
            severity_score=ru.severity_score,
            ensemble_score=ru.ensemble_score,
            reason_codes=ru.reason_codes,
            feature_payload=ru.feature_payload,
            raw_ref=ru.raw_ref,
        )
        for ru in rollups
    ]
    db.add_all(event_models + rollup_models)
    db.commit()

    summary = {
        "total_events": len(scored_events),
        "total_rollups": len(rollups),
        "by_source": {},
        "lookback_sessions": len(prior_sessions),
    }
    for ev in scored_events:
        summary["by_source"].setdefault(ev.source.value, 0)
        summary["by_source"][ev.source.value] += 1

    return {
        "events": scored_events,
        "rollups": rollups,
        "summary": summary,
    }
