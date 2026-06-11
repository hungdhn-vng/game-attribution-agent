FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN pip install --no-cache-dir -e .
ENV GAA_DB_PATH=/app/gaa.sqlite GAA_CACHE_DIR=/app/data/cache
EXPOSE 8080
CMD ["python", "main.py"]
