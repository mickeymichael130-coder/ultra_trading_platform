"""
Pip and position-size helpers shared across layers.
Convention: position_size is expressed in MICRO LOTS (1 micro lot = 1000 base
units). Pip value = $0.10 per pip per micro lot for forex.

For crypto symbols (Binance), the same normalized risk-unit model is used:
a "pip" is a fixed price step so ATR/SL/TP/pip-value math stays consistent.
"""
from typing import Union

_CRYPTO_QUOTES = ("USDT", "USDC", "BUSD", "TUSD", "USD", "BTC", "ETH", "BNB")


def is_crypto_symbol(symbol: str) -> bool:
    """Heuristic: Deriv forex symbols are 'frx...'; everything else without a
    slash is treated as a crypto/CFD pair (e.g. BTCUSDT)."""
    s = symbol.upper()
    if s.startswith("FRX"):
        return False
    if "/" in s:
        return False
    return s.endswith(_CRYPTO_QUOTES)


def _crypto_base(symbol: str) -> str:
    """Strip the quote currency from a crypto symbol (BTCUSDT -> BTC)."""
    s = symbol.upper()
    for quote in _CRYPTO_QUOTES:
        if s.endswith(quote) and len(s) > len(quote):
            return s[: -len(quote)]
    return s


def get_pip_size(symbol: str) -> float:
    """Return pip size for a symbol. JPY pairs use 0.01, forex 0.0001.
    Crypto: BTC/ETH quote pairs use $1 per pip, smaller coins $0.01."""
    if is_crypto_symbol(symbol):
        base = _crypto_base(symbol)
        return 1.0 if base in ("BTC", "ETH") else 0.01
    if "JPY" in symbol:
        return 0.01
    return 0.0001


PIP_VALUE_PER_MICRO_LOT = 0.10  # $0.10 per pip per micro lot


def pnl_from_price_move(symbol: str, direction: str, entry: float, exit: float, position_size: float) -> float:
    """
    Realized P&L for a closed position in micro lots.

    Args:
        symbol: Trading symbol (determines pip size)
        direction: "BUY" or "SELL"
        entry, exit: Fill prices
        position_size: Size in micro lots

    Returns:
        P&L in dollars
    """
    if not position_size or position_size <= 0:
        position_size = 1.0

    pip = get_pip_size(symbol)
    if direction == "BUY":
        pips = (exit - entry) / pip
    else:
        pips = (entry - exit) / pip

    return pips * PIP_VALUE_PER_MICRO_LOT * position_size
