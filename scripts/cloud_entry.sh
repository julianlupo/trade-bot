#!/bin/bash
# Container entrypoint: dashboard (background) + scheduler (foreground).
set -e
cd /app

# Dashboard on Railway's $PORT
uv run streamlit run app.py \
    --server.port "${PORT:-8530}" \
    --server.address 0.0.0.0 \
    --server.headless true &

# Scheduler supervises the trading day; keeps the container alive
exec uv run python scheduler.py
