# Map Dashboard Application - Deployment Guide

## Overview
This is a Flask-based geospatial data visualization application that displays vendor locations, order heatmaps, and coverage analysis on interactive maps. The application connects to Metabase for live data and processes geospatial polygons for area analysis.

## File Structure & Purpose

### Core Application Files

#### `app.py`
**Main Flask application file**
- Contains all API endpoints and business logic
- Handles data loading from Metabase and local CSV files
- Processes geospatial data (polygons, coordinates)
- Generates heatmaps, coverage grids, and vendor markers
- Serves the web interface
- **Key endpoints:**
  - `/` - Serves the main dashboard
  - `/api/initial-data` - Returns dropdown options for filters
  - `/api/map-data` - Main API that returns map data based on filters

#### `config.py`
**Configuration file**
- Contains Metabase connection credentials
- Defines question IDs for data queries
- Sets performance parameters (workers, cache size, page size)
- Defines city boundaries for coverage grid generation
- **Important:** Contains production credentials - handle securely

#### `run_production.py`
**Production server launcher**
- Automatically detects OS (Windows/Linux)
- Uses Waitress server on Windows, Gunicorn on Linux
- Calculates optimal worker count based on CPU cores
- Loads data before starting server
- Binds to `0.0.0.0:5001` for container deployment

#### `mini.py`
**Metabase data fetcher utility**
- Handles authentication with Metabase API
- Fetches data from specific question IDs
- Implements retry logic and error handling
- Used by app.py to get live order and vendor data

### Frontend Files (`public/` directory)

#### `public/index.html`
**Main web interface**
- Single-page application with interactive map
- Filter controls for date, city, business lines, vendor status
- Map layers for vendors, heatmaps, polygons, coverage grid

#### `public/script.js`
**Frontend JavaScript logic**
- Leaflet.js map implementation
- API communication with backend
- Dynamic filter updates
- Heatmap and marker rendering

#### `public/styles.css`
**Styling and layout**
- Responsive design
- Map controls styling
- Loading indicators

### Data Files (`src/` directory)

#### `src/polygons/tapsifood_marketing_areas/`
- `mashhad_polygons.csv` - Marketing area boundaries for Mashhad
- `tehran_polygons.csv` - Marketing area boundaries for Tehran  
- `shiraz_polygons.csv` - Marketing area boundaries for Shiraz
- **Format:** CSV with WKT geometry column

#### `src/polygons/tehran_districts/`
- Shapefile data for Tehran administrative boundaries
- `RegionTehran_WGS1984.*` - Regional districts
- `Tehran_WGS1984.*` - Main city districts
- **Format:** ESRI Shapefiles (shp, dbf, prj, shx)

#### `src/targets/`
- `tehran_coverage.csv` - Target vendor counts per marketing area
- Used for coverage analysis and performance metrics

#### `src/vendor/`
- `graded.csv` - Vendor quality grades/ratings
- Merged with live vendor data for enhanced analytics

### Configuration Files

#### `requirements.txt`
**Python dependencies**
- Flask web framework
- GeoPandas for geospatial data processing
- Pandas/NumPy for data analysis
- Gunicorn/Waitress for production servers
- Scientific computing libraries (SciPy)

#### `Dockerfile`
**Container configuration**
- Based on Python 3.12.7-slim
- Installs geospatial system dependencies (GDAL, GEOS, PROJ)
- Sets up non-root user for security
- Exposes port 5001
- Uses run_production.py as entry point

## Deployment Instructions

### 1. Environment Setup
The application requires these external dependencies:
- **Metabase instance** at `https://metabase.ofood.cloud`
- **Network access** to Metabase API
- **Question IDs 5822 (orders) and 5045 (vendors)** configured in Metabase

### 2. Container Deployment
```bash
# Build the container
docker build -t map-dashboard .

# Run the container
docker run -p 5001:5001 map-dashboard
```

### 3. Configuration
- **Port:** Application runs on port 5001
- **Health Check:** GET `/api/initial-data` should return 200 OK
- **Resource Requirements:** 
  - RAM: 2GB minimum (data processing)
  - CPU: 2+ cores recommended
  - Storage: 500MB for application + data cache

### 4. Data Sources
The application automatically loads:
- **Live data:** From Metabase via API calls
- **Static data:** CSV and shapefile data from src/ directory
- **Cache:** In-memory caching for performance

## Features

### Interactive Map
- Vendor locations with filtering
- Order density heatmaps (total, organic, non-organic)
- User density heatmaps
- Population density visualization
- Coverage grid analysis

### Filtering Options
- **Geographic:** City selection, area filtering
- **Temporal:** Date range selection
- **Business:** Business line filtering
- **Vendor attributes:** Status, grades, visibility, radius

### Performance Features
- Vectorized spatial calculations
- Adaptive heatmap precision based on zoom level
- In-memory caching for coverage calculations
- Optimized data loading with proper data types
