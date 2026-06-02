#!/bin/bash
# Tiger Sovereign — auto-start script
# Runs at 08:00 ET Mon-Fri via crontab
# Starts the dashboard and waits for market open to launch the bot

PROJECT="$HOME/projects/trading-bot"
LOG_DIR="$PROJECT/logs"
mkdir -p "$LOG_DIR"

TODAY=$(date +%Y-%m-%d)
DASH_LOG="$LOG_DIR/dashboard_$TODAY.log"
BOT_LOG="$LOG_DIR/bot_$TODAY.log"

# Kill any existing instances
pkill -f "streamlit run app.py" 2>/dev/null
pkill -f "python run.py" 2>/dev/null
sleep 2

cd "$PROJECT"

# Start dashboard
/Users/julianlupolover/projects/trading-bot/.venv/bin/python \
    -m streamlit run app.py --server.port 8530 \
    >> "$DASH_LOG" 2>&1 &

echo "[$(date)] Dashboard started (PID $!)" >> "$LOG_DIR/start.log"

# Wait 10s for dashboard to load, then start the bot
sleep 10

/Users/julianlupolover/projects/trading-bot/.venv/bin/python \
    run.py >> "$BOT_LOG" 2>&1 &

echo "[$(date)] Bot started (PID $!)" >> "$LOG_DIR/start.log"
