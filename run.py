"""
Tiger Sovereign — live paper trading runner.

Usage:
    uv run python run.py              # auto-scan for candidates at open
    uv run python run.py NVDA TSLA   # manually specify tickers (skips scanner)

What it does:
  08:00 ET  Scans news + pre-market gaps for today's candidates
  09:30 ET  Opens WebSocket, starts receiving 1m bars
  09:30-15:49  Runs Tiger Sovereign logic on every bar, places paper orders
  15:49 ET  Flushes any open position
  16:00 ET  Prints end-of-day summary

Run this once per trading day, after 08:00 ET.
"""
from __future__ import annotations

import logging
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from tiger.bars import BarStream
from tiger.live import LiveEngine
from tiger.scanner import run_scan

ET = ZoneInfo("America/New_York")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def main() -> None:
    now = datetime.now(ET)
    log.info("Tiger Sovereign starting — %s", now.strftime("%Y-%m-%d %H:%M ET"))

    # ── Step 1: get tickers ──────────────────────────────────────────────────
    if len(sys.argv) > 1:
        tickers = [t.upper() for t in sys.argv[1:]]
        log.info("Manual tickers: %s", tickers)
    else:
        log.info("Running pre-market scan...")
        candidates = run_scan(print_results=True)
        if not candidates:
            log.warning("No candidates found. Exiting.")
            return
        tickers = [c.ticker for c in candidates]

    # Always include QQQ for the weather check
    stream_tickers = list(dict.fromkeys(["QQQ"] + tickers))
    log.info("Subscribing to bars for: %s", stream_tickers)

    # ── Step 2: build one LiveEngine per target ticker ───────────────────────
    engines: dict[str, LiveEngine] = {t: LiveEngine(t) for t in tickers}

    # ── Step 3: start bar stream ─────────────────────────────────────────────
    stream = BarStream(stream_tickers)
    stream.start()

    log.info("Waiting for market open (09:30 ET)...")

    try:
        while True:
            now = datetime.now(ET)

            # Stop after 16:00
            if now.hour >= 16:
                log.info("Market closed. Shutting down.")
                break

            bar = stream.get(timeout=10)
            if bar is None:
                continue

            if bar.ticker == "QQQ":
                for engine in engines.values():
                    engine.feed_qqq_bar(bar)
            elif bar.ticker in engines:
                engines[bar.ticker].feed_bar(bar)

    except KeyboardInterrupt:
        log.info("Interrupted by user.")
    finally:
        stream.stop()
        for engine in engines.values():
            print(engine.summary())
        log.info("Done.")


if __name__ == "__main__":
    main()
