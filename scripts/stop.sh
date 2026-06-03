#!/bin/bash
# Tiger Sovereign — stop script
# Runs at 16:30 ET Mon-Fri via crontab

pkill -f "streamlit run app.py" 2>/dev/null
pkill -f "python run.py" 2>/dev/null
pkill -f "caffeinate -i -s -t" 2>/dev/null

PROJECT="$HOME/projects/trading-bot"
echo "[$(date)] Stopped." >> "$PROJECT/logs/start.log"
