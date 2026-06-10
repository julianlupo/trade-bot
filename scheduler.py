"""
Cloud scheduler — replaces launchd/cron when running on Railway.

Runs forever inside the container and supervises the trading day:
  - Weekdays 08:00-16:00 ET: keeps the bot (run.py) alive. If it's started
    mid-session, run.py's backfill catches it up. If the bot crashes, it is
    restarted (startup reconciliation flattens any positions the dead
    instance left, so state is always clean).
  - Weekdays ~16:10 ET, once: safety-flatten + record real results to the
    track record (eod_report).
  - Sunday 09:00 ET, once: weekly A/B backtest.

The dashboard (streamlit) runs as a separate process — see scripts/cloud_entry.sh.
"""
from __future__ import annotations

import logging
import subprocess
import sys
import time
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

BOT_START = dtime(8, 0)
BOT_END = dtime(16, 0)
EOD_TASKS_AT = dtime(16, 10)
WEEKLY_AT = dtime(9, 0)

MAX_RESTARTS_PER_DAY = 5  # don't loop forever on a hard crash

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  [scheduler] %(message)s",
    datefmt="%H:%M:%S",
)
# Log timestamps in ET (the container clock is UTC)
logging.Formatter.converter = lambda *args: datetime.now(ET).timetuple()
log = logging.getLogger(__name__)


def is_weekday(now: datetime) -> bool:
    return now.weekday() < 5  # Mon=0 .. Fri=4


def main() -> None:
    bot: subprocess.Popen | None = None
    restarts_today = 0
    eod_done_for: str | None = None
    weekly_done_for: str | None = None
    log.info("Scheduler up. ET now: %s", datetime.now(ET).strftime("%a %H:%M"))

    while True:
        now = datetime.now(ET)
        today = now.date().isoformat()
        t = now.time()

        # ── trading window: keep the bot alive ──────────────────────────────
        in_window = is_weekday(now) and BOT_START <= t < BOT_END
        if in_window:
            # Reap a dead bot exactly once (don't recount the same corpse)
            if bot is not None and bot.poll() is not None:
                log.warning("Bot exited (code %s).", bot.returncode)
                restarts_today += 1
                bot = None
            if bot is None:
                if restarts_today >= MAX_RESTARTS_PER_DAY:
                    pass  # crash cap hit — stay down; EOD flatten still runs
                else:
                    log.info("Starting bot (attempt #%d today)...", restarts_today + 1)
                    bot = subprocess.Popen([sys.executable, "run.py"])
        else:
            if bot is not None and bot.poll() is None:
                log.info("Outside trading window — stopping bot.")
                bot.terminate()
                try:
                    bot.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    bot.kill()
            bot = None

        # ── EOD: safety flatten + record the real day ────────────────────────
        if is_weekday(now) and t >= EOD_TASKS_AT and eod_done_for != today:
            eod_done_for = today
            restarts_today = 0
            log.info("EOD tasks: safety flatten + eod_report...")
            try:
                subprocess.run(
                    [sys.executable, "-c",
                     "from tiger import broker; broker.close_all_positions()"],
                    timeout=120,
                )
                subprocess.run(
                    [sys.executable, "-m", "tiger.eod_report"], timeout=300)
                log.info("EOD recorded.")
            except Exception as exc:
                log.error("EOD tasks failed: %s", exc)

        # ── Sunday: weekly A/B backtest ──────────────────────────────────────
        if now.weekday() == 6 and t >= WEEKLY_AT and weekly_done_for != today:
            weekly_done_for = today
            log.info("Running weekly backtest...")
            try:
                subprocess.run(
                    [sys.executable, "-m", "tiger.weekly_backtest"], timeout=1800)
            except Exception as exc:
                log.error("Weekly backtest failed: %s", exc)

        time.sleep(30)


if __name__ == "__main__":
    main()
