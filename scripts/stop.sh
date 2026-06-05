#!/bin/bash
# Tiger Sovereign — stop script
# Runs at 16:30 ET Mon-Fri via crontab

PROJECT="$HOME/projects/trading-bot"
UV="$HOME/.local/bin/uv"

# Record the day's REAL results to the permanent track record BEFORE killing
# anything (needs the account state; the bot itself is already idle post-close).
cd "$PROJECT"
"$UV" run python -m tiger.eod_report >> "$PROJECT/logs/eod_$(date +%Y-%m-%d).log" 2>&1

# Now stop the live processes
pkill -f "streamlit run app.py" 2>/dev/null
pkill -f "python run.py" 2>/dev/null
pkill -f "caffeinate -i -s -t" 2>/dev/null

echo "[$(date)] Stopped + EOD recorded." >> "$PROJECT/logs/start.log"
