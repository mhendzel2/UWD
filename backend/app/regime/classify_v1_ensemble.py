from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from app.db import models

DEFAULT_WEIGHTS = {"short": 0.33, "long": 0.33, "mixed": 0.34}
WEIGHT_FLOOR = 0.2
MAX_WEEKLY_DELTA = 0.05
EWMA_ALPHA = 0.3


@dataclass
class Vote:
    label: models.RegimeLabel
    confidence: float
    reasons: List[str]


def _confidence(count: int, total: int) -> float:
    return round(min(1.0, count / max(total, 1)), 3)


def _short_classifier(feature: models.FeaturesUnderlyingDay) -> Vote:
    signals = []
    if feature.hc_sweep_dominant:
        signals.append("sweep_dominant")
    if feature.bot_overpay_present:
        signals.append("bot_overpay")
    if feature.bot_aggressive_present:
        signals.append("bot_aggressive")
    if feature.hc_liquidity_churn:
        signals.append("liquidity_churn")
    if feature.intent_persistence_3d is not None and feature.intent_persistence_3d < 0.4:
        signals.append("low_intent_persistence")
    label = models.RegimeLabel.TREND_RISK if len(signals) >= 2 else models.RegimeLabel.MIXED_NO_TRADE
    if feature.oi_symmetric and not feature.hc_liquidity_churn:
        label = models.RegimeLabel.PIN_RANGE
    return Vote(label=label, confidence=_confidence(len(signals), 5), reasons=signals)


def _long_classifier(feature: models.FeaturesUnderlyingDay) -> Vote:
    signals = []
    if feature.oi_symmetric:
        signals.append("oi_symmetric")
    if feature.oi_multileg_dominant:
        signals.append("oi_multileg")
    if feature.hc_multileg_dominant:
        signals.append("hc_multileg")
    if feature.dp_meaningful:
        signals.append("darkpool_meaningful")
    if feature.oi_persistence_3d is not None and feature.oi_persistence_3d >= 0.6:
        signals.append("high_oi_persistence")
    label = models.RegimeLabel.PIN_RANGE if len(signals) >= 3 else models.RegimeLabel.MIXED_NO_TRADE
    return Vote(label=label, confidence=_confidence(len(signals), 5), reasons=signals)


def _mixed_classifier(feature: models.FeaturesUnderlyingDay) -> Vote:
    signals = []
    if feature.regime_switch_rate_10d and feature.regime_switch_rate_10d > 0.4:
        signals.append("high_switch_rate")
    if feature.intent_persistence_3d is not None and feature.intent_persistence_3d < 0.3:
        signals.append("intent_choppy")
    if feature.hot_chain_persistence_3d is not None and feature.hot_chain_persistence_3d < 0.3:
        signals.append("hot_chain_turnover")
    if feature.hc_liquidity_churn and feature.oi_multileg_dominant:
        signals.append("flow_conflict")
    label = models.RegimeLabel.MIXED_NO_TRADE if signals else models.RegimeLabel.PIN_RANGE
    if feature.hc_sweep_dominant and feature.ss_implied_move_high:
        label = models.RegimeLabel.TREND_RISK
        signals.append("sweep_plus_high_move")
    return Vote(label=label, confidence=_confidence(len(signals), 4), reasons=signals)


def _combine_votes(votes: Dict[str, Vote], weights: Dict[str, float]) -> Tuple[models.RegimeLabel, float, Dict[str, Any]]:
    label_scores: dict[models.RegimeLabel, float] = {l: 0.0 for l in models.RegimeLabel}
    for horizon, vote in votes.items():
        w = weights.get(horizon, 0.0)
        label_scores[vote.label] += vote.confidence * w
    label = max(label_scores.items(), key=lambda kv: kv[1])[0]
    total_weight = sum(weights.values()) or 1.0
    confidence = round(label_scores[label] / total_weight, 3)
    component_payload = {
        k: {"label": v.label.value, "confidence": v.confidence, "reasons": v.reasons} for k, v in votes.items()
    }
    return label, confidence, component_payload


def _load_weights(db: Session, asof_date: date) -> Dict[str, float]:
    latest = (
        db.query(models.ModelWeights)
        .filter(models.ModelWeights.asof_date <= asof_date, models.ModelWeights.version == "v1")
        .order_by(models.ModelWeights.asof_date.desc())
        .first()
    )
    if latest:
        stored = latest.weights or {}
        return {**DEFAULT_WEIGHTS, **{k: float(v) for k, v in stored.items()}}
    return DEFAULT_WEIGHTS.copy()


