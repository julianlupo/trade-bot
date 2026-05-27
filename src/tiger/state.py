"""Core state objects for the Tiger Sovereign engine.

These hold what the bot "remembers" during a session: the opening range, the
running high/low of the day, the divergence-tracking peaks, the strike counter,
realized P&L, and the currently open trade (if any). The backtest engine and
(later) the live engine both drive these.

Money fields use Decimal — price/P&L correctness is non-negotiable (see CLAUDE.md).
Indicator values stay float (they come from indicators.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum


class Direction(str, Enum):
    LONG = "long"   # "Bison"
    SHORT = "short"  # "Wounded Buffalo"


class ExitReason(str, Enum):
    HARD_STOP = "hard_stop"
    ALARM_A = "alarm_a_flash_move"
    ALARM_B = "alarm_b_trend_death"
    ALARM_D = "alarm_d_hvp_lock"
    RATCHET_STOP = "ratchet_stop"  # stop ratcheted by Alarm C/E was then hit
    EOD_FLUSH = "eod_flush"


@dataclass
class StrikeState:
    """One open trade (entry -> exit). 'Strike' in the spec's language."""

    strike_number: int
    direction: Direction
    entry_time: datetime
    entry_price: Decimal
    shares: int
    stop_price: Decimal           # current resting STOP MARKET level
    stop_source: str = "hard"     # 'hard' | 'ratchet_c' | 'ratchet_e'
    trade_hvp_5m_adx: float = 0.0  # per-Strike peak 5m ADX (spec Trade_HVP; for Alarm D per-strike test)
    is_scaled: bool = False        # entered at 50% (Scaled Strike) and may scale in
    is_full_filled: bool = True    # False while a Scaled Strike awaits its second half
    exit_time: datetime | None = None
    exit_price: Decimal | None = None
    exit_reason: ExitReason | None = None

    @property
    def is_open(self) -> bool:
        return self.exit_price is None

    def realized_pnl(self) -> Decimal:
        if self.exit_price is None:
            return Decimal(0)
        delta = self.exit_price - self.entry_price
        if self.direction is Direction.SHORT:
            delta = -delta
        return delta * self.shares


@dataclass
class MarketState:
    """Per-session state for one ticker on one trading day."""

    ticker: str
    orh: float | None = None      # locked at 09:35:59
    orl: float | None = None      # locked at 09:35:59
    nhod: float | None = None     # running high of day
    nlod: float | None = None     # running low of day

    # Alarm E divergence tracking — updated when a new NHOD/NLOD is set.
    stored_peak_price: float | None = None
    stored_peak_rsi: float | None = None

    # Alarm D — SESSION peak of 5m ADX (HWM). Per the ORIGINAL source doc this
    # is session-wide, NOT per-strike. See OPEN_QUESTIONS.md Q1.
    session_peak_5m_adx: float = 0.0

    strikes_taken: int = 0
    realized_pnl: Decimal = Decimal(0)
    circuit_broken: bool = False

    open_strike: StrikeState | None = None
    closed_strikes: list[StrikeState] = field(default_factory=list)

    # --- opening range -------------------------------------------------- #
    def update_opening_range(self, high: float, low: float) -> None:
        """Track running OR high/low during the 09:30-09:35:59 window."""
        self.orh = high if self.orh is None else max(self.orh, high)
        self.orl = low if self.orl is None else min(self.orl, low)

    # --- running extremes + divergence peaks ---------------------------- #
    def update_extremes(self, high: float, low: float, rsi: float) -> None:
        """Update NHOD/NLOD; capture divergence peaks at each new extreme."""
        if self.nhod is None or high > self.nhod:
            self.nhod = high
            self.stored_peak_price = high
            self.stored_peak_rsi = rsi
        if self.nlod is None or low < self.nlod:
            self.nlod = low
            self.stored_peak_price = low
            self.stored_peak_rsi = rsi

    def update_session_adx_peak(self, adx_5m: float) -> None:
        if adx_5m is not None and adx_5m > self.session_peak_5m_adx:
            self.session_peak_5m_adx = adx_5m

    @property
    def in_position(self) -> bool:
        return self.open_strike is not None and self.open_strike.is_open

    @property
    def can_open_new_strike(self) -> bool:
        return (
            not self.in_position
            and self.strikes_taken < 3
            and not self.circuit_broken
        )
