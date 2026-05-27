"""The Sentinels — exit alarms A through E (spec Addendum + Section 1).

Each alarm is a pure function returning an ``AlarmResult``. They are
independent; the engine runs all that apply each bar and acts on every fire.

  A  Flash Move    1m move > 1% against position        -> MARKET EXIT
  B  Trend Death   5m candle closes across 5m 9-EMA      -> MARKET EXIT
  C  Tiger Grip    3 consecutive 1m ADX declines         -> RATCHET STOP +/-0.25%
  D  HVP Lock      5m ADX < 75% session peak (HWM)       -> MARKET EXIT
  E  Divergence    new extreme on weaker RSI             -> RATCHET STOP +/-0.25%

Divergence (Alarm E) is also used pre-entry as a binary filter (Section 1).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from tiger.state import Direction


class AlarmAction(str, Enum):
    NONE = "none"
    EXIT = "exit"
    RATCHET = "ratchet"


@dataclass(frozen=True)
class AlarmResult:
    name: str
    action: AlarmAction


_NONE = AlarmResult("none", AlarmAction.NONE)

# Flash-move threshold and the bar-to-bar measurement basis are not pinned
# down precisely in the source ("1m price move > 1% against position"). We use
# close-to-close 1m return. See OPEN_QUESTIONS.md Q8.  # OPEN-Q8
FLASH_MOVE_PCT = 0.01
HVP_LOCK_FRACTION = 0.75


def divergence(
    direction: Direction,
    current_price: float,
    current_rsi: float,
    stored_peak_price: float | None,
    stored_peak_rsi: float | None,
) -> bool:
    """Alarm E core test (Section 1.2).

    Bison (long): new price high on LOWER rsi  -> price > peak AND rsi < peak_rsi
    Buffalo (short): new price low on HIGHER rsi -> price < peak AND rsi > peak_rsi
    Strict inequalities per the spec.
    """
    if stored_peak_price is None or stored_peak_rsi is None:
        return False
    if direction is Direction.LONG:
        return current_price > stored_peak_price and current_rsi < stored_peak_rsi
    return current_price < stored_peak_price and current_rsi > stored_peak_rsi


def alarm_a_flash_move(
    direction: Direction, prev_close: float | None, close: float
) -> AlarmResult:
    """A: a >1% adverse 1-minute (close-to-close) move."""
    if prev_close is None or prev_close == 0:
        return _NONE
    ret = (close - prev_close) / prev_close
    adverse = -ret if direction is Direction.LONG else ret
    return AlarmResult("alarm_a", AlarmAction.EXIT) if adverse > FLASH_MOVE_PCT else _NONE


def alarm_b_trend_death(
    direction: Direction, completed_5m_close: float | None, ema9_5m: float | None
) -> AlarmResult:
    """B: a completed 5m candle closes on the wrong side of the 5m 9-EMA.

    Only meaningful to call when a 5m bar has just completed; the engine gates that.
    """
    if completed_5m_close is None or ema9_5m is None:
        return _NONE
    if direction is Direction.LONG and completed_5m_close < ema9_5m:
        return AlarmResult("alarm_b", AlarmAction.EXIT)
    if direction is Direction.SHORT and completed_5m_close > ema9_5m:
        return AlarmResult("alarm_b", AlarmAction.EXIT)
    return _NONE


def alarm_c_tiger_grip(recent_adx_1m: list[float]) -> AlarmResult:
    """C: 3 consecutive declines in 1m ADX (needs the last 4 values)."""
    vals = [v for v in recent_adx_1m[-4:] if v is not None]
    if len(vals) < 4:
        return _NONE
    a, b, c, d = vals[-4], vals[-3], vals[-2], vals[-1]
    if a > b > c > d:
        return AlarmResult("alarm_c", AlarmAction.RATCHET)
    return _NONE


def alarm_d_hvp_lock(
    adx_5m: float | None, session_peak_5m_adx: float
) -> AlarmResult:
    """D: current 5m ADX drops below 75% of the SESSION peak 5m ADX."""
    if adx_5m is None or session_peak_5m_adx <= 0:
        return _NONE
    if adx_5m < HVP_LOCK_FRACTION * session_peak_5m_adx:
        return AlarmResult("alarm_d", AlarmAction.EXIT)
    return _NONE


def alarm_e_divergence(
    direction: Direction,
    current_price: float,
    current_rsi: float,
    stored_peak_price: float | None,
    stored_peak_rsi: float | None,
) -> AlarmResult:
    """E (post-entry sentinel): divergence -> ratchet stop."""
    if divergence(direction, current_price, current_rsi, stored_peak_price, stored_peak_rsi):
        return AlarmResult("alarm_e", AlarmAction.RATCHET)
    return _NONE
