from datetime import date, datetime, timedelta
from typing import Any, Dict

from app.db.models import Plan, PlanType, RegimeDecision


def _infer_direction(feature_context: Dict[str, Any]) -> str:
    oi = feature_context.get("oi", {})
    call_oi = oi.get("call_oi", 0) or 0
    put_oi = oi.get("put_oi", 0) or 0
    return "CALL" if call_oi >= put_oi else "PUT"


def build_plan(decision: RegimeDecision, trade_date: date | None = None) -> Plan:
    trade_date = trade_date or (decision.asof_date + timedelta(days=1))
    feature_ctx = decision.feature.numeric_context if decision.feature else {}

    if decision.regime_label == decision.regime_label.TREND_RISK:
        direction = _infer_direction(feature_ctx)
        staged_contracts = [
            {"direction": direction, "size": 1, "notes": "Stage smallest size until breach confirms"}
        ]
        entry_conditions = {
            "breach_reference": "dominant OI wall",
            "direction": direction,
            "confirmations": ["volume expansion", "1m sustained move"],
        }
        risk_limits = {"max_loss_pct": 0.5, "hard_stop_ticks": 5}
        plan_type = PlanType.TREND_BREACH_CONDITIONAL
    else:
        staged_contracts = [{"notes": "No trade until wall breach", "direction": None}]
        entry_conditions = {"note": "Pin/range or mixed. Stand down unless wall breach confirmed."}
        risk_limits = {"note": "No capital at risk until breach."}
        plan_type = PlanType.NO_TRADE

    return Plan(
        session_id=decision.session_id,
        underlying=decision.underlying,
        trade_date=trade_date,
        plan_type=plan_type,
        staged_contracts=staged_contracts,
        entry_conditions=entry_conditions,
        risk_limits=risk_limits,
        regime=decision,
    )
