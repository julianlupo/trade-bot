"""Unit tests for src/tiger/indicators.py.

Two kinds of checks:
  1. Worked examples computed by hand (RMA, EMA) — exact equality.
  2. Property/behavior checks (RSI bounds, DI dominance, VWAP reset, warmup) —
     things that must hold for the math to be correct.

The *final* acceptance test (matching the strategy author's TradingView numbers
on real bars) happens in Phase 1 with real data; see ROADMAP.md.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tiger import indicators as ind


# --------------------------------------------------------------------------- #
# wilder_rma
# --------------------------------------------------------------------------- #
def test_wilder_rma_worked_example():
    # period 3 over [1,2,3,4,5]:
    #   seed at idx2 = mean(1,2,3) = 2.0
    #   idx3 = (4-2)/3 + 2          = 2.666666...
    #   idx4 = (5-2.6667)/3 + 2.6667 = 3.444444...
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    out = ind.wilder_rma(s, 3)
    assert np.isnan(out.iloc[0]) and np.isnan(out.iloc[1])
    assert out.iloc[2] == pytest.approx(2.0)
    assert out.iloc[3] == pytest.approx(2.0 + (4.0 - 2.0) / 3.0)
    assert out.iloc[4] == pytest.approx(out.iloc[3] + (5.0 - out.iloc[3]) / 3.0)


def test_wilder_rma_handles_leading_nan():
    # A leading NaN (as produced by .diff()) should shift the seed by one.
    s = pd.Series([np.nan, 2.0, 4.0, 6.0, 8.0])
    out = ind.wilder_rma(s, 3)
    # first valid value at idx1, so seed lands at idx1+3-1 = idx3 = mean(2,4,6)=4
    assert out.iloc[:3].isna().all()
    assert out.iloc[3] == pytest.approx(4.0)


def test_wilder_rma_all_nan_when_too_short():
    s = pd.Series([1.0, 2.0])
    assert ind.wilder_rma(s, 5).isna().all()


# --------------------------------------------------------------------------- #
# ema
# --------------------------------------------------------------------------- #
def test_ema_worked_example():
    # period 2 -> alpha = 2/3, seeded with first value.
    #   e0 = 1
    #   e1 = 2/3*2 + 1/3*1 = 1.666...
    #   e2 = 2/3*3 + 1/3*1.6667 = 2.555...
    s = pd.Series([1.0, 2.0, 3.0])
    out = ind.ema(s, 2)
    a = 2.0 / 3.0
    assert out.iloc[0] == pytest.approx(1.0)
    assert out.iloc[1] == pytest.approx(a * 2 + (1 - a) * 1)
    assert out.iloc[2] == pytest.approx(a * 3 + (1 - a) * out.iloc[1])


# --------------------------------------------------------------------------- #
# rsi
# --------------------------------------------------------------------------- #
def test_rsi_pure_uptrend_is_100():
    s = pd.Series(np.arange(1, 30, dtype=float))  # strictly increasing
    out = ind.rsi(s, 15)
    assert out.dropna().eq(100.0).all()


def test_rsi_pure_downtrend_is_0():
    s = pd.Series(np.arange(30, 1, -1, dtype=float))  # strictly decreasing
    out = ind.rsi(s, 15)
    assert out.dropna().eq(0.0).all()


def test_rsi_bounded_and_warmup():
    rng = np.random.default_rng(42)
    s = pd.Series(100 + np.cumsum(rng.normal(0, 1, 200)))
    out = ind.rsi(s, 15)
    valid = out.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()
    # RSI(15) needs one diff + 15 values -> first value at index 15.
    assert out.iloc[:15].isna().all()
    assert not np.isnan(out.iloc[15])


# --------------------------------------------------------------------------- #
# adx_di
# --------------------------------------------------------------------------- #
def test_adx_di_uptrend_diplus_dominates():
    n = 60
    base = np.arange(n, dtype=float)
    high = pd.Series(base + 1.0)
    low = pd.Series(base)
    close = pd.Series(base + 0.5)
    res = ind.adx_di(high, low, close, period=14)
    tail = res.dropna().iloc[-1]
    assert tail["di_plus"] > tail["di_minus"]
    assert tail["di_minus"] == pytest.approx(0.0, abs=1e-9)
    assert tail["adx"] > 20  # a clean trend should register strength


def test_adx_di_downtrend_diminus_dominates():
    n = 60
    base = np.arange(n, 0, -1, dtype=float)
    high = pd.Series(base + 1.0)
    low = pd.Series(base)
    close = pd.Series(base + 0.5)
    res = ind.adx_di(high, low, close, period=14)
    tail = res.dropna().iloc[-1]
    assert tail["di_minus"] > tail["di_plus"]
    assert tail["di_plus"] == pytest.approx(0.0, abs=1e-9)


def test_adx_di_columns_and_warmup():
    n = 80
    rng = np.random.default_rng(7)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    high = pd.Series(close + rng.uniform(0, 1, n))
    low = pd.Series(close - rng.uniform(0, 1, n))
    res = ind.adx_di(high, pd.Series(low), pd.Series(close), period=14)
    assert list(res.columns) == ["adx", "di_plus", "di_minus"]
    # DI valid from index 14; ADX from 14 + 14 - 1 = 27.
    assert res["di_plus"].iloc[:14].isna().all()
    assert not np.isnan(res["di_plus"].iloc[14])
    assert res["adx"].iloc[:27].isna().all()
    assert not np.isnan(res["adx"].iloc[27])


# --------------------------------------------------------------------------- #
# session_vwap
# --------------------------------------------------------------------------- #
def test_session_vwap_resets_each_day():
    idx = pd.to_datetime(
        [
            "2026-05-26 09:30", "2026-05-26 09:31",
            "2026-05-27 09:30", "2026-05-27 09:31",
        ]
    ).tz_localize("America/New_York")
    high = pd.Series([10.0, 12.0, 20.0, 22.0], index=idx)
    low = pd.Series([10.0, 12.0, 20.0, 22.0], index=idx)
    close = pd.Series([10.0, 12.0, 20.0, 22.0], index=idx)
    volume = pd.Series([100.0, 100.0, 100.0, 100.0], index=idx)
    vwap = ind.session_vwap(high, low, close, volume)
    # day 1: first bar = 10; second = (10*100 + 12*100)/200 = 11
    assert vwap.iloc[0] == pytest.approx(10.0)
    assert vwap.iloc[1] == pytest.approx(11.0)
    # day 2 must NOT carry day 1: first bar = 20, second = 21
    assert vwap.iloc[2] == pytest.approx(20.0)
    assert vwap.iloc[3] == pytest.approx(21.0)


def test_session_vwap_requires_datetime_index():
    s = pd.Series([1.0, 2.0])
    with pytest.raises(TypeError):
        ind.session_vwap(s, s, s, s)


# --------------------------------------------------------------------------- #
# rolling_volume_average
# --------------------------------------------------------------------------- #
def test_rolling_volume_average():
    v = pd.Series([10.0, 20.0, 30.0, 40.0])
    out = ind.rolling_volume_average(v, window=3)
    assert out.iloc[:2].isna().all()
    assert out.iloc[2] == pytest.approx(20.0)   # mean(10,20,30)
    assert out.iloc[3] == pytest.approx(30.0)   # mean(20,30,40)
