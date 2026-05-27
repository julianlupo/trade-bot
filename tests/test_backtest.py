"""Integration test: the full engine on the deterministic synthetic session."""

from __future__ import annotations

from tiger import data
from tiger.backtest import run_backtest


def test_synthetic_session_produces_a_long_trade():
    stock, qqq = data.synthetic_session(seed=0)
    result = run_backtest(stock, qqq, "SYNTH")

    # opening range locked
    assert result.state.orh is not None and result.state.orl is not None

    # the engineered breakout should produce at least one long trade
    assert len(result.trades) >= 1
    first = result.trades[0]
    assert first.direction.value == "long"
    assert first.exit_reason is not None          # it exited cleanly
    assert first.exit_time > first.entry_time

    # every trade obeys the ~$500 hard-stop floor (loss never far beyond it)
    for t in result.trades:
        assert t.realized_pnl() >= -600            # small slack for fill modeling


def test_no_more_than_three_strikes():
    stock, qqq = data.synthetic_session(seed=0)
    result = run_backtest(stock, qqq, "SYNTH")
    assert result.state.strikes_taken <= 3
