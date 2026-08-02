# ULTRA Algorithmic Trading Platform
FROM python:3.12-slim

LABEL org.opencontainers.image.title="ULTRA Algorithmic Trading Platform" \
      org.opencontainers.image.description="Paper/live automated trading platform (Deriv + Binance)" \
      org.opencontainers.image.source="https://github.com/mickeymichael130-coder/ultra_trading_platform"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps (curl only needed if you extend the healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Python deps (cached as a layer)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App code (src, config, main, docs)
COPY src ./src
COPY config ./config
COPY main.py .
COPY VERSION .
COPY BLUEPRINT_CHECKLIST.md ./

# Runtime state lives in volumes; never bake secrets into the image
VOLUME ["/app/data", "/app/logs", "/app/backups"]

# Run as an unprivileged user
RUN useradd --create-home --uid 1000 ultra \
    && mkdir -p /app/data /app/logs /app/backups \
    && chown -R ultra:ultra /app
USER ultra

EXPOSE 8501

# Mode/broker come from the environment (docker-compose / --env-file).
# Default to paper + binance (public market data, no token required).
CMD ["python", "main.py", "--mode", "paper", "--broker", "binance"]
