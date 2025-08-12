# Dockerfile for Map Dashboard application
FROM python:3.12.7-slim

WORKDIR /app

# Install system dependencies required by geospatial libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    g++ \
    libspatialindex-dev \
    libgdal-dev \
    gdal-bin \
    libgeos-dev \
    libproj-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Ensure public directory is accessible
RUN chmod -R 755 public/

# Create non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser appuser
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 5001

# Run the production server by default
CMD ["python", "run_production.py"]
