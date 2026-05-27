"""Entry logic — Bison (long) and Wounded Buffalo (short). Spec Sections 2-3.

Pure functions evaluated on each 1m bar close. The engine assembles the inputs
(indicators, levels, the last two 1m closes) and calls ``check_entry``.

Phases, in order (abort on first failure):
  1   Weather    — QQQ trending the same direction (5m 9-EMA + session VWAP)
  2   Permit     — two consecutive 1m closes beyond the target level
  2.5 Volume Gate— 1m vol >= 55-bar avg (only enforced after 10:00 ET)
  3   Authority  — 5m DI(side) > 25 AND 5m ADX > 20 AND divergence == False
  3.5 Sizing     — DI(side) thresholds decide full vs scaled (see note)

Sizing (Phase 3.5): 1m DI(side) > 30 => Full Strike (100%); in [25, 30] =>
Scaled Strike (50% starter, may add the second half via ``scale_in_ok``);
< 25 => do not enter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from tiger.alarms import divergence
from tiger.state import Direction

VOLUME_GATE_START = time(10, 0, 0)  # gate enforced at/after 10:00 ET
DI_AUTHORITY_MIN = 25.0   # 5m DI(side) authority
ADX_TREND_MIN = 20.0      # 5m ADX trend-exists
DI_ENTRY_MIN = 25.0       # 1m DI(side) minimum to enter at all (sizing floor)
DI_FULL_SIZE = 30.0       # 1m DI(side) for full size (v2 sizing)


@dataclass(frozen=True)
class EntrySignal:
    direction: Direction
    full_size: bool  # True if 1m DI(side) > 30; informational in v1


def two_consecutive_beyond(
    closes: list[float], level: float, direction: Direction
) -> bool:
    """Last two 1m closes both beyond the level (above for long, below for short)."""
    if level is None or len(closes) < 2:
        return False
    a, b = closes[-2], closes[-1]
    if direction is Direction.LONG:
        return a > level and b > level
    return a < level and b < level


def weather_ok(
    direction: Direction,
    qqq_close_5m: float | None,
    qqq_ema9_5m: float | None,
    qqq_price: float | None,
    qqq_vwap_5m: float | None,
) -> bool:
    """Phase 1: QQQ aligned with trade direction."""
    if None in (qqq_close_5m, qqq_ema9_5m, qqq_price, qqq_vwap_5m):
        return False
    if direction is Direction.LONG:
        return qqq_close_5m > qqq_ema9_5m and qqq_price > qqq_vwap_5m
    return qqq_close_5m < qqq_ema9_5m and qqq_price < qqq_vwap_5m


def volume_ok(volume: float, vol_avg_55: float | None, bar_time: time) -> bool:
    """Phase 2.5: only enforced at/after 10:00 ET; always passes before."""
    if bar_time < VOLUME_GATE_START:
        return True
    if vol_avg_55 is None:
        return False  # can't confirm institutional volume -> fail the gate
    return volume >= vol_avg_55  # OPEN_QUESTIONS.md Q3: '>=' confirmed by source


def authority_ok(
    direction: Direction,
    di_plus_5m: float | None,
    di_minus_5m: float | None,
    adx_5m: float | None,
    divergent: bool,
) -> bool:
    """Phase 3: higher-timeframe authority + momentum + no divergence."""
    if adx_5m is None or adx_5m <= ADX_TREND_MIN:
        return False
    if divergent:
        return False
    di_side = di_plus_5m if direction is Direction.LONG else di_minus_5m
    return di_side is not None and di_side > DI_AUTHORITY_MIN


def sizing_ok(direction: Direction, di_plus_1m: float | None, di_minus_1m: float | None):
    """Phase 3.5: returns (allowed, full_size). <25 => not allowed."""
    di_side = di_plus_1m if direction is Direction.LONG else di_minus_1m
    if di_side is None or di_side < DI_ENTRY_MIN:
        return False, False
    return True, di_side > DI_FULL_SIZE


def scale_in_ok(
    direction: Direction,
    di_plus_1m: float | None,
    di_minus_1m: float | None,
    made_new_extreme: bool,
    divergent: bool,
) -> bool:
    """Phase 5: add the second 50% of a Scaled Strike.

    Long: 1m DI+ > 30 AND new NHOD set AND Alarm E == False.
    Short: 1m DI- > 30 AND new NLOD set AND Alarm E == False.
    """
    if not made_new_extreme or divergent:
        return False
    di_side = di_plus_1m if direction is Direction.LONG else di_minus_1m
    return di_side is not None and di_side > DI_FULL_SIZE


def check_entry(
    direction: Direction,
    *,
    closes: list[float],
    level: float,
    is_strike1: bool,
    qqq_close_5m: float | None,
    qqq_ema9_5m: float | None,
    qqq_price: float | None,
    qqq_vwap_5m: float | None,
    volume: float,
    vol_avg_55: float | None,
    bar_time: time,
    di_plus_5m: float | None,
    di_minus_5m: float | None,
    adx_5m: float | None,
    di_plus_1m: float | None,
    di_minus_1m: float | None,
    current_price: float,
    current_rsi: float,
    stored_peak_price: float | None,
    stored_peak_rsi: float | None,
) -> EntrySignal | None:
    """Run all entry phases for one direction. Returns a signal or None."""
    # Phase 1
    if not weather_ok(direction, qqq_close_5m, qqq_ema9_5m, qqq_price, qqq_vwap_5m):
        return None
    # Phase 2
    if not two_consecutive_beyond(closes, level, direction):
        return None
    # Phase 2.5
    if not volume_ok(volume, vol_avg_55, bar_time):
        return None
    # Phase 3 — divergence pre-entry filter applies to Strikes 2/3 only (Strike 1 exempt)
    divergent = False
    if not is_strike1:
        divergent = divergence(
            direction, current_price, current_rsi, stored_peak_price, stored_peak_rsi
        )
    if not authority_ok(direction, di_plus_5m, di_minus_5m, adx_5m, divergent):
        return None
    # Phase 3.5
    allowed, full = sizing_ok(direction, di_plus_1m, di_minus_1m)
    if not allowed:
        return None
    return EntrySignal(direction=direction, full_size=full)
