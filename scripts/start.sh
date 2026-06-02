#!/bin/bash
# Tiger Sovereign — auto-start script
# Runs at 08:00 ET Mon-Fri via crontab

PROJECT="$HOME/projects/trading-bot"
UV="$HOME/.local/bin/uv"
LOG_DIR="$PROJECT/logs"
mkdir -p "$LOG_DIR"

TODAY=$(date +%Y-%m-%d)
DASH_LOG="$LOG_DIR/dashboard_$TODAY.log"
BOT_LOG="$LOG_DIR/bot_$TODAY.log"

# Kill any stale instances from a previous day
pkill -f "streamlit run app.py" 2>/dev/null
pkill -f "python run.py" 2>/dev/null
sleep 2

cd "$PROJECT"

# Start dashboard
"$UV" run streamlit run app.py --server.port 8530 >> "$DASH_LOG" 2>&1 &
echo "[$(date)] Dashboard started (PID $!)" >> "$LOG_DIR/start.log"

# Give dashboard 10s to load, then start the bot
sleep 10

"$UV" run python run.py >> "$BOT_LOG" 2>&1 &
echo "[$(date)] Bot started (PID $!)" >> "$LOG_DIR/start.log"
