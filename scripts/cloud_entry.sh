#!/bin/bash
# Container entrypoint: dashboard (background) + scheduler (foreground).
set -e
cd /app

# One-time seed: if the volume is fresh, carry over the laptop-era history
for f in seed_data/*.jsonl; do
    base=$(basename "$f")
    [ -f "data/$base" ] || cp "$f" "data/$base"
done

# Dashboard on Railway's $PORT
uv run streamlit run app.py \
    --server.port "${PORT:-8530}" \
    --server.address 0.0.0.0 \
    --server.headless true &

# Scheduler supervises the trading day; keeps the container alive
exec uv run python scheduler.py
