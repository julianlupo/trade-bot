"""Historical 1-minute bar loaders for backtesting.

Two sources:
  - ``synthetic_session`` : a deterministic, offline fake trading day. Always
    works, no network/keys. Constructed to contain a clean long ("Bison") setup
    so the engine has something to trade — used in tests and quick demos.
  - ``load_yfinance``     : real recent 1m bars (last ~7 days only) via yfinance.
    No API key needed. Volume is consolidated (good enough for a first look).
    Alpaca/Polygon loaders come in Phase 2.

All loaders return a DataFrame indexed by tz-aware America/New_York timestamps
with columns: open, high, low, close, volume — regular session (09:30-16:00) only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

ET = "America/New_York"
SESSION_COLS = ["open", "high", "low", "close", "volume"]


def _ohlcv_from_close(close: np.ndarray, index: pd.DatetimeIndex, volume: np.ndarray,
                      wick: float = 0.05) -> pd.DataFrame:
    """Build plausible OHLCV around a close path (open = prior close)."""
    open_ = np.empty_like(close)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    high = np.maximum(open_, close) + wick
    low = np.minimum(open_, close) - wick
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )


def _day_index(date: pd.Timestamp) -> pd.DatetimeIndex:
    d = date.strftime("%Y-%m-%d")
    return pd.date_range(f"{d} 09:30", f"{d} 15:59", freq="1min", tz=ET)


def synthetic_session(
    date: str = "2026-05-20", seed: int = 0, warmup_days: int = 3
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (stock_1m, qqq_1m) ending on a fabricated breakout day.

    The last day is the target: a tight opening range near $100, a clean
    breakout + sustained uptrend through late morning, then a rollover that
    trips the exit alarms. The preceding ``warmup_days`` (gentle uptrend) exist
    only so the 5-minute trend indicators are warmed up by the target open —
    exactly as prior-session data would do in live trading. QQQ drifts up the
    whole time so the long "weather" filter stays satisfied.
    """
    rng = np.random.default_rng(seed)
    target = pd.Timestamp(date)
    dates = [target - pd.Timedelta(days=warmup_days - i) for i in range(warmup_days)]
    dates.append(target)

    full_idx = pd.DatetimeIndex(np.concatenate([_day_index(d).to_numpy() for d in dates]))
    full_idx = full_idx.tz_localize(None).tz_localize(ET)
    target_len = len(_day_index(target))
    warm_len = len(full_idx) - target_len
    n_total = len(full_idx)

    # --- QQQ: ONE continuous low-noise uptrend across all days (no overnight
    # gaps, so the 5m EMA never sits stranded above price -> weather holds). ---
    qclose = 398.0 + np.linspace(0, 8.0, n_total) + rng.normal(0, 0.02, n_total)
    qvol = rng.integers(50_000, 80_000, n_total).astype(float)
    qqq = _ohlcv_from_close(qclose, full_idx, qvol, wick=0.1)

    # --- Stock: warmup drifts continuously up to ~99.8, then the target day's
    # opening range / breakout / rollover begins right where warmup left off. ---
    sclose = np.empty(n_total)
    sclose[:warm_len] = 97.0 + np.linspace(0, 2.8, warm_len)  # ends ~99.8
    tgt = sclose[warm_len:]
    for i in range(6):  # opening range ~100
        tgt[i] = 100.0 + (0.35 if i % 2 == 0 else -0.35)
    ramp_end, peak = 66, 106.0
    for i in range(6, target_len):
        if i <= ramp_end:
            tgt[i] = 100.5 + (i - 6) * (peak - 100.5) / (ramp_end - 6)
        else:
            tgt[i] = peak - (i - ramp_end) * 0.06  # rollover
    sclose += rng.normal(0, 0.02, n_total)

    svol = rng.integers(8_000, 12_000, n_total).astype(float)
    svol[warm_len + 6 : warm_len + 67] = rng.integers(28_000, 34_000, 61).astype(float)
    stock = _ohlcv_from_close(sclose, full_idx, svol)

    return stock, qqq


def load_yfinance(ticker: str, period: str = "5d") -> pd.DataFrame:
    """Real recent 1m bars via yfinance (regular session, ET). Lazy import."""
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("yfinance not installed: `uv add yfinance`") from exc

    raw = yf.download(ticker, period=period, interval="1m", prepost=False,
                      auto_adjust=False, progress=False)
    if raw is None or raw.empty:
        raise RuntimeError(f"No data returned for {ticker} (yfinance may be rate-limited)")

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw = raw.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]

    idx = raw.index
    raw.index = idx.tz_convert(ET) if idx.tz is not None else idx.tz_localize("UTC").tz_convert(ET)
    session = raw.between_time("09:30", "15:59")
    return session.astype(float)


def split_by_day(bars: pd.DataFrame) -> dict[pd.Timestamp, pd.DataFrame]:
    """Group multi-day 1m bars into {date: one-day DataFrame}."""
    return {d: g for d, g in bars.groupby(bars.index.normalize())}
