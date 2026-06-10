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
from datetime import datetime, time as dtime
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
    # ALARM_D_SCOPE env var picks the Alarm D reference peak:
    #   "session" (default/literal spec) or "strike" (per-trade test — lets
    #   winners run). Set in .env to switch without code changes.
    import os
    alarm_d_scope = os.getenv("ALARM_D_SCOPE", "session").lower()
    exit_mode = os.getenv("EXIT_MODE", "alarms").lower()
    log.info("Alarm D scope: %s | Exit mode: %s", alarm_d_scope, exit_mode)
    engines: dict[str, LiveEngine] = {
        t: LiveEngine(t, alarm_d_scope=alarm_d_scope, exit_mode=exit_mode)
        for t in tickers
    }

    # ── Step 2.1: startup reconciliation (SAFETY) ────────────────────────────
    # The engine always starts assuming FLAT. If Alpaca shows pre-existing
    # positions (e.g. a prior instance died, or something carried overnight),
    # flatten them now so we begin from a known-clean state. This prevents
    # orphaned positions and double-trading on the same ticker.
    from tiger import broker
    existing = broker.list_open_positions()
    if existing:
        log.warning("Startup: found pre-existing positions %s — flattening for a "
                    "clean start (engine assumes flat).", existing)
        broker.close_all_positions()

    # ── Step 2.5: mid-session backfill ───────────────────────────────────────
    # If we're starting after the opening range window, replay today's bars in
    # warmup mode so the opening range locks and indicators warm up. No orders
    # are placed during backfill — only NEW breakouts trade going forward.
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    if market_open < now < market_close and now.time() > dtime(9, 36):
        log.info("Mid-session start detected — backfilling today's bars (warmup only)...")
        try:
            from tiger.backfill import warmup_engines
            warmup_engines(engines)
        except Exception as exc:
            log.error("Backfill failed: %s — continuing with live bars only.", exc)

    # ── Step 3: start bar stream ─────────────────────────────────────────────
    stream = BarStream(stream_tickers)
    stream.start()

    if now < market_open:
        log.info("Waiting for market open (09:30 ET)...")
    else:
        log.info("Streaming live bars — trading new breakouts.")

    from tiger import broker
    from decimal import Decimal
    ACCOUNT_DAILY_LIMIT = Decimal("-1500")  # account-wide, across all tickers
    account_halted = False
    last_pnl_check = 0.0

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

            # Account-wide circuit breaker: the per-ticker engines each have
            # their own -$1,500 limit, but the ACCOUNT can lose more across
            # several tickers. Check the real Alpaca account P&L (throttled to
            # once every ~30s) and halt every engine if the account breaches.
            if not account_halted:
                tick = time.monotonic()
                if tick - last_pnl_check > 30:
                    last_pnl_check = tick
                    try:
                        acct_pnl = broker.get_account_pnl()
                        if acct_pnl <= ACCOUNT_DAILY_LIMIT:
                            account_halted = True
                            for eng in engines.values():
                                eng._state.circuit_broken = True
                            log.warning("ACCOUNT CIRCUIT BREAKER — real P&L %.2f <= %.2f. "
                                        "All engines halted for the day.",
                                        float(acct_pnl), float(ACCOUNT_DAILY_LIMIT))
                    except Exception as exc:
                        log.warning("Account P&L check failed: %s", exc)

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
