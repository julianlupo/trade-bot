#!/bin/bash
# Tiger Sovereign — weekly backtest tracker
# Runs Sat (after the trading week) via crontab. Logs expectancy over time.

PROJECT="$HOME/projects/trading-bot"
UV="$HOME/.local/bin/uv"
cd "$PROJECT"
"$UV" run python -m tiger.weekly_backtest >> "$PROJECT/logs/weekly_$(date +%Y-%m-%d).log" 2>&1
echo "[$(date)] Weekly backtest recorded." >> "$PROJECT/logs/start.log"
