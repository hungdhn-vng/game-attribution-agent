FROM python:3.11-slim

WORKDIR /app

# System deps kept minimal: browse uses httpx + beautifulsoup4 (pure-Python), no chromium.
COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir -e ".[server]"

EXPOSE 8080
CMD ["uvicorn", "gaa.server.app:app", "--host", "0.0.0.0", "--port", "8080"]
