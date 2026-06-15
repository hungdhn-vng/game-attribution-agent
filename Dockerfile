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
ENV OPENCLAW_CONFIG_DIR=/home/node/.openclaw \
    OPENCLAW_URL=http://127.0.0.1:18789 \
    GAA_CACHE_DIR=/home/node/.gaa \
    GAA_DB_PATH=/home/node/.gaa/gaa.sqlite \
    GAA_RUN_SIDECAR=/home/node/.gaa/last_run.json
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=6 \
  CMD curl -fsS http://127.0.0.1:8080/health || exit 1
USER node
ENTRYPOINT ["tini", "-s", "--"]
CMD ["/opt/gaa/entrypoint.sh"]
