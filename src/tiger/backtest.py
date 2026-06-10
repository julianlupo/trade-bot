"""Backtest engine — replays one trading day of 1m bars through the strategy.

This is the Phase 1 deliverable: prove the edge on historical data before any
live engine or paid data. It wires together indicators + state + entry + alarms
+ risk and produces a trade log and summary stats.

Documented v1 approximations (all because a bar-level backtest lacks tick/quote
data — see ROADMAP.md and OPEN_QUESTIONS.md):
  * Decisions are made on 1m bar CLOSE. Alarm E's "exact tick" is approximated
    at bar close.
  * LIMIT entry fills at bar close * (1 +/- 0.1%) (we lack live bid/ask).
  * Hard/ratcheted STOP MARKET fills exactly at the stop level if the bar's
    range touches it (no extra gap slippage modeled).
  * 5m indicators are aligned to the 1m timeline using each 5m bar's COMPLETION
    time, so there is no lookahead.
  * Scale-in / half-size sizing is deferred to v2; v1 takes full size.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from decimal import Decimal

import pandas as pd

from tiger import alarms, entry, indicators, risk
from tiger.alarms import AlarmAction
from tiger.state import Direction, ExitReason, MarketState, StrikeState

OR_LOCK = time(9, 35, 59)
ENTRY_OPEN = time(9, 36, 0)
ENTRY_CLOSE = time(15, 44, 59)
EOD_FLUSH = time(15, 49, 0)


# --------------------------------------------------------------------------- #
# Feed preparation: precompute every indicator the loop needs, on one timeline.
# --------------------------------------------------------------------------- #
def _resample_5m(df: pd.DataFrame) -> pd.DataFrame:
    r = df.resample("5min", label="left", closed="left")
    out = pd.DataFrame(
        {
            "open": r["open"].first(),
            "high": r["high"].max(),
            "low": r["low"].min(),
            "close": r["close"].last(),
            "volume": r["volume"].sum(),
        }
    ).dropna()
    return out


def _align_5m(bars5m: pd.DataFrame, index_1m: pd.DatetimeIndex,
              cols: dict[str, pd.Series]) -> pd.DataFrame:
    """Align completed-5m values onto the 1m index (no lookahead).

    A 5m bar labeled T completes at T+5min, so its values become visible to 1m
    bars at/after T+5min. We carry the 5m label so the loop can detect when a
    fresh 5m bar just completed (Alarm B).
    """
    right = pd.DataFrame(cols, index=bars5m.index)
    right["label5m"] = bars5m.index
    right["completion"] = (bars5m.index + pd.Timedelta(minutes=5)).as_unit("ns")
    right = right.sort_values("completion")

    left = pd.DataFrame({"ts": index_1m.as_unit("ns")}).sort_values("ts")
    merged = pd.merge_asof(left, right, left_on="ts", right_on="completion",
                           direction="backward")
    merged.index = left["ts"].to_numpy()
    return merged.reindex(index_1m)


def prepare_feed(stock_1m: pd.DataFrame, qqq_1m: pd.DataFrame) -> pd.DataFrame:
    """Build one 1m-indexed DataFrame with all indicators the engine reads."""
    feed = stock_1m.copy()

    # stock 1m indicators
    feed["rsi_1m"] = indicators.rsi(feed["close"], 15)
    dmi1 = indicators.adx_di(feed["high"], feed["low"], feed["close"], 14)
    feed["adx_1m"] = dmi1["adx"]
    feed["di_plus_1m"] = dmi1["di_plus"]
    feed["di_minus_1m"] = dmi1["di_minus"]
    feed["vol55"] = indicators.rolling_volume_average(feed["volume"], 55)

    # stock 5m indicators
    s5 = _resample_5m(stock_1m)
    dmi5 = indicators.adx_di(s5["high"], s5["low"], s5["close"], 14)
    s5_aligned = _align_5m(
        s5, feed.index,
        {
            "adx_5m": dmi5["adx"],
            "di_plus_5m": dmi5["di_plus"],
            "di_minus_5m": dmi5["di_minus"],
            "ema9_5m": indicators.ema(s5["close"], 9),
            "close5m": s5["close"],
        },
    )
    for c in ["adx_5m", "di_plus_5m", "di_minus_5m", "ema9_5m", "close5m", "label5m"]:
        feed[c] = s5_aligned[c].to_numpy()

    # QQQ 1m price + 5m weather indicators
    feed["qqq_price"] = qqq_1m["close"].reindex(feed.index).ffill().to_numpy()
    q5 = _resample_5m(qqq_1m)
    q5_aligned = _align_5m(
        q5, feed.index,
        {
            "qqq_close5m": q5["close"],
            "qqq_ema9_5m": indicators.ema(q5["close"], 9),
            "qqq_vwap5m": indicators.session_vwap(q5["high"], q5["low"], q5["close"], q5["volume"]),
        },
    )
    for c in ["qqq_close5m", "qqq_ema9_5m", "qqq_vwap5m"]:
        feed[c] = q5_aligned[c].to_numpy()

    return feed


# --------------------------------------------------------------------------- #
# The engine
# --------------------------------------------------------------------------- #
@dataclass
class SessionResult:
    ticker: str
    date: str
    state: MarketState

    @property
    def trades(self) -> list[StrikeState]:
        return self.state.closed_strikes

    @property
    def total_pnl(self) -> Decimal:
        return self.state.realized_pnl


def _f(v) -> float | None:
    """NaN-safe float extractor for feed cells."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return float(v)


