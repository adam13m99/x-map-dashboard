import os
# Apply memory optimization settings immediately when config is imported
# These environment variables optimize memory allocation for geospatial workloads
os.environ.setdefault('MALLOC_ARENA_MAX', '2')
os.environ.setdefault('MALLOC_MMAP_THRESHOLD_', '131072')
os.environ.setdefault('MALLOC_TRIM_THRESHOLD_', '131072')
os.environ.setdefault('MALLOC_TOP_PAD_', '131072')
os.environ.setdefault('MALLOC_MMAP_MAX_', '65536')

# Metabase connection details
METABASE_URL = os.getenv("METABASE_URL", "https://metabase.ofood.cloud")
METABASE_USERNAME = os.getenv("METABASE_USERNAME", "xmap@ofood.cloud")
METABASE_PASSWORD = os.getenv("METABASE_PASSWORD", "METABASE_PASSWORD")

# Metabase question IDs
ORDER_DATA_QUESTION_ID = int(os.getenv("ORDER_DATA_QUESTION_ID", "5822"))
VENDOR_DATA_QUESTION_ID = int(os.getenv("VENDOR_DATA_QUESTION_ID", "5045"))

# Performance tuning - configurable via environment variables
WORKER_COUNT = int(os.getenv("WORKER_COUNT", "6"))
PAGE_SIZE = int(os.getenv("PAGE_SIZE", "100000"))

# Cache configuration
CACHE_SIZE = int(os.getenv("CACHE_SIZE", "100"))

# Memory optimization settings (can be overridden via environment)
MEMORY_OPTIMIZATION = {
    'MALLOC_ARENA_MAX': os.getenv('MALLOC_ARENA_MAX', '2'),
    'MALLOC_MMAP_THRESHOLD_': os.getenv('MALLOC_MMAP_THRESHOLD_', '131072'),
    'MALLOC_TRIM_THRESHOLD_': os.getenv('MALLOC_TRIM_THRESHOLD_', '131072'),
    'MALLOC_TOP_PAD_': os.getenv('MALLOC_TOP_PAD_', '131072'),
    'MALLOC_MMAP_MAX_': os.getenv('MALLOC_MMAP_MAX_', '65536'),
}

# Apply memory settings
for key, value in MEMORY_OPTIMIZATION.items():
    os.environ[key] = value

# Production settings
DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")
FLASK_ENV = os.getenv("FLASK_ENV", "production")

# City boundaries for grid generation (approximate)
city_boundaries = {
    "tehran": {"min_lat": 35.5, "max_lat": 35.85, "min_lng": 51.1, "max_lng": 51.7},
    "mashhad": {"min_lat": 36.15, "max_lat": 36.45, "min_lng": 59.35, "max_lng": 59.8},
    "shiraz": {"min_lat": 29.5, "max_lat": 29.75, "min_lng": 52.4, "max_lng": 52.7},
}

# Resource limits (configurable)
MAX_MEMORY_GB = float(os.getenv("MAX_MEMORY_GB", "4.0"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "6"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "120"))

# Logging configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")

print(f"🔧 Memory optimization applied: {MEMORY_OPTIMIZATION}")
print(f"📊 Performance settings: Workers={WORKER_COUNT}, Cache={CACHE_SIZE}, PageSize={PAGE_SIZE}")
print(f"🚀 Environment: {FLASK_ENV}, Debug={DEBUG}")
