#!/bin/bash
# Tiger Sovereign — stop script
# Runs at 16:30 ET Mon-Fri via crontab

PROJECT="$HOME/projects/trading-bot"
UV="$HOME/.local/bin/uv"

# Record the day's REAL results to the permanent track record BEFORE killing
# anything (needs the account state; the bot itself is already idle post-close).
cd "$PROJECT"
"$UV" run python -m tiger.eod_report >> "$PROJECT/logs/eod_$(date +%Y-%m-%d).log" 2>&1

# Stop the bot process first so it can't re-open anything mid-flatten
pkill -f "python run.py" 2>/dev/null
sleep 2

# SAFETY NET: force-flatten any open positions so NOTHING carries overnight,
# even if the bot's internal 15:49 EOD flush didn't fire (e.g. it died early).
"$UV" run python -c "from tiger import broker; broker.close_all_positions()" \
    >> "$PROJECT/logs/eod_$(date +%Y-%m-%d).log" 2>&1

# Stop the rest
pkill -f "streamlit run app.py" 2>/dev/null
pkill -f "caffeinate -i -s -t" 2>/dev/null

echo "[$(date)] Stopped + flattened + EOD recorded." >> "$PROJECT/logs/start.log"