def run_backtest(
    stock_1m: pd.DataFrame,
    qqq_1m: pd.DataFrame,
    ticker: str = "TEST",
    target_date=None,
    alarm_d_scope: str = "session",
    exit_mode: str = "alarms",
) -> SessionResult:
    """Run the strategy on one target day.

    Indicators are computed over the FULL input (any warmup days included) so
    5m trend indicators are warm at the open. Only the target day is traded
    (defaults to the last date present). Rolling histories (closes, recent ADX,
    prev close) carry across the boundary so alarms aren't cold at 09:30.
    """
    feed = prepare_feed(stock_1m, qqq_1m)
    all_dates = pd.DatetimeIndex(feed.index.normalize().unique())
    target = all_dates[-1] if target_date is None else pd.Timestamp(target_date).normalize()
    target = target.tz_localize(feed.index.tz) if target.tzinfo is None else target

    state = MarketState(ticker=ticker)
    closes: list[float] = []
    recent_adx_1m: list[float] = []
    prev_close: float | None = None
    last_5m_label = None

    for ts, row in feed.iterrows():
        # Always maintain rolling indicator history; only trade the target day.
        if ts.normalize() != target:
            closes.append(float(row["close"]))
            recent_adx_1m.append(_f(row["adx_1m"]) or 0.0)
            prev_close = float(row["close"])
            last_5m_label = row["label5m"]
            continue

        bar_time = ts.time()
        high, low, close = float(row["high"]), float(row["low"]), float(row["close"])
        rsi_1m = _f(row["rsi_1m"])
        adx_5m = _f(row["adx_5m"])
        closes.append(close)

        # --- opening range window (no trading) ---
        if bar_time <= OR_LOCK:
            state.update_opening_range(high, low)
            state.update_extremes(high, low, rsi_1m if rsi_1m is not None else 50.0)
            state.update_session_adx_peak(adx_5m if adx_5m is not None else 0.0)
            prev_close = close
            recent_adx_1m.append(_f(row["adx_1m"]) or 0.0)
            last_5m_label = row["label5m"]
            continue

        # snapshot prior extremes BEFORE this bar updates them (permit levels for strikes 2/3)
        prior_nhod, prior_nlod = state.nhod, state.nlod
        state.update_extremes(high, low, rsi_1m if rsi_1m is not None else 50.0)
        state.update_session_adx_peak(adx_5m if adx_5m is not None else 0.0)
        recent_adx_1m.append(_f(row["adx_1m"]) or 0.0)
        new_5m_completed = row["label5m"] != last_5m_label
        new_nhod = prior_nhod is None or high > prior_nhod
        new_nlod = prior_nlod is None or low < prior_nlod

        # ---------------- manage an open position ---------------- #
        if state.in_position:
            strike = state.open_strike
            direction = strike.direction
            exited = _manage_position(
                state, strike, ts, bar_time, row, close, high, low,
                prev_close, rsi_1m, adx_5m, recent_adx_1m, new_5m_completed,
                alarm_d_scope, new_nhod, new_nlod, exit_mode,
            )
            if exited:
                if risk.circuit_breaker_tripped(state.realized_pnl):
                    state.circuit_broken = True

        # ---------------- consider a new entry ---------------- #
        elif state.can_open_new_strike and ENTRY_OPEN <= bar_time <= ENTRY_CLOSE:
            _try_entry(state, ts, bar_time, row, close, prior_nhod, prior_nlod, closes, rsi_1m)

        prev_close = close
        last_5m_label = row["label5m"]

    return SessionResult(ticker=ticker, date=str(target.date()), state=state)


