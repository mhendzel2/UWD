import re
from typing import Mapping, Any


def derive_underlying(row: Mapping[str, Any]) -> str:
    """Best-effort extraction of underlying symbol from varied dataset rows."""
    for key in (
        "underlying",
        "underlying_symbol",
        "underlyingsymbol",
        "underlyingSymbol",
        "symbol",
        "ticker",
    ):
        val = row.get(key)
        if val:
            return str(val).strip().upper()
    option_symbol = row.get("option_symbol")
    if option_symbol:
        match = re.match(r"([A-Za-z]+)", str(option_symbol))
        if match:
            return match.group(1).upper()
    return "UNKNOWN"
