FROM python:3.12-slim

WORKDIR /app

# Install system deps for lxml/scipy
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libxml2-dev libxslt1-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps (API-only, no heavy causal libs)
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

# Optional: install tigramite/dowhy/econml if they work (non-fatal)
RUN pip install --no-cache-dir tigramite>=5.2.0 || true
RUN pip install --no-cache-dir dowhy>=0.11 econml>=0.15.0 || true

# Copy source
COPY src/ src/

# Expose port (Railway sets PORT env var dynamically)
EXPOSE 8000

# Run the API server — use $PORT if set (Railway), else 8000
CMD ["sh", "-c", "uvicorn src.api.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
