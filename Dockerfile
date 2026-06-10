# Tiger Sovereign — Railway deployment
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

# tzdata so ZoneInfo("America/New_York") resolves in the slim image
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first (layer cache), then the project
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

COPY . .

# data/ is a Railway volume (track record + live log persist across deploys)
RUN mkdir -p data logs

CMD ["bash", "scripts/cloud_entry.sh"]
