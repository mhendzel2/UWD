from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OptionsSignalsConfig:
    market_tz: str = "America/New_York"
    contract_multiplier: int = 100
    uoa_window: int = 20
    zscore_window: int = 60
    iv_rank_window: int = 252
    term_front_min_days: int = 7
    term_back_min_days: int = 60
    term_back_max_days: int = 90


DEFAULT_CONFIG = OptionsSignalsConfig()

