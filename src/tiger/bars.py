"""
Live bar builder using Alpaca's WebSocket bar stream.
Alpaca emits completed 1-minute bars directly — no need to aggregate trades.
"""
from __future__ import annotations

import asyncio
import logging
import os
import queue
import threading
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from alpaca.data.live import StockDataStream
from dotenv import load_dotenv

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


@dataclass
class LiveBar:
    ticker: str
    timestamp: datetime   # bar open time, ET-aware
    open: float
    high: float
    low: float
    close: float
    volume: int


class BarStream:
    """
    Subscribes to Alpaca's 1-minute bar WebSocket for the given tickers.
    Completed bars are placed on a thread-safe queue for the main loop to read.

    Usage:
        stream = BarStream(["NVDA", "QQQ"])
        stream.start()
        while True:
            bar = stream.get(timeout=5)   # blocks up to 5s, returns None on timeout
            if bar:
                process(bar)
    """

    def __init__(self, tickers: list[str]):
        load_dotenv()
        self.tickers = tickers
        self._q: queue.Queue[LiveBar] = queue.Queue()
        self._wss = StockDataStream(
            api_key=os.getenv("ALPACA_API_KEY"),
            secret_key=os.getenv("ALPACA_SECRET_KEY"),
        )
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # ── public ───────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the WebSocket in a background thread."""
        self._wss.subscribe_bars(self._on_bar, *self.tickers)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info("BarStream started for %s", self.tickers)

    def stop(self) -> None:
        """Signal the WebSocket thread to stop."""
        self._stop_event.set()
        try:
            self._wss.stop()
        except Exception:
            pass
        log.info("BarStream stopped.")

    def get(self, timeout: float = 5.0) -> LiveBar | None:
        """Pop the next completed bar, or return None after timeout seconds."""
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    # ── internals ────────────────────────────────────────────────────────────

    def _run(self) -> None:
        try:
            self._wss.run()
        except Exception as exc:
            if not self._stop_event.is_set():
                log.error("BarStream WebSocket error: %s", exc)

    async def _on_bar(self, bar) -> None:
        ts = bar.timestamp
        if ts.tzinfo is None:
            from datetime import timezone
            ts = ts.replace(tzinfo=timezone.utc)
        ts_et = ts.astimezone(ET)

        live_bar = LiveBar(
            ticker=bar.symbol,
            timestamp=ts_et,
            open=float(bar.open),
            high=float(bar.high),
            low=float(bar.low),
            close=float(bar.close),
            volume=int(bar.volume),
        )
        self._q.put(live_bar)
        log.debug("Bar: %s %s O=%.2f H=%.2f L=%.2f C=%.2f V=%d",
                  bar.symbol, ts_et.strftime("%H:%M"), live_bar.open,
                  live_bar.high, live_bar.low, live_bar.close, live_bar.volume)
