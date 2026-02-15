FROM python:3.11-slim

WORKDIR /app

# Install system dependencies.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code.
COPY . .

# Copy shared config.
COPY ../shared /app/shared
# Note: In docker-compose, we mount shared/ as a volume instead.

# Expose API port.
EXPOSE 8000

# Default: run the API server.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
