"""
Live Tiger Sovereign engine.

Feeds completed 1-minute bars through the same indicator / state / decision
logic used in the backtest, but executes via Alpaca paper orders instead of
simulating fills.

One LiveEngine instance per ticker.  QQQ bars are also fed in for the weather
check — always start with QQQ in the BarStream alongside the target ticker.
"""
from __future__ import annotations

import logging
from collections import deque
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from tiger import alarms, broker, entry, logger, risk
from tiger.bars import LiveBar
from tiger.indicators import adx_di, ema, rolling_volume_average, rsi, session_vwap
from tiger.state import Direction, MarketState, StrikeState

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

HISTORY_LEN = 500


def _5m_bucket(dt: datetime) -> datetime:
    return dt.replace(minute=(dt.minute // 5) * 5, second=0, microsecond=0)


class LiveEngine:
    """
    Processes one ticker's live bars through Tiger Sovereign logic.
    Call feed_bar(bar) for each completed 1m bar.
    Call feed_qqq_bar(bar) for each completed QQQ 1m bar.
    """

    def __init__(self, ticker: str, trade_date: date | None = None):
        self.ticker = ticker
        self.trade_date = trade_date or datetime.now(ET).date()

        self._opens: deque[float] = deque(maxlen=HISTORY_LEN)
        self._highs: deque[float] = deque(maxlen=HISTORY_LEN)
        self._lows: deque[float] = deque(maxlen=HISTORY_LEN)
        self._closes: deque[float] = deque(maxlen=HISTORY_LEN)
        self._volumes: deque[float] = deque(maxlen=HISTORY_LEN)
        self._timestamps: deque[datetime] = deque(maxlen=HISTORY_LEN)

        self._qqq_closes: deque[float] = deque(maxlen=HISTORY_LEN)
        self._qqq_highs: deque[float] = deque(maxlen=HISTORY_LEN)
        self._qqq_lows: deque[float] = deque(maxlen=HISTORY_LEN)
        self._qqq_volumes: deque[float] = deque(maxlen=HISTORY_LEN)
        self._qqq_timestamps: deque[datetime] = deque(maxlen=HISTORY_LEN)

        self._last_5m_bar: dict | None = None
        self._current_5m_bucket: datetime | None = None
        self._5m_open: float | None = None
        self._5m_high: float = float("-inf")
        self._5m_low: float = float("inf")
        self._5m_close: float | None = None
        self._5m_volume: int = 0
        self._completed_5m_bars: list[dict] = []

        self._qqq_last_5m_bar: dict | None = None
        self._qqq_current_5m_bucket: datetime | None = None
        self._qqq_5m_open: float | None = None
        self._qqq_5m_high: float = float("-inf")
        self._qqq_5m_low: float = float("inf")
        self._qqq_5m_close: float | None = None
        self._qqq_5m_volume: int = 0
        self._qqq_completed_5m_bars: list[dict] = []

        self._state = MarketState(ticker=ticker)
        self._prev_close: float | None = None
        self._session_adx_peak: float = 0.0
        self._recent_1m_adx: deque[float] = deque(maxlen=10)
        self._eod_flushed = False

    # ── public feed ──────────────────────────────────────────────────────────

    def feed_bar(self, bar: LiveBar) -> None:
        bar_time = bar.timestamp.time()
        if bar_time < time(9, 30) or bar_time >= time(16, 0):
            return
        if bar_time >= time(15, 49) and not self._eod_flushed:
            self._do_eod_flush(bar)
            return

        self._opens.append(bar.open)
        self._highs.append(bar.high)
        self._lows.append(bar.low)
        self._closes.append(bar.close)
        self._volumes.append(bar.volume)
        self._timestamps.append(bar.timestamp)

        new_5m = self._update_5m(bar)

        if bar_time == time(9, 35):
            self._state.update_opening_range(bar.high, bar.low)
            log.info("[%s] OR locked: H=%.2f L=%.2f", self.ticker,
                     self._state.orh, self._state.orl)

        ind = self._compute_indicators(bar)
        if ind is None:
            # Still update extremes with a neutral RSI until indicators warm up
            self._state.update_extremes(bar.high, bar.low, 50.0)
            self._prev_close = bar.close
            return

        # Update extremes now that RSI is available
        self._state.update_extremes(bar.high, bar.low, ind["rsi_1m"])

        adx_1m = ind["adx_1m"]
        if adx_1m and not np.isnan(adx_1m):
            self._recent_1m_adx.append(adx_1m)
            self._state.update_session_adx_peak(adx_1m)
            self._session_adx_peak = max(self._session_adx_peak, adx_1m)

        if self._state.in_position:
            self._manage_position(bar, ind, new_5m)
        elif self._state.can_open_new_strike and bar_time >= time(9, 36):
            self._try_entry(bar, ind)

        self._prev_close = bar.close

    def feed_qqq_bar(self, bar: LiveBar) -> None:
        self._qqq_closes.append(bar.close)
        self._qqq_highs.append(bar.high)
        self._qqq_lows.append(bar.low)
        self._qqq_volumes.append(bar.volume)
        self._qqq_timestamps.append(bar.timestamp)
        self._update_qqq_5m(bar)

    # ── indicators ───────────────────────────────────────────────────────────

    def _compute_indicators(self, bar: LiveBar) -> dict | None:
        if len(self._closes) < 30:
            return None

        closes = pd.Series(list(self._closes))
        highs = pd.Series(list(self._highs))
        lows = pd.Series(list(self._lows))
        volumes = pd.Series(list(self._volumes))
        ts_index = pd.DatetimeIndex(list(self._timestamps), tz=ET)

        # session_vwap requires the DatetimeIndex on the series themselves
        highs_i = highs.set_axis(ts_index)
        lows_i = lows.set_axis(ts_index)
        closes_i = closes.set_axis(ts_index)
        volumes_i = volumes.set_axis(ts_index)

        rsi_val = float(rsi(closes).iloc[-1])
        adx_df = adx_di(highs, lows, closes)
        adx_1m = float(adx_df["adx"].iloc[-1])
        di_plus_1m = float(adx_df["di_plus"].iloc[-1])
        di_minus_1m = float(adx_df["di_minus"].iloc[-1])
        vwap_1m = float(session_vwap(highs_i, lows_i, closes_i, volumes_i).iloc[-1])
        vol_avg = rolling_volume_average(volumes)
        vol_avg_val = float(vol_avg.iloc[-1]) if not np.isnan(vol_avg.iloc[-1]) else None

        adx_5m = di_plus_5m = di_minus_5m = ema9_5m = None
        if len(self._completed_5m_bars) >= 20:
            df5 = pd.DataFrame(self._completed_5m_bars)
            adx5 = adx_di(df5["h"], df5["l"], df5["c"])
            adx_5m = float(adx5["adx"].iloc[-1])
            di_plus_5m = float(adx5["di_plus"].iloc[-1])
            di_minus_5m = float(adx5["di_minus"].iloc[-1])
            ema9_5m = float(ema(df5["c"], 9).iloc[-1])

        qqq_close_5m = qqq_ema9_5m = qqq_price = qqq_vwap = None
        if self._qqq_last_5m_bar and len(self._qqq_completed_5m_bars) >= 10:
            qqq_close_5m = self._qqq_last_5m_bar["c"]
            qqq_price = list(self._qqq_closes)[-1] if self._qqq_closes else None
            df_qqq = pd.DataFrame(self._qqq_completed_5m_bars)
            qqq_ema9_5m = float(ema(df_qqq["c"], 9).iloc[-1])
            if self._qqq_timestamps:
                qqq_ts = pd.DatetimeIndex(list(self._qqq_timestamps), tz=ET)
                qqq_vwap = float(
                    session_vwap(
                        pd.Series(list(self._qqq_highs), index=qqq_ts),
                        pd.Series(list(self._qqq_lows), index=qqq_ts),
                        pd.Series(list(self._qqq_closes), index=qqq_ts),
                        pd.Series(list(self._qqq_volumes), index=qqq_ts),
                    ).iloc[-1]
                )

        return {
            "rsi_1m": rsi_val,
            "adx_1m": adx_1m,
            "di_plus_1m": di_plus_1m,
            "di_minus_1m": di_minus_1m,
            "vwap_1m": vwap_1m,
            "vol_avg": vol_avg_val,
            "adx_5m": adx_5m,
            "di_plus_5m": di_plus_5m,
            "di_minus_5m": di_minus_5m,
            "ema9_5m": ema9_5m,
            "qqq_close_5m": qqq_close_5m,
            "qqq_ema9_5m": qqq_ema9_5m,
            "qqq_price": qqq_price,
            "qqq_vwap": qqq_vwap,
        }

    # ── entry ────────────────────────────────────────────────────────────────

    def _try_entry(self, bar: LiveBar, ind: dict) -> None:
        if not self._state.orh or not self._state.orl:
            return
        if self._state.circuit_broken:
            return

        recent_closes = list(self._closes)[-4:]

        for direction in (Direction.LONG, Direction.SHORT):
            level = float(self._state.orh) if direction == Direction.LONG else float(self._state.orl)
            signal = entry.check_entry(
                direction=direction,
                closes=recent_closes,
                level=level,
                is_strike1=(self._state.strikes_taken == 0),
                qqq_close_5m=ind["qqq_close_5m"],
                qqq_ema9_5m=ind["qqq_ema9_5m"],
                qqq_price=ind["qqq_price"],
                qqq_vwap_5m=ind["qqq_vwap"],
                volume=bar.volume,
                vol_avg_55=ind["vol_avg"],
                bar_time=bar.timestamp.time(),
                di_plus_5m=ind["di_plus_5m"],
                di_minus_5m=ind["di_minus_5m"],
                adx_5m=ind["adx_5m"],
                di_plus_1m=ind["di_plus_1m"],
                di_minus_1m=ind["di_minus_1m"],
                current_price=bar.close,
                current_rsi=ind["rsi_1m"],
                stored_peak_price=self._state.stored_peak_price,
                stored_peak_rsi=self._state.stored_peak_rsi,
            )
            if signal is None:
                continue

            fill_price = Decimal(str(bar.close))
            limit_px = risk.entry_limit_price(direction, fill_price)
            shares_full = risk.position_size(limit_px)
            shares = shares_full if signal.full_size else shares_full // 2
            if shares <= 0:
                continue

            stop_px = risk.hard_stop_price(direction, limit_px, shares)

            if direction == Direction.LONG:
                broker.buy_limit(self.ticker, shares, limit_px)
            else:
                broker.sell_short_limit(self.ticker, shares, limit_px)

            strike = StrikeState(
                strike_number=self._state.strikes_taken + 1,
                direction=direction,
                entry_time=bar.timestamp,
                entry_price=limit_px,
                shares=shares,
                stop_price=stop_px,
                stop_source="hard",
                trade_hvp_5m_adx=ind["adx_5m"] or 0.0,
                is_scaled=not signal.full_size,
                is_full_filled=signal.full_size,
            )
            self._state.open_strike = strike
            self._state.strikes_taken += 1

            log.info("[%s] ENTRY %s qty=%d limit=%.2f stop=%.2f strike=%d",
                     self.ticker, direction.value, shares, float(limit_px),
                     float(stop_px), strike.strike_number)
            logger.log_entry(
                ticker=self.ticker, direction=direction.value,
                qty=shares, limit_price=float(limit_px), stop_price=float(stop_px),
                strike_num=strike.strike_number, full_size=signal.full_size,
                ind={k: (round(v, 4) if isinstance(v, float) else v)
                     for k, v in ind.items() if v is not None},
            )
            break

    # ── position management ──────────────────────────────────────────────────

    def _manage_position(self, bar: LiveBar, ind: dict, new_5m_bar: bool) -> None:
        strike = self._state.open_strike
        if not strike:
            return

        direction = strike.direction
        close = bar.close

        stop_hit = (
            (direction == Direction.LONG and bar.low <= float(strike.stop_price))
            or (direction == Direction.SHORT and bar.high >= float(strike.stop_price))
        )
        if stop_hit:
            self._exit(bar, "HARD/RATCHET STOP")
            return

        if self._prev_close:
            a = alarms.alarm_a_flash_move(direction, self._prev_close, close)
            if a.action == alarms.AlarmAction.EXIT:
                self._exit(bar, "ALARM A")
                return

        if new_5m_bar and ind["ema9_5m"] and self._completed_5m_bars:
            last_5m_close = self._completed_5m_bars[-1]["c"]
            b = alarms.alarm_b_trend_death(direction, last_5m_close, ind["ema9_5m"])
            if b.action == alarms.AlarmAction.EXIT:
                self._exit(bar, "ALARM B")
                return

        if ind["adx_5m"] and self._state.session_peak_5m_adx:
            d = alarms.alarm_d_hvp_lock(ind["adx_5m"], self._state.session_peak_5m_adx)
            if d.action == alarms.AlarmAction.EXIT:
                self._exit(bar, "ALARM D")
                return

        if len(self._recent_1m_adx) >= 4:
            c = alarms.alarm_c_tiger_grip(list(self._recent_1m_adx)[-4:])
            if c.action == alarms.AlarmAction.RATCHET:
                new_stop = risk.ratchet_stop(direction, Decimal(str(close)), strike.stop_price)
                if new_stop != strike.stop_price:
                    strike.stop_price = new_stop
                    strike.stop_source = "ratchet_c"
                    log.info("[%s] Alarm C ratchet → %.2f", self.ticker, float(new_stop))
                    logger.log_ratchet(self.ticker, direction.value,
                                       float(strike.stop_price), float(new_stop), "alarm_c")

        e = alarms.alarm_e_divergence(
            direction, close, ind["rsi_1m"],
            self._state.stored_peak_price, self._state.stored_peak_rsi,
        )
        if e.action == alarms.AlarmAction.RATCHET:
            new_stop = risk.ratchet_stop(direction, Decimal(str(close)), strike.stop_price)
            if new_stop != strike.stop_price:
                strike.stop_price = new_stop
                strike.stop_source = "ratchet_e"
                log.info("[%s] Alarm E ratchet → %.2f", self.ticker, float(new_stop))
                logger.log_ratchet(self.ticker, direction.value,
                                   float(strike.stop_price), float(new_stop), "alarm_e")

        if direction == Direction.LONG and close > (self._state.stored_peak_price or 0):
            self._state.stored_peak_price = close
            self._state.stored_peak_rsi = ind["rsi_1m"]
        elif direction == Direction.SHORT and close < (self._state.stored_peak_price or float("inf")):
            self._state.stored_peak_price = close
            self._state.stored_peak_rsi = ind["rsi_1m"]

        if (strike.is_scaled and not strike.is_full_filled
                and ind["di_plus_1m"] and ind["di_minus_1m"]):
            made_new_extreme = (
                (direction == Direction.LONG and bar.high >= float(self._state.nhod or 0))
                or (direction == Direction.SHORT and bar.low <= float(self._state.nlod or float("inf")))
            )
            divergent = alarms.divergence(
                direction, close, ind["rsi_1m"],
                self._state.stored_peak_price, self._state.stored_peak_rsi,
            )
            if entry.scale_in_ok(direction, ind["di_plus_1m"], ind["di_minus_1m"],
                                  made_new_extreme, divergent):
                add_shares = strike.shares
                limit_px = risk.entry_limit_price(direction, Decimal(str(close)))
                if direction == Direction.LONG:
                    broker.buy_limit(self.ticker, add_shares, limit_px)
                else:
                    broker.sell_short_limit(self.ticker, add_shares, limit_px)
                blended = risk.blended_entry_price(
                    strike.entry_price, strike.shares, limit_px, add_shares)
                strike.shares += add_shares
                strike.entry_price = blended
                strike.stop_price = risk.hard_stop_price(direction, blended, strike.shares)
                strike.is_full_filled = True
                log.info("[%s] SCALE-IN %s +%d blended=%.2f new_stop=%.2f",
                         self.ticker, direction.value, add_shares,
                         float(blended), float(strike.stop_price))

    def _exit(self, bar: LiveBar, reason: str) -> None:
        strike = self._state.open_strike
        if not strike:
            return
        broker.close_position_market(self.ticker)
        fill = Decimal(str(bar.close))
        strike.exit_time = bar.timestamp
        strike.exit_price = fill
        strike.exit_reason = reason
        pnl = strike.realized_pnl()
        self._state.realized_pnl += pnl
        self._state.closed_strikes.append(strike)
        self._state.open_strike = None
        if risk.circuit_breaker_tripped(self._state.realized_pnl):
            self._state.circuit_broken = True
            log.warning("[%s] CIRCUIT BREAKER — no more trades. daily_pnl=%.2f",
                        self.ticker, float(self._state.realized_pnl))
            logger.log_circuit_break(self.ticker, float(self._state.realized_pnl))
        log.info("[%s] EXIT %s reason=%s pnl=%.2f daily_pnl=%.2f",
                 self.ticker, strike.direction.value, reason,
                 float(pnl), float(self._state.realized_pnl))
        logger.log_exit(
            ticker=self.ticker, direction=strike.direction.value,
            exit_price=float(fill), entry_price=float(strike.entry_price),
            qty=strike.shares, pnl=float(pnl), reason=reason,
            daily_pnl=float(self._state.realized_pnl),
        )

    def _do_eod_flush(self, bar: LiveBar) -> None:
        if self._state.in_position:
            log.info("[%s] EOD FLUSH", self.ticker)
            self._exit(bar, "EOD FLUSH")
        self._eod_flushed = True

    # ── 5m aggregation ───────────────────────────────────────────────────────

    def _update_5m(self, bar: LiveBar) -> bool:
        bucket = _5m_bucket(bar.timestamp)
        if self._current_5m_bucket is None:
            self._current_5m_bucket = bucket
            self._5m_open = bar.open

        if bucket > self._current_5m_bucket:
            completed = {"ts": self._current_5m_bucket, "o": self._5m_open,
                         "h": self._5m_high, "l": self._5m_low,
                         "c": self._5m_close, "v": self._5m_volume}
            self._completed_5m_bars.append(completed)
            if len(self._completed_5m_bars) > 200:
                self._completed_5m_bars.pop(0)
            self._last_5m_bar = completed
            if len(self._completed_5m_bars) >= 20:
                df5 = pd.DataFrame(self._completed_5m_bars)
                adx5 = adx_di(df5["h"], df5["l"], df5["c"])
                adx_val = float(adx5["adx"].iloc[-1])
                if not np.isnan(adx_val):
                    self._state.update_session_adx_peak(adx_val)
            self._current_5m_bucket = bucket
            self._5m_open = bar.open
            self._5m_high = bar.high
            self._5m_low = bar.low
            self._5m_close = bar.close
            self._5m_volume = bar.volume
            return True
        else:
            self._5m_high = max(self._5m_high, bar.high)
            self._5m_low = min(self._5m_low, bar.low)
            self._5m_close = bar.close
            self._5m_volume += bar.volume
            return False

    def _update_qqq_5m(self, bar: LiveBar) -> None:
        bucket = _5m_bucket(bar.timestamp)
        if self._qqq_current_5m_bucket is None:
            self._qqq_current_5m_bucket = bucket
            self._qqq_5m_open = bar.open
        if bucket > self._qqq_current_5m_bucket:
            completed = {"ts": self._qqq_current_5m_bucket, "o": self._qqq_5m_open,
                         "h": self._qqq_5m_high, "l": self._qqq_5m_low,
                         "c": self._qqq_5m_close, "v": self._qqq_5m_volume}
            self._qqq_completed_5m_bars.append(completed)
            if len(self._qqq_completed_5m_bars) > 200:
                self._qqq_completed_5m_bars.pop(0)
            self._qqq_last_5m_bar = completed
            self._qqq_current_5m_bucket = bucket
            self._qqq_5m_open = bar.open
            self._qqq_5m_high = bar.high
            self._qqq_5m_low = bar.low
            self._qqq_5m_close = bar.close
            self._qqq_5m_volume = bar.volume
        else:
            self._qqq_5m_high = max(self._qqq_5m_high, bar.high)
            self._qqq_5m_low = min(self._qqq_5m_low, bar.low)
            self._qqq_5m_close = bar.close
            self._qqq_5m_volume += bar.volume

    # ── summary ──────────────────────────────────────────────────────────────

    def summary(self) -> str:
        strikes = self._state.closed_strikes
        pnl = float(self._state.realized_pnl)
        lines = [f"\n{'='*50}",
                 f"  {self.ticker} — end of day",
                 f"  Trades: {len(strikes)}  |  P&L: ${pnl:+.2f}",
                 f"{'='*50}"]
        for s in strikes:
            lines.append(
                f"  Strike {s.strike_number}: {s.direction.value.upper()}  "
                f"entry={float(s.entry_price):.2f}  "
                f"exit={float(s.exit_price):.2f}  "
                f"pnl=${float(s.realized_pnl()):+.2f}  "
                f"reason={s.exit_reason}"
            )
        return "\n".join(lines)