def _map_outcome(label: models.OutcomeLabel | None) -> models.RegimeLabel | None:
    if not label:
        return None
    if label == models.OutcomeLabel.PIN_RANGE:
        return models.RegimeLabel.PIN_RANGE
    if label == models.OutcomeLabel.TREND:
        return models.RegimeLabel.TREND_RISK
    return models.RegimeLabel.MIXED_NO_TRADE


def _component_accuracy(db: Session, asof_date: date) -> Dict[str, float]:
    rows = (
        db.query(models.EnsembleDecision, models.Session, models.OutcomeDay)
        .join(models.Session, models.EnsembleDecision.session_id == models.Session.session_id)
        .join(
            models.OutcomeDay,
            (models.OutcomeDay.trade_date == models.EnsembleDecision.asof_date)
            & (models.OutcomeDay.underlying == models.EnsembleDecision.underlying),
        )
        .filter(models.Session.date < asof_date)
        .all()
    )
    scores: dict[str, float] = {"short": 0.0, "long": 0.0, "mixed": 0.0}
    counts: dict[str, int] = {"short": 0, "long": 0, "mixed": 0}
    for ed, _, outcome in rows:
        target = _map_outcome(outcome.realized_label_manual)
        if not target:
            continue
        votes = ed.component_votes or {}
        for horizon in scores.keys():
            vote = votes.get(horizon)
            if not vote:
                continue
            counts[horizon] += 1
            predicted = vote.get("label")
            try:
                pred_label = models.RegimeLabel(predicted)
            except Exception:
                pred_label = None
            if not pred_label:
                continue
            if pred_label == target:
                scores[horizon] += 1
            elif pred_label == models.RegimeLabel.TREND_RISK and target == models.RegimeLabel.PIN_RANGE:
                scores[horizon] -= 1
    accuracies: dict[str, float] = {}
    for horizon, total in counts.items():
        accuracies[horizon] = scores[horizon] / total if total else 0.0
    return accuracies


def _enough_outcomes(db: Session, asof_date: date) -> bool:
    outcomes = db.query(models.OutcomeDay).filter(models.OutcomeDay.trade_date <= asof_date).all()
    friday_labeled = [o for o in outcomes if o.trade_date.weekday() == 4 and o.realized_label_manual]
    return len(friday_labeled) >= 12


def _update_weights(db: Session, asof_date: date, current: Dict[str, float]) -> Dict[str, float]:
    if asof_date.weekday() != 4:
        return current
    if not _enough_outcomes(db, asof_date):
        return current
    accuracies = _component_accuracy(db, asof_date)
    updated: dict[str, float] = {}
    for horizon, weight in current.items():
        acc = max(0.0, accuracies.get(horizon, 0.0))
        target = weight * (1 - EWMA_ALPHA) + acc * EWMA_ALPHA
        delta = max(min(target - weight, MAX_WEEKLY_DELTA), -MAX_WEEKLY_DELTA)
        updated[horizon] = max(WEIGHT_FLOOR, weight + delta)
    total = sum(updated.values()) or 1.0
    normalized = {k: round(v / total, 4) for k, v in updated.items()}
    record = (
        db.query(models.ModelWeights)
        .filter(models.ModelWeights.asof_date == asof_date, models.ModelWeights.version == "v1")
        .one_or_none()
    )
    if record:
        record.weights = normalized
        record.updated_at = datetime.utcnow()
    else:
        record = models.ModelWeights(asof_date=asof_date, weights=normalized, version="v1")
        db.add(record)
    return normalized


def classify_ensemble(db: Session, feature: models.FeaturesUnderlyingDay, asof_date: date) -> models.EnsembleDecision:
    weights = _load_weights(db, asof_date)
    weights = _update_weights(db, asof_date, weights)

    votes = {
        "short": _short_classifier(feature),
        "long": _long_classifier(feature),
        "mixed": _mixed_classifier(feature),
    }
    label, confidence, component_payload = _combine_votes(votes, weights)
    stability = {
        "oi_persistence_3d": feature.oi_persistence_3d,
        "hot_chain_persistence_3d": feature.hot_chain_persistence_3d,
        "intent_persistence_3d": feature.intent_persistence_3d,
        "regime_switch_rate_10d": feature.regime_switch_rate_10d,
    }

    ensemble = models.EnsembleDecision(
        session_id=feature.session_id,
        underlying=feature.underlying,
        asof_date=feature.asof_date,
        ensemble_label=label,
        ensemble_confidence=confidence,
        horizon_weights=weights,
        component_votes=component_payload,
        stability_metrics=stability,
        ensemble_version="v1",
        computed_at=datetime.utcnow(),
    )
    return ensemble
