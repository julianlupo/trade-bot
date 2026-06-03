"""
Intraday backfill — replay today's bars to warm the engine mid-session.

When the bot is started after 09:30 (e.g. cron failed, or a manual mid-day
start), this pulls today's 1-minute bars from Alpaca and replays them through
each engine in WARMUP mode (execute=False): it locks the real opening range
and warms all indicators, but places NO orders. After backfill, the engine is
in the exact state it would have been in had it run since the open — flat,
with the correct opening range and indicator history — and trades only NEW
breakouts going forward.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from dotenv import load_dotenv

from tiger.bars import LiveBar
from tiger.live import LiveEngine

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def _client() -> StockHistoricalDataClient:
    load_dotenv()
    return StockHistoricalDataClient(
        api_key=os.getenv("ALPACA_API_KEY"),
        secret_key=os.getenv("ALPACA_SECRET_KEY"),
    )


def fetch_today_1m(tickers: list[str]) -> dict[str, list[LiveBar]]:
    """Fetch today's 1-minute bars (09:30 ET to now) for each ticker."""
    client = _client()
    now = datetime.now(ET)
    session_open = now.replace(hour=9, minute=30, second=0, microsecond=0)

    req = StockBarsRequest(
        symbol_or_symbols=tickers,
        timeframe=TimeFrame.Minute,
        start=session_open,
        limit=10000,
    )
    df = client.get_stock_bars(req).df

    out: dict[str, list[LiveBar]] = {t: [] for t in tickers}
    if df.empty:
        return out

    df = df.reset_index()  # columns: symbol, timestamp, open, high, low, close, volume, ...
    for _, row in df.iterrows():
        ts = row["timestamp"]
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        ts_et = ts.tz_convert(ET)
        # Regular session only
        t = ts_et.time()
        if t.hour < 9 or (t.hour == 9 and t.minute < 30) or t.hour >= 16:
            continue
        sym = row["symbol"]
        out.setdefault(sym, []).append(LiveBar(
            ticker=sym,
            timestamp=ts_et.to_pydatetime(),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=int(row["volume"]),
        ))
    return out


def warmup_engines(engines: dict[str, LiveEngine], qqq_ticker: str = "QQQ") -> None:
    """
    Replay today's bars through each engine in warmup mode (no orders placed).
    Feeds QQQ and target bars interleaved by timestamp so the weather check
    has QQQ data available at each target bar.
    """
    target_tickers = list(engines.keys())
    all_tickers = list(dict.fromkeys([qqq_ticker] + target_tickers))

    log.info("Backfill: fetching today's bars for %s ...", all_tickers)
    bars_by_ticker = fetch_today_1m(all_tickers)

    qqq_bars = bars_by_ticker.get(qqq_ticker, [])
    log.info("Backfill: QQQ %d bars; %s",
             len(qqq_bars),
             ", ".join(f"{t} {len(bars_by_ticker.get(t, []))}" for t in target_tickers))

    if not qqq_bars:
        log.warning("Backfill: no QQQ bars returned — weather check will be blind. "
                    "Proceeding anyway; entries may be suppressed until live QQQ arrives.")

    # Build a merged, time-ordered event list of (timestamp, ticker, bar)
    events: list[tuple[datetime, str, LiveBar]] = []
    for b in qqq_bars:
        events.append((b.timestamp, qqq_ticker, b))
    for t in target_tickers:
        for b in bars_by_ticker.get(t, []):
            events.append((b.timestamp, t, b))
    events.sort(key=lambda e: (e[0], e[1] != qqq_ticker))  # QQQ first within same minute

    for ts, ticker, bar in events:
        if ticker == qqq_ticker:
            for eng in engines.values():
                eng.feed_qqq_bar(bar)
        elif ticker in engines:
            engines[ticker].feed_bar(bar, execute=False)

    for t, eng in engines.items():
        s = eng._state
        if s.orh is not None:
            log.info("Backfill done [%s]: OR locked H=%.2f L=%.2f | warmed %d 1m bars, %d 5m bars",
                     t, s.orh, s.orl, len(eng._closes), len(eng._completed_5m_bars))
        else:
            log.warning("Backfill [%s]: opening range NOT set — not enough early bars.", t)
