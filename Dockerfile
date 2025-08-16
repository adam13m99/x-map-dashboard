# Updated to work with enhanced run_production.py and config.py
FROM python:3.12.7-slim

# Set memory optimization environment variables at container level
# These match the settings in config.py for consistent memory management
ENV MALLOC_ARENA_MAX=2 \
    MALLOC_MMAP_THRESHOLD_=131072 \
    MALLOC_TRIM_THRESHOLD_=131072 \
    MALLOC_TOP_PAD_=131072 \
    MALLOC_MMAP_MAX_=65536

# Production environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FLASK_ENV=production \
    DEBUG=false \
    LOG_LEVEL=INFO

# Resource management settings (can be overridden at runtime)
ENV MAX_WORKERS=6 \
    MAX_MEMORY_GB=4.0 \
    REQUEST_TIMEOUT=120 \
    WORKER_COUNT=6 \
    PAGE_SIZE=100000 \
    CACHE_SIZE=100

WORKDIR /app

# Install system dependencies required by geospatial libraries + psutil monitoring
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Build tools
    g++ \
    gcc \
    build-essential \
    # Geospatial system libraries
    libspatialindex-dev \
    libgdal-dev \
    gdal-bin \
    libgeos-dev \
    libproj-dev \
    # Additional dependencies for system monitoring (psutil)
    python3-dev \
    # Utilities for health checks and debugging
    curl \
    procps \
    # Clean up in same layer to reduce image size
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /tmp/* \
    && rm -rf /var/tmp/*

# Copy requirements and install Python dependencies
COPY requirements.txt ./

# Install Python packages with optimizations
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt && \
    # Verify critical packages installed correctly
    python -c "import geopandas, shapely, psutil; print('✅ Critical packages verified')" && \
    # Clean up pip cache
    pip cache purge && \
    rm -rf /tmp/* && \
    rm -rf /var/tmp/*

# Copy application source
COPY . .

# Create necessary directories and set permissions
RUN mkdir -p logs tmp && \
    chmod -R 755 public/ logs/ tmp/ && \
    # Verify all required files are present
    ls -la app.py config.py run_production.py || exit 1

# Create non-root user for security
RUN groupadd -r appuser && \
    useradd -r -g appuser appuser && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose the application port
EXPOSE 5001

# Enhanced health check that works with the new error handling
HEALTHCHECK --interval=30s --timeout=15s --start-period=60s --retries=3 \
    CMD python -c " \
import sys, requests; \
try: \
    response = requests.get('http://localhost:5001/api/initial-data', timeout=10); \
    print(f'Health check: HTTP {response.status_code}'); \
    sys.exit(0 if response.status_code == 200 else 1); \
except requests.exceptions.ConnectionError: \
    print('Health check: Connection refused - app may be starting'); \
    sys.exit(1); \
except Exception as e: \
    print(f'Health check failed: {e}'); \
    sys.exit(1); \
" || exit 1

# Add labels for better container management
LABEL maintainer="Map Dashboard Team" \
      version="2.0" \
      description="Geospatial Map Dashboard with optimized memory management" \
      memory_optimized="true" \
      psutil_monitoring="true"

# Run the enhanced production server
CMD ["python", "run_production.py"]
