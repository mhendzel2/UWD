from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class BlackScholesInputs:
    spot: float
    strike: float
    t_years: float
    rate: float = 0.04
    dividend_yield: float = 0.0
    iv: float = 0.50


def _norm_cdf(x: float) -> float:
    # Standard normal CDF using erf; avoids scipy dependency.
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black_scholes_fair_value(*, params: BlackScholesInputs, option_type: str) -> float:
    """Compute Black–Scholes fair value for European options.

    Inputs:
      - spot, strike: underlying spot and strike
      - t_years: time to expiry in years
      - rate: continuously-compounded risk-free rate
      - dividend_yield: continuous dividend yield
      - iv: volatility (sigma)
    """

    option_type_u = str(option_type).upper()
    if option_type_u not in {"CALL", "PUT"}:
        raise ValueError("option_type must be CALL or PUT")

    s = float(params.spot)
    k = float(params.strike)
    t = float(params.t_years)
    r = float(params.rate)
    q = float(params.dividend_yield)
    sig = float(params.iv)

    if not (math.isfinite(s) and math.isfinite(k) and math.isfinite(t) and math.isfinite(r) and math.isfinite(q) and math.isfinite(sig)):
        return float("nan")
    if s <= 0 or k <= 0:
        return float("nan")
    if t <= 0:
        # At expiry: intrinsic value.
        if option_type_u == "CALL":
            return max(0.0, s - k)
        return max(0.0, k - s)
    if sig <= 0:
        # No-vol limit: discounted intrinsic under forward.
        f = s * math.exp((r - q) * t)
        if option_type_u == "CALL":
            return math.exp(-r * t) * max(0.0, f - k)
        return math.exp(-r * t) * max(0.0, k - f)

    sqrt_t = math.sqrt(t)
    d1 = (math.log(s / k) + (r - q + 0.5 * sig * sig) * t) / (sig * sqrt_t)
    d2 = d1 - sig * sqrt_t

    df_r = math.exp(-r * t)
    df_q = math.exp(-q * t)

    if option_type_u == "CALL":
        return df_q * s * _norm_cdf(d1) - df_r * k * _norm_cdf(d2)
    # PUT
    return df_r * k * _norm_cdf(-d2) - df_q * s * _norm_cdf(-d1)
