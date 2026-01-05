from __future__ import annotations

from trade_surveillance.options_pricing import BlackScholesInputs, black_scholes_fair_value


def test_black_scholes_reference_values() -> None:
    # Classic reference: S=100, K=100, r=5%, sigma=20%, T=1y, q=0
    params = BlackScholesInputs(spot=100.0, strike=100.0, t_years=1.0, rate=0.05, dividend_yield=0.0, iv=0.20)
    call = black_scholes_fair_value(params=params, option_type="CALL")
    put = black_scholes_fair_value(params=params, option_type="PUT")

    # Known approximate values
    assert abs(call - 10.4506) < 1e-2
    assert abs(put - 5.5735) < 1e-2
