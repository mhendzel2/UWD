from typing import Dict, Any

from app.db import models


def build_stability_snapshot(feature: models.FeaturesUnderlyingDay) -> Dict[str, Any]:
    """Lightweight interpretability snapshot for v1 outputs."""
    return {
        "oi_persistence_3d": feature.oi_persistence_3d,
        "hot_chain_persistence_3d": feature.hot_chain_persistence_3d,
        "intent_persistence_3d": feature.intent_persistence_3d,
        "regime_last": feature.regime_last.value if feature.regime_last else None,
        "regime_switch_rate_10d": feature.regime_switch_rate_10d,
        "range_pct_5d_mean": feature.range_pct_5d_mean,
        "range_pct_5d_std": feature.range_pct_5d_std,
        "volume_to_avg30": feature.volume_to_avg30,
    }
