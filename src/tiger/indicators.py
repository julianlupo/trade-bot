"""Technical indicators, hand-rolled to match TradingView.

The Tiger Sovereign strategy reads these exact values to make entry/exit
decisions, so they must match the strategy author's TradingView charts. We
deliberately avoid pandas-ta / ta-lib: their ADX/DI math does not reliably
match TradingView, and they add fragile dependencies. See CLAUDE.md.

All functions take and return pandas objects aligned to the input index.
Indicator math uses float (NOT Decimal) — Decimal is reserved for order prices
and P&L (see risk.py / broker.py when built).

We mirror these TradingView Pine `ta.*` built-ins exactly:
  - ta.rma  : Wilder's moving average (RMA), seeded with an SMA.
  - ta.rsi  : 100 - 100/(1+rs), rs = rma(gain)/rma(loss).
  - ta.dmi  : +DI / -DI / ADX from rma-smoothed +DM / -DM / TR.
  - ta.ema  : exponential MA, alpha = 2/(n+1), seeded with the first value.
  - ta.vwap : cumulative typical-price*volume / cumulative volume, per session.

Acceptance gate: these are unit-tested for internal correctness here, but the
*final* sign-off is matching the strategy author's TradingView numbers on real
bars (see ROADMAP.md, Phase 1).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = [
    "wilder_rma",
    "ema",
    "rsi",
    "adx_di",
    "session_vwap",
    "rolling_volume_average",
]


def wilder_rma(series: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing (RMA), matching TradingView ``ta.rma``.

    Seeded with the simple average of the first ``period`` valid values, then
    recursively ``rma[i] = alpha * x[i] + (1 - alpha) * rma[i-1]`` with
    ``alpha = 1 / period``. Leading positions (and any leading NaNs in the
    input) are NaN until the seed point.
    """
    if period <= 0:
        raise ValueError("period must be positive")

    values = series.to_numpy(dtype=float)
    n = values.size
    out = np.full(n, np.nan, dtype=float)

    valid = np.flatnonzero(~np.isnan(values))
    if valid.size < period:
        return pd.Series(out, index=series.index, name=series.name)

    start = int(valid[0])
    seed_idx = start + period - 1
    out[seed_idx] = values[start : start + period].mean()

    alpha = 1.0 / period
    prev = out[seed_idx]
    for i in range(seed_idx + 1, n):
        prev = alpha * values[i] + (1.0 - alpha) * prev
        out[i] = prev

    return pd.Series(out, index=series.index, name=series.name)


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average, matching TradingView ``ta.ema``.

    ``alpha = 2 / (period + 1)``, seeded with the first value (Pine seeds EMA
    with ``src[0]``, which is exactly ``pandas.ewm(adjust=False)``).
    """
    if period <= 0:
        raise ValueError("period must be positive")
    return series.ewm(span=period, adjust=False).mean()


def rsi(close: pd.Series, period: int = 15) -> pd.Series:
    """Relative Strength Index, matching TradingView ``ta.rsi``.

    Default period 15 per the Tiger Sovereign spec. Uses Wilder RMA of gains
    and losses. RSI is 100 when there are no losses in the window, 0 when there
    are no gains.
    """
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = wilder_rma(gain, period)
    avg_loss = wilder_rma(loss, period)

    rs = avg_gain / avg_loss
    out = 100.0 - 100.0 / (1.0 + rs)

    # avg_loss == 0 -> pure uptrend -> RSI 100; avg_gain == 0 -> pure down -> 0.
    out = out.where(avg_loss != 0.0, 100.0)
    out = out.where(~((avg_gain == 0.0) & (avg_loss == 0.0)), 0.0)
    out[avg_gain.isna() | avg_loss.isna()] = np.nan
    return pd.Series(out, index=close.index, name="rsi")


def adx_di(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
    adx_period: int | None = None,
) -> pd.DataFrame:
    """ADX, +DI and -DI, matching TradingView ``ta.dmi``.

    Returns a DataFrame with columns ``adx``, ``di_plus``, ``di_minus``.
    ``period`` smooths the directional movement / true range (DI length);
    ``adx_period`` smooths DX into ADX (defaults to ``period``). The Tiger
    Sovereign spec uses 14 for both.

    First bar of +DM / -DM / TR is NaN (no prior bar), so warmup matches
    TradingView: DI valid from index ``period``, ADX from ``period + adx_period - 1``.
    """
    adx_period = period if adx_period is None else adx_period

    prev_close = close.shift(1)
    true_range = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    true_range.iloc[0] = np.nan  # no prior close -> undefined, like Pine ta.tr

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0.0), up_move, 0.0),
        index=high.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0.0), down_move, 0.0),
        index=high.index,
    )
    plus_dm.iloc[0] = np.nan
    minus_dm.iloc[0] = np.nan

    atr = wilder_rma(true_range, period)
    plus_di = 100.0 * wilder_rma(plus_dm, period) / atr
    minus_di = 100.0 * wilder_rma(minus_dm, period) / atr

    di_sum = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum
    adx = wilder_rma(dx, adx_period)

    return pd.DataFrame(
        {"adx": adx, "di_plus": plus_di, "di_minus": minus_di},
        index=high.index,
    )


def session_vwap(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
) -> pd.Series:
    """Session-anchored VWAP, matching TradingView ``ta.vwap``.

    Typical price = (high + low + close) / 3, accumulated within each trading
    day and reset at the first bar of the next day. The index must be a
    tz-aware (ET) DatetimeIndex; anchoring is by calendar date in that tz.

    The spec anchors VWAP to 09:30 ET. The caller is responsible for passing
    regular-session bars only (09:30-16:00 ET) so the anchor lands on the open;
    pre-market bars in the input would shift the anchor earlier.
    """
    if not isinstance(high.index, pd.DatetimeIndex):
        raise TypeError("session_vwap requires a DatetimeIndex")

    typical = (high + low + close) / 3.0
    pv = typical * volume
    day = pd.Index(high.index.date, name="session")

    cum_pv = pv.groupby(day).cumsum()
    cum_vol = volume.groupby(day).cumsum().replace(0.0, np.nan)
    return pd.Series((cum_pv / cum_vol).to_numpy(), index=high.index, name="vwap")


def rolling_volume_average(volume: pd.Series, window: int = 55) -> pd.Series:
    """Trailing simple average of the last ``window`` bar volumes.

    NaN until ``window`` bars are available. Per the spec, the Volume Gate
    compares the current bar's volume to this (default 55-bar) average.
    """
    if window <= 0:
        raise ValueError("window must be positive")
    return volume.rolling(window=window, min_periods=window).mean()
