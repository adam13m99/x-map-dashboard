import os

# Metabase connection details
METABASE_URL = "https://metabase.ofood.cloud"
METABASE_USERNAME = "ME|TABASE_USERNAME"
METABASE_PASSWORD = "METABASE_PASSWORD"

# Metabase question IDs
ORDER_DATA_QUESTION_ID = 5822
VENDOR_DATA_QUESTION_ID = 5045

# Performance tuning
WORKER_COUNT = 10
PAGE_SIZE = 100000

# Cache configuration
CACHE_SIZE = 100

# City boundaries for grid generation (approximate)
city_boundaries = {
    "tehran": {"min_lat": 35.5, "max_lat": 35.85, "min_lng": 51.1, "max_lng": 51.7},
    "mashhad": {"min_lat": 36.15, "max_lat": 36.45, "min_lng": 59.35, "max_lng": 59.8},
    "shiraz": {"min_lat": 29.5, "max_lat": 29.75, "min_lng": 52.4, "max_lng": 52.7},
}