def _try_entry(state, ts, bar_time, row, close, prior_nhod, prior_nlod, closes, rsi_1m):
    is_strike1 = state.strikes_taken == 0
    common = dict(
        closes=closes,
        is_strike1=is_strike1,
        qqq_close_5m=_f(row["qqq_close5m"]),
        qqq_ema9_5m=_f(row["qqq_ema9_5m"]),
        qqq_price=_f(row["qqq_price"]),
        qqq_vwap_5m=_f(row["qqq_vwap5m"]),
        volume=float(row["volume"]),
        vol_avg_55=_f(row["vol55"]),
        bar_time=bar_time,
        di_plus_5m=_f(row["di_plus_5m"]),
        di_minus_5m=_f(row["di_minus_5m"]),
        adx_5m=_f(row["adx_5m"]),
        di_plus_1m=_f(row["di_plus_1m"]),
        di_minus_1m=_f(row["di_minus_1m"]),
        current_price=close,
        current_rsi=rsi_1m if rsi_1m is not None else 50.0,
        stored_peak_price=state.stored_peak_price,
        stored_peak_rsi=state.stored_peak_rsi,
    )
    long_level = state.orh if is_strike1 else prior_nhod
    short_level = state.orl if is_strike1 else prior_nlod

    signal = entry.check_entry(Direction.LONG, level=long_level, **common)
    if signal is None:
        signal = entry.check_entry(Direction.SHORT, level=short_level, **common)
    if signal is None:
        return

    fill = risk.entry_limit_price(signal.direction, Decimal(str(close)))
    full_shares = risk.position_size(fill)
    if full_shares <= 0:
        return
    # Full Strike takes 100%; Scaled Strike takes 50% now and may add the rest.
    if signal.full_size:
        shares, is_scaled, is_full = full_shares, False, True
    else:
        shares = max(full_shares // 2, 1)
        is_scaled, is_full = True, False
    stop = risk.hard_stop_price(signal.direction, fill, shares)
    state.open_strike = StrikeState(
        strike_number=state.strikes_taken + 1,
        direction=signal.direction,
        entry_time=ts,
        entry_price=fill,
        shares=shares,
        stop_price=stop,
        is_scaled=is_scaled,
        is_full_filled=is_full,
    )
    state.strikes_taken += 1


def _close_position(state, strike, ts, exit_price: Decimal, reason: ExitReason):
    strike.exit_time = ts
    strike.exit_price = exit_price
    strike.exit_reason = reason
    state.realized_pnl += strike.realized_pnl()
    state.closed_strikes.append(strike)
    state.open_strike = None


def _manage_position(state, strike, ts, bar_time, row, close, high, low,
                     prev_close, rsi_1m, adx_5m, recent_adx_1m, new_5m_completed,
                     alarm_d_scope="session", new_nhod=False, new_nlod=False,
                     exit_mode="alarms") -> bool:
    """Run sentinels + stop + EOD flush for the open position. Returns True if exited."""
    d = strike.direction

    # Track the per-Strike peak 5m ADX (spec Trade_HVP) for the per-strike Alarm D test.
    if adx_5m is not None and adx_5m > strike.trade_hvp_5m_adx:
        strike.trade_hvp_5m_adx = adx_5m

    # EOD flush takes precedence
    if bar_time >= EOD_FLUSH:
        _close_position(state, strike, ts, Decimal(str(close)), ExitReason.EOD_FLUSH)
        return True

    # Market-exit alarms (A, B, D)
    a = alarms.alarm_a_flash_move(d, prev_close, close)
    if a.action is AlarmAction.EXIT:
        _close_position(state, strike, ts, Decimal(str(close)), ExitReason.ALARM_A)
        return True
    if new_5m_completed:
        b = alarms.alarm_b_trend_death(d, _f(row["close5m"]), _f(row["ema9_5m"]))
        if b.action is AlarmAction.EXIT:
            _close_position(state, strike, ts, Decimal(str(close)), ExitReason.ALARM_B)
            return True
    # OPEN-Q1: Alarm D peak scope — 'session' (original literal) or 'strike' (Trade_HVP).
    hvp_peak = state.session_peak_5m_adx if alarm_d_scope == "session" else strike.trade_hvp_5m_adx
    dd = alarms.alarm_d_hvp_lock(adx_5m, hvp_peak)
    if dd.action is AlarmAction.EXIT:
        _close_position(state, strike, ts, Decimal(str(close)), ExitReason.ALARM_D)
        return True

    # Stop touched intrabar?
    stop = strike.stop_price
    if d is Direction.LONG and Decimal(str(low)) <= stop:
        reason = ExitReason.HARD_STOP if strike.stop_source == "hard" else ExitReason.RATCHET_STOP
        _close_position(state, strike, ts, stop, reason)
        return True
    if d is Direction.SHORT and Decimal(str(high)) >= stop:
        reason = ExitReason.HARD_STOP if strike.stop_source == "hard" else ExitReason.RATCHET_STOP
        _close_position(state, strike, ts, stop, reason)
        return True

    # Scale-in (Phase 5): add the second 50% of a Scaled Strike if it strengthens.
    if strike.is_scaled and not strike.is_full_filled:
        made_new_extreme = new_nhod if d is Direction.LONG else new_nlod
        divergent = alarms.divergence(
            d, close, rsi_1m if rsi_1m is not None else 50.0,
            state.stored_peak_price, state.stored_peak_rsi,
        )
        if entry.scale_in_ok(d, _f(row["di_plus_1m"]), _f(row["di_minus_1m"]),
                             made_new_extreme, divergent):
            add_qty = strike.shares
            fill2 = risk.entry_limit_price(d, Decimal(str(close)))
            blended = risk.blended_entry_price(strike.entry_price, strike.shares, fill2, add_qty)
            strike.entry_price = blended
            strike.shares += add_qty
            strike.is_full_filled = True
            strike.stop_price = risk.hard_stop_price(d, blended, strike.shares)  # OPEN-Q4: recalc on full
            strike.stop_source = "hard"

    # Ratchet alarms (C, E) — tighten the stop for future bars.
    # ONLY in "alarms" mode. "run" mode skips ratcheting (the documented loss
    # center) and lets the trade run to its hard stop / alarm B-D / EOD.
    if exit_mode == "alarms":
        c = alarms.alarm_c_tiger_grip(recent_adx_1m)
        e = alarms.alarm_e_divergence(
            d, close, rsi_1m if rsi_1m is not None else 50.0,
            state.stored_peak_price, state.stored_peak_rsi,
        )
        if c.action is AlarmAction.RATCHET or e.action is AlarmAction.RATCHET:
            new_stop = risk.ratchet_stop(d, Decimal(str(close)), strike.stop_price)
            if new_stop != strike.stop_price:
                strike.stop_price = new_stop
                strike.stop_source = "ratchet_e" if e.action is AlarmAction.RATCHET else "ratchet_c"
    return False


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def format_report(result: SessionResult) -> str:
    s = result.state
    lines = [
        f"=== Tiger Sovereign backtest — {result.ticker} {result.date} ===",
        f"Opening range: ORH={s.orh:.2f} ORL={s.orl:.2f}" if s.orh else "No opening range",
        f"Strikes taken: {s.strikes_taken} | Circuit broken: {s.circuit_broken}",
        f"Trades closed: {len(result.trades)} | Session P&L: ${result.total_pnl:.2f}",
        "",
    ]
    if not result.trades:
        lines.append("(no trades)")
    for t in result.trades:
        lines.append(
            f"  Strike {t.strike_number} {t.direction.value.upper():5s} "
            f"{t.shares:>4d}sh @ {t.entry_price:.3f} -> {t.exit_price:.3f} "
            f"| {t.exit_reason.value:20s} | P&L ${t.realized_pnl():.2f} "
            f"| {t.entry_time.time()}->{t.exit_time.time()}"
        )
    return "\n".join(lines)


def summary_stats(result: SessionResult) -> dict:
    """Headline numbers for a session (used by the dashboard and CLI)."""
    trades = result.trades
    wins = [t for t in trades if t.realized_pnl() > 0]
    n = len(trades)
    return {
        "trades": n,
        "wins": len(wins),
        "win_rate": (len(wins) / n * 100) if n else 0.0,
        "total_pnl": float(result.total_pnl),
        "avg_pnl": (float(result.total_pnl) / n) if n else 0.0,
        "strikes": result.state.strikes_taken,
        "circuit_broken": result.state.circuit_broken,
    }


def load_and_run_yfinance(ticker: str, period: str = "5d"):
    """Fetch real bars, run the most recent shared day, return (result, day_bars)."""
    from tiger import data

    stock = data.load_yfinance(ticker, period=period)
    qqq = data.load_yfinance("QQQ", period=period)
    common = sorted(set(stock.index.normalize()) & set(qqq.index.normalize()))
    if not common:
        raise RuntimeError(f"No overlapping session days for {ticker} and QQQ")
    target = common[-1]
    result = run_backtest(stock, qqq, ticker, target_date=target)
    day_bars = stock[stock.index.normalize() == target]
    return result, day_bars


def main():  # pragma: no cover - manual demo entrypoint
    import sys

    from tiger import data

    if len(sys.argv) > 1:
        ticker = sys.argv[1].upper()
        stock = data.load_yfinance(ticker)          # multi-day -> warmup + target
        qqq = data.load_yfinance("QQQ")
        # trade the most recent fully-shared day; earlier days warm the indicators
        common = sorted(set(stock.index.normalize()) & set(qqq.index.normalize()))
        print(format_report(run_backtest(stock, qqq, ticker, target_date=common[-1])))
    else:
        stock, qqq = data.synthetic_session()
        print(format_report(run_backtest(stock, qqq, "SYNTH")))


if __name__ == "__main__":
    main()
