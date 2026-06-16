FROM ghcr.io/openclaw/openclaw:latest
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-dev build-essential curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/gaa
COPY pyproject.toml ./
COPY src ./src
RUN pip3 install --no-cache-dir --break-system-packages ".[server]"
COPY openclaw /opt/gaa/openclaw
COPY scripts/entrypoint.sh /opt/gaa/entrypoint.sh
RUN chmod +x /opt/gaa/entrypoint.sh && chmod -R a+rX /opt/gaa
ENV OPENCLAW_HOME=/home/node/.openclaw \
    OPENCLAW_WORKSPACE=/home/node/.openclaw/workspace \
    OPENCLAW_CONFIG_NONADMIN=/home/node/.openclaw-nonadmin/openclaw.json \
    OPENCLAW_CONFIG_ADMIN=/home/node/.openclaw-admin/openclaw.json \
    OPENCLAW_STATE_NONADMIN=/home/node/.openclaw-nonadmin/state \
    OPENCLAW_STATE_ADMIN=/home/node/.openclaw-admin/state \
    OPENCLAW_URL_NONADMIN=http://127.0.0.1:18789 \
    OPENCLAW_URL_ADMIN=http://127.0.0.1:18790 \
    GAA_CACHE_DIR=/home/node/.gaa \
    GAA_DB_PATH=/home/node/.gaa/gaa.sqlite \
    GAA_RUN_SIDECAR=/home/node/.gaa/last_run.json \
    GAA_PROGRESS=/home/node/.gaa/progress.jsonl
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=6 \
  CMD curl -fsS http://127.0.0.1:8080/health || exit 1
USER node
ENTRYPOINT ["tini", "-s", "--"]
CMD ["/opt/gaa/entrypoint.sh"]
