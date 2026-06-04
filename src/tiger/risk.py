"""Risk management math: position sizing, hard stop, ratchet, circuit breaker.

All money math is Decimal. Constants come straight from the spec (Section 4):
  - $25,000 nominal position size
  - $500 hard stop per trade
  - -$1,500 daily circuit breaker
  - ratchet stops to current price +/- 0.25%
"""

from __future__ import annotations

from decimal import Decimal

from tiger.state import Direction

NOMINAL_POSITION = Decimal("25000")
MAX_LOSS_PER_TRADE = Decimal("500")
DAILY_LOSS_LIMIT = Decimal("-1500")
RATCHET_PCT = Decimal("0.0025")  # 0.25%
ENTRY_SLIPPAGE = Decimal("0.001")  # LIMIT at ask*1.001 / bid*0.999


def position_size(price: Decimal, nominal: Decimal = NOMINAL_POSITION) -> int:
    """Whole shares for the nominal position at ``price`` (floor)."""
    if price <= 0:
        raise ValueError("price must be positive")
    return int(nominal / price)


def entry_limit_price(direction: Direction, reference: Decimal) -> Decimal:
    """LIMIT entry price: ask*1.001 (long) or bid*0.999 (short).

    ``reference`` is the ask (long) or bid (short). In backtest we approximate
    both with the bar close.

    Rounded to whole cents: US equities >= $1 must be priced in penny
    increments, and a sub-penny limit price is rejected by the broker.
    """
    if direction is Direction.LONG:
        raw = reference * (Decimal(1) + ENTRY_SLIPPAGE)
    else:
        raw = reference * (Decimal(1) - ENTRY_SLIPPAGE)
    return raw.quantize(Decimal("0.01"))


def hard_stop_price(
    direction: Direction,
    fill_price: Decimal,
    shares: int,
    max_loss: Decimal = MAX_LOSS_PER_TRADE,
) -> Decimal:
    """STOP MARKET level corresponding to a ``max_loss`` dollar loss."""
    if shares <= 0:
        raise ValueError("shares must be positive")
    distance = max_loss / shares
    if direction is Direction.LONG:
        return fill_price - distance
    return fill_price + distance


def ratchet_stop(
    direction: Direction,
    current_price: Decimal,
    existing_stop: Decimal,
    pct: Decimal = RATCHET_PCT,
) -> Decimal:
    """Ratchet the stop to current price +/- ``pct``, but only ever tighter.

    Long: new = current*(1-pct); keep whichever is HIGHER (more protective).
    Short: new = current*(1+pct); keep whichever is LOWER.
    See OPEN_QUESTIONS.md Q2 — one stop, only moves favorably.
    """
    if direction is Direction.LONG:
        proposed = current_price * (Decimal(1) - pct)
        return max(existing_stop, proposed)
    proposed = current_price * (Decimal(1) + pct)
    return min(existing_stop, proposed)


def blended_entry_price(price1: Decimal, qty1: int, price2: Decimal, qty2: int) -> Decimal:
    """Share-weighted average entry after a scale-in add."""
    total = qty1 + qty2
    if total <= 0:
        raise ValueError("total shares must be positive")
    return (price1 * qty1 + price2 * qty2) / total


def circuit_breaker_tripped(
    realized_pnl: Decimal, limit: Decimal = DAILY_LOSS_LIMIT
) -> bool:
    return realized_pnl <= limit
