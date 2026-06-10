"""Multi-day / multi-ticker batch backtest + aggregate expectancy stats.

This is the module that actually answers "does the strategy make money?" — one
day proves the machine runs, but only many sessions reveal an edge (or its
absence). We run the engine across every shared session for a set of tickers
and aggregate the trade outcomes.

DATA REALITY: free yfinance only serves ~7 calendar days of 1m bars, so a batch
here spans a handful of sessions per ticker — enough for a first read, NOT a
statistically robust verdict. A real expectancy study needs the deeper history
that comes with Phase 2's paid data. See ROADMAP.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tiger.backtest import SessionResult, run_backtest
from tiger.state import StrikeState


@dataclass
class BatchResult:
    sessions: list[SessionResult] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # tickers that failed to load

    @property
    def trades(self) -> list[StrikeState]:
        return [t for s in self.sessions for t in s.trades]

    def stats(self) -> dict:
        return aggregate(self.sessions)

    def equity_curve(self):
        return equity_curve(self.sessions)

    def trade_rows(self) -> list[dict]:
        rows = []
        for s in self.sessions:
            for t in s.trades:
                rows.append({
                    "ticker": s.ticker,
                    "date": s.date,
                    "strike": t.strike_number,
                    "direction": t.direction.value,
                    "shares": t.shares,
                    "entry": float(t.entry_price),
                    "exit": float(t.exit_price),
                    "exit_reason": t.exit_reason.value if t.exit_reason else "",
                    "pnl": float(t.realized_pnl()),
                    "entry_time": t.entry_time,
                    "exit_time": t.exit_time,
                })
        return rows


def aggregate(sessions: list[SessionResult]) -> dict:
    """Headline expectancy metrics across all trades in the sessions."""
    trades = [t for s in sessions for t in s.trades]
    pnls = [float(t.realized_pnl()) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    n = len(pnls)

    gross_win = sum(wins)
    gross_loss = -sum(losses)  # positive magnitude
    avg_win = (gross_win / len(wins)) if wins else 0.0
    avg_loss = (gross_loss / len(losses)) if losses else 0.0
    win_rate = (len(wins) / n) if n else 0.0

    # Expectancy: average $ you make per trade over the long run.
    expectancy = (sum(pnls) / n) if n else 0.0
    # Profit factor: gross winnings / gross losses ( >1 = profitable ).
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)

    exit_reasons: dict[str, int] = {}
    for t in trades:
        key = t.exit_reason.value if t.exit_reason else "unknown"
        exit_reasons[key] = exit_reasons.get(key, 0) + 1

    return {
        "sessions": len(sessions),
        "sessions_with_trades": sum(1 for s in sessions if s.trades),
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate * 100,
        "total_pnl": sum(pnls),
        "avg_win": avg_win,
        "avg_loss": -avg_loss,         # report as negative
        "expectancy": expectancy,       # $ per trade
        "profit_factor": profit_factor,
        "best": max(pnls) if pnls else 0.0,
        "worst": min(pnls) if pnls else 0.0,
        "exit_reasons": exit_reasons,
    }


def equity_curve(sessions: list[SessionResult]):
    """Return (exit_times, cumulative_pnl) ordered by trade exit time."""
    trades = sorted(
        (t for s in sessions for t in s.trades),
        key=lambda t: t.exit_time,
    )
    times, cum, running = [], [], 0.0
    for t in trades:
        running += float(t.realized_pnl())
        times.append(t.exit_time)
        cum.append(running)
    return times, cum


def run_batch(tickers: list[str], period: str = "5d", alarm_d_scope: str = "session",
              exit_mode: str = "alarms") -> BatchResult:
    """Run every shared session for each ticker against QQQ. Network (yfinance)."""
    from tiger import data

    qqq = data.load_yfinance("QQQ", period=period)
    qqq_days = set(qqq.index.normalize())

    result = BatchResult()
    for tk in tickers:
        tk = tk.strip().upper()
        if not tk:
            continue
        try:
            stock = data.load_yfinance(tk, period=period)
        except Exception:  # noqa: BLE001
            result.skipped.append(tk)
            continue
        days = sorted(set(stock.index.normalize()) & qqq_days)
        for d in days:
            try:
                result.sessions.append(
                    run_backtest(stock, qqq, tk, target_date=d,
                                 alarm_d_scope=alarm_d_scope, exit_mode=exit_mode)
                )
            except Exception:  # noqa: BLE001 - a bad day shouldn't kill the batch
                continue
    return result
