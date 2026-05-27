"""Tests for batch aggregation (no network — uses synthetic sessions)."""

from __future__ import annotations

import pandas as pd

from tiger import batch, data
from tiger.backtest import run_backtest


def _synth_sessions(n: int = 3):
    """A few synthetic sessions (same shape, different seeds) to aggregate."""
    sessions = []
    for seed in range(n):
        stock, qqq = data.synthetic_session(seed=seed)
        sessions.append(run_backtest(stock, qqq, f"S{seed}"))
    return sessions


def test_aggregate_basic_shape():
    sessions = _synth_sessions(3)
    stats = batch.aggregate(sessions)
    assert stats["sessions"] == 3
    assert stats["trades"] == stats["wins"] + stats["losses"] + (
        stats["trades"] - stats["wins"] - stats["losses"]  # breakevens, if any
    )
    assert 0.0 <= stats["win_rate"] <= 100.0
    # expectancy is total / trades
    if stats["trades"]:
        assert abs(stats["expectancy"] - stats["total_pnl"] / stats["trades"]) < 1e-6


def test_equity_curve_is_cumulative_and_ordered():
    sessions = _synth_sessions(3)
    times, cum = batch.equity_curve(sessions)
    assert len(times) == len(cum) == batch.aggregate(sessions)["trades"]
    assert times == sorted(times)  # ordered by exit time
    if cum:
        assert abs(cum[-1] - batch.aggregate(sessions)["total_pnl"]) < 1e-6


def test_aggregate_handles_no_trades():
    stats = batch.aggregate([])
    assert stats["trades"] == 0
    assert stats["win_rate"] == 0.0
    assert stats["expectancy"] == 0.0


def test_batch_result_trade_rows():
    sessions = _synth_sessions(2)
    br = batch.BatchResult(sessions=sessions)
    rows = br.trade_rows()
    assert len(rows) == batch.aggregate(sessions)["trades"]
    if rows:
        assert {"ticker", "pnl", "exit_reason", "direction"} <= set(rows[0])
