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

# Performance tuning - MODIFIED for single worker debugging
# Force single worker to debug SIGKILL issues
WORKER_COUNT = int(os.getenv("WORKER_COUNT", "1"))  # CHANGED: Force 1 worker
PAGE_SIZE = int(os.getenv("PAGE_SIZE", "50000"))  # REDUCED: Smaller page size for debugging

# Cache configuration - reduced for single worker
CACHE_SIZE = int(os.getenv("CACHE_SIZE", "50"))  # REDUCED: Smaller cache for single worker

# AUTO-REFRESH CONFIGURATION - NEW: Add auto-refresh settings
ENABLE_AUTO_REFRESH = os.getenv("ENABLE_AUTO_REFRESH", "True").lower() in ("true", "1", "yes")
VENDOR_REFRESH_INTERVAL_MINUTES = int(os.getenv("VENDOR_REFRESH_INTERVAL_MINUTES", "10"))
ORDER_REFRESH_INTERVAL_MINUTES = int(os.getenv("ORDER_REFRESH_INTERVAL_MINUTES", "720"))  # Orders refresh less frequently
REFRESH_ON_STARTUP_DELAY_SECONDS = int(os.getenv("REFRESH_ON_STARTUP_DELAY_SECONDS", "120"))  # Wait 2 minutes after startup
AUTO_REFRESH_MAX_RETRIES = int(os.getenv("AUTO_REFRESH_MAX_RETRIES", "3"))
AUTO_REFRESH_RETRY_DELAY_SECONDS = int(os.getenv("AUTO_REFRESH_RETRY_DELAY_SECONDS", "30"))

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

# Production settings - MODIFIED for debugging
DEBUG = os.getenv("DEBUG", "True").lower() in ("true", "1", "yes")  # CHANGED: Enable debug by default
FLASK_ENV = os.getenv("FLASK_ENV", "development")  # CHANGED: Development mode for debugging

# TIMEOUT SETTINGS - NEW: Add timeout configurations
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "300"))  # INCREASED: 5 minutes instead of 2
GRACEFUL_TIMEOUT = int(os.getenv("GRACEFUL_TIMEOUT", "60"))  # NEW: Graceful shutdown timeout
KEEPALIVE_TIMEOUT = int(os.getenv("KEEPALIVE_TIMEOUT", "5"))  # NEW: Connection keepalive

# WORKER SETTINGS - NEW: Add worker-specific configurations
MAX_REQUESTS = int(os.getenv("MAX_REQUESTS", "100"))  # REDUCED: Force worker recycling for debugging
MAX_REQUESTS_JITTER = int(os.getenv("MAX_REQUESTS_JITTER", "20"))  # NEW: Small jitter
WORKER_CONNECTIONS = int(os.getenv("WORKER_CONNECTIONS", "100"))  # REDUCED: Conservative connection limit

# City boundaries for grid generation (approximate)
city_boundaries = {
    "tehran": {"min_lat": 35.5, "max_lat": 35.85, "min_lng": 51.1, "max_lng": 51.7},
    "mashhad": {"min_lat": 36.15, "max_lat": 36.45, "min_lng": 59.35, "max_lng": 59.8},
    "shiraz": {"min_lat": 29.5, "max_lat": 29.75, "min_lng": 52.4, "max_lng": 52.7},
}

# Resource limits (configurable) - MODIFIED for debugging
MAX_MEMORY_GB = float(os.getenv("MAX_MEMORY_GB", "4.0"))  # Conservative memory limit
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "1"))  # CHANGED: Force 1 worker max

# Logging configuration - ENHANCED for debugging
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")  # CHANGED: More verbose logging
LOG_FORMAT = os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# DEBUGGING FLAGS - NEW: Add debugging-specific settings
ENABLE_PROFILING = os.getenv("ENABLE_PROFILING", "False").lower() in ("true", "1", "yes")
ENABLE_REQUEST_LOGGING = os.getenv("ENABLE_REQUEST_LOGGING", "True").lower() in ("true", "1", "yes")
ENABLE_MEMORY_MONITORING = os.getenv("ENABLE_MEMORY_MONITORING", "True").lower() in ("true", "1", "yes")

# DATA LOADING SETTINGS - NEW: Add data loading configurations
CONTINUE_WITHOUT_DATA = os.getenv("CONTINUE_WITHOUT_DATA", "False").lower() in ("true", "1", "yes")
DATA_LOADING_TIMEOUT = int(os.getenv("DATA_LOADING_TIMEOUT", "600"))  # 10 minutes for data loading

# METABASE SETTINGS - MODIFIED for debugging
METABASE_TIMEOUT = int(os.getenv("METABASE_TIMEOUT", "120"))  # 2 minutes per query
METABASE_RETRY_COUNT = int(os.getenv("METABASE_RETRY_COUNT", "3"))  # Number of retries
METABASE_WORKERS = int(os.getenv("METABASE_WORKERS", "4"))  # REDUCED: Fewer parallel workers

# TEMP DIRECTORY SETTINGS - NEW: Force RAM-based temp directory
WORKER_TMP_DIR = os.getenv("WORKER_TMP_DIR", "/dev/shm" if os.path.exists("/dev/shm") else "/tmp")

# FILE SYSTEM SETTINGS - NEW: Add file handling settings
USE_SENDFILE = os.getenv("USE_SENDFILE", "False").lower() in ("true", "1", "yes")  # Disable sendfile for debugging

# CONTAINER DETECTION - NEW: Add container-specific settings
IS_CONTAINER = os.path.exists('/.dockerenv') or os.getenv('IS_CONTAINER', 'False').lower() in ('true', '1', 'yes')
CONTAINER_MEMORY_LIMIT = os.getenv('CONTAINER_MEMORY_LIMIT', None)  # Container memory limit if known

# NEW: MULTI-PLATFORM VENDOR DATA PATHS
# Snappfood vendor data path
SF_VENDORS_CSV_PATH = os.getenv("SF_VENDORS_CSV_PATH", "src/vendor/sf_vendors.csv")

# Enhanced graded data path (now includes dual vendor mapping)
GRADED_CSV_PATH = os.getenv("GRADED_CSV_PATH", "src/vendor/graded.csv")

# VENDOR MAP TYPE SETTINGS - NEW: Configuration for vendor display modes
DEFAULT_VENDOR_MAP_TYPE = os.getenv("DEFAULT_VENDOR_MAP_TYPE", "tapsifood_only")

VENDOR_MAP_TYPES = {
    "tapsifood_only": {
        "name": "Tapsifood Only",
        "description": "Show only Tapsifood vendors from Metabase",
        "sources": ["metabase"],
        "default": True
    },
    "all_snappfood": {
        "name": "All Snappfood Vendors", 
        "description": "Show all Snappfood vendors from CSV",
        "sources": ["snappfood"],
        "default": False
    },
    "snappfood_exclude_tapsifood": {
        "name": "Snappfood Exclude Tapsifood",
        "description": "Show Snappfood vendors not in Tapsifood",
        "sources": ["snappfood_only"], 
        "default": False
    },
    "combined_no_overlap": {
        "name": "Tapsifood + Snappfood Exclude Tapsifood",
        "description": "Show Tapsifood + unique Snappfood vendors",
        "sources": ["metabase", "snappfood_only"],
        "default": False
    }
}

# DEBUGGING HELPERS - NEW: Add debugging utilities
def print_config_summary():
    """Print a summary of current configuration for debugging"""
    print("🔧 Configuration Summary:")
    print(f"   Workers: {WORKER_COUNT} (DEBUG: FORCED TO 1)")
    print(f"   Request Timeout: {REQUEST_TIMEOUT}s (DEBUG: EXTENDED)")
    print(f"   Page Size: {PAGE_SIZE} (DEBUG: REDUCED)")
    print(f"   Cache Size: {CACHE_SIZE} (DEBUG: REDUCED)")
    print(f"   Debug Mode: {DEBUG}")
    print(f"   Log Level: {LOG_LEVEL}")
    print(f"   Worker Temp Dir: {WORKER_TMP_DIR}")
    print(f"   Max Requests per Worker: {MAX_REQUESTS} (DEBUG: LOW FOR RECYCLING)")
    
    # NEW: Print multi-platform vendor configuration
    print(f"🏪 Multi-Platform Vendor Configuration:")
    print(f"   Snappfood CSV: {SF_VENDORS_CSV_PATH}")
    print(f"   Enhanced Graded CSV: {GRADED_CSV_PATH}")
    print(f"   Default Vendor Map Type: {DEFAULT_VENDOR_MAP_TYPE}")
    print(f"   Available Vendor Types: {len(VENDOR_MAP_TYPES)}")
    for vmt_key, vmt_config in VENDOR_MAP_TYPES.items():
        status = "(DEFAULT)" if vmt_config.get("default") else ""
        print(f"     • {vmt_config['name']} {status}")
    
    # NEW: Print auto-refresh configuration
    print(f"🔄 Auto-Refresh Configuration:")
    print(f"   Auto-Refresh Enabled: {ENABLE_AUTO_REFRESH}")
    if ENABLE_AUTO_REFRESH:
        print(f"   Vendor Refresh Interval: {VENDOR_REFRESH_INTERVAL_MINUTES} minutes")
        print(f"   Order Refresh Interval: {ORDER_REFRESH_INTERVAL_MINUTES} minutes")
        print(f"   Startup Delay: {REFRESH_ON_STARTUP_DELAY_SECONDS} seconds")
        print(f"   Max Retries: {AUTO_REFRESH_MAX_RETRIES}")
        print(f"   Retry Delay: {AUTO_REFRESH_RETRY_DELAY_SECONDS} seconds")
    
    if IS_CONTAINER:
        print(f"   Container Mode: DETECTED")
        if CONTAINER_MEMORY_LIMIT:
            print(f"   Container Memory Limit: {CONTAINER_MEMORY_LIMIT}")
    
    if ENABLE_PROFILING:
        print(f"   Profiling: ENABLED")
    
    if CONTINUE_WITHOUT_DATA:
        print(f"   Continue Without Data: ENABLED (DEBUG MODE)")

def check_memory_optimization():
    """Check if memory optimization settings are applied"""
    applied_settings = {}
    for key, expected_value in MEMORY_OPTIMIZATION.items():
        actual_value = os.environ.get(key)
        applied_settings[key] = {
            'expected': expected_value,
            'actual': actual_value,
            'applied': actual_value == expected_value
        }
    
    all_applied = all(setting['applied'] for setting in applied_settings.values())
    
    if all_applied:
        print("✅ All memory optimization settings applied correctly")
    else:
        print("⚠️  Some memory optimization settings not applied:")
        for key, setting in applied_settings.items():
            if not setting['applied']:
                print(f"   {key}: expected {setting['expected']}, got {setting['actual']}")
    
    return all_applied

# VALIDATION FUNCTIONS - NEW: Add configuration validation
def validate_config():
    """Validate configuration settings and warn about potential issues"""
    issues = []
    
    # Check worker count
    if WORKER_COUNT != 1:
        issues.append(f"Worker count is {WORKER_COUNT}, should be 1 for debugging")
    
    # Check timeout settings
    if REQUEST_TIMEOUT < 300:
        issues.append(f"Request timeout is {REQUEST_TIMEOUT}s, consider increasing to 300s+ for debugging")
    
    # Check debug mode
    if not DEBUG:
        issues.append("Debug mode is disabled, consider enabling for troubleshooting")
    
    # Check cache size
    if CACHE_SIZE > 100:
        issues.append(f"Cache size is {CACHE_SIZE}, consider reducing for single worker")
    
    # Check temp directory
    if WORKER_TMP_DIR.startswith('/tmp') and os.path.exists('/dev/shm'):
        issues.append("Using disk-based temp directory, consider using /dev/shm for better performance")
    
    # NEW: Validate auto-refresh settings
    if ENABLE_AUTO_REFRESH:
        if VENDOR_REFRESH_INTERVAL_MINUTES < 1:
            issues.append(f"Vendor refresh interval is {VENDOR_REFRESH_INTERVAL_MINUTES} minutes, should be at least 1")
        if ORDER_REFRESH_INTERVAL_MINUTES < 5:
            issues.append(f"Order refresh interval is {ORDER_REFRESH_INTERVAL_MINUTES} minutes, should be at least 5")
        if AUTO_REFRESH_MAX_RETRIES < 1:
            issues.append(f"Auto-refresh max retries is {AUTO_REFRESH_MAX_RETRIES}, should be at least 1")
    
    # NEW: Validate multi-platform vendor settings
    if not os.path.exists(SF_VENDORS_CSV_PATH):
        issues.append(f"Snappfood vendors CSV not found: {SF_VENDORS_CSV_PATH}")
    
    if not os.path.exists(GRADED_CSV_PATH):
        issues.append(f"Graded vendors CSV not found: {GRADED_CSV_PATH}")
    
    if DEFAULT_VENDOR_MAP_TYPE not in VENDOR_MAP_TYPES:
        issues.append(f"Invalid default vendor map type: {DEFAULT_VENDOR_MAP_TYPE}")
    
    if issues:
        print("⚠️  Configuration Issues Found:")
        for issue in issues:
            print(f"   • {issue}")
    else:
        print("✅ Configuration validation passed")
    
    return len(issues) == 0

# AUTO-EXECUTION - Run checks when config is imported
if __name__ != "__main__":
    # Only run auto-checks when imported as module, not when run directly
    pass
else:
    # When run directly, show full configuration details
    print("🔧 MAP DASHBOARD CONFIGURATION (MULTI-PLATFORM + DEBUG MODE)")
    print("=" * 60)
    print_config_summary()
    print()
    check_memory_optimization()
    print()
    validate_config()

print(f"🔧 Memory optimization applied: {MEMORY_OPTIMIZATION}")
print(f"📊 Performance settings: Workers={WORKER_COUNT}, Cache={CACHE_SIZE}, PageSize={PAGE_SIZE}")
print(f"🚀 Environment: {FLASK_ENV}, Debug={DEBUG}")
print(f"⏱️  Timeouts: Request={REQUEST_TIMEOUT}s, Graceful={GRACEFUL_TIMEOUT}s")
print(f"🏪 Multi-Platform: Tapsifood + Snappfood support enabled")
if ENABLE_AUTO_REFRESH:
    print(f"🔄 Auto-Refresh: Enabled (Vendors: {VENDOR_REFRESH_INTERVAL_MINUTES}min, Orders: {ORDER_REFRESH_INTERVAL_MINUTES}min)")

# ENVIRONMENT VARIABLE OVERRIDES - NEW: Document available overrides
"""
Available Environment Variable Overrides:
=========================================

Core Settings:
- WORKER_COUNT: Number of workers (default: 1 for debugging)
- REQUEST_TIMEOUT: Request timeout in seconds (default: 300)
- PAGE_SIZE: Metabase page size (default: 50000)
- CACHE_SIZE: Coverage cache size (default: 50)

Multi-Platform Vendor Settings:
- SF_VENDORS_CSV_PATH: Path to Snappfood vendors CSV (default: src/vendor/sf_vendors.csv)
- GRADED_CSV_PATH: Path to enhanced graded CSV (default: src/vendor/graded.csv)
- DEFAULT_VENDOR_MAP_TYPE: Default vendor display mode (default: tapsifood_only)

Auto-Refresh Settings:
- ENABLE_AUTO_REFRESH: Enable automatic data refresh (default: True)
- VENDOR_REFRESH_INTERVAL_MINUTES: Vendor refresh interval (default: 10)
- ORDER_REFRESH_INTERVAL_MINUTES: Order refresh interval (default: 30)
- REFRESH_ON_STARTUP_DELAY_SECONDS: Delay before first refresh (default: 120)
- AUTO_REFRESH_MAX_RETRIES: Max retries on refresh failure (default: 3)
- AUTO_REFRESH_RETRY_DELAY_SECONDS: Delay between retries (default: 30)

Debug Settings:
- DEBUG: Enable debug mode (default: True)
- LOG_LEVEL: Logging level (default: DEBUG)
- ENABLE_PROFILING: Enable performance profiling (default: False)
- CONTINUE_WITHOUT_DATA: Start without data (default: False)

Memory Settings:
- MAX_MEMORY_GB: Maximum memory per worker (default: 4.0)
- WORKER_TMP_DIR: Temporary directory path (default: /dev/shm)

Timeout Settings:
- GRACEFUL_TIMEOUT: Graceful shutdown timeout (default: 60)
- KEEPALIVE_TIMEOUT: Connection keepalive (default: 5)
- DATA_LOADING_TIMEOUT: Data loading timeout (default: 600)

Metabase Settings:
- METABASE_TIMEOUT: Per-query timeout (default: 120)
- METABASE_RETRY_COUNT: Number of retries (default: 3)
- METABASE_WORKERS: Parallel workers (default: 4)

Container Settings:
- IS_CONTAINER: Force container mode (default: auto-detect)
- CONTAINER_MEMORY_LIMIT: Known container memory limit

Examples:
- DEBUG=True WORKER_COUNT=1 python run_production.py
- DEFAULT_VENDOR_MAP_TYPE=all_snappfood python run_production.py
- SF_VENDORS_CSV_PATH=/custom/path/sf_vendors.csv python run_production.py
- ENABLE_AUTO_REFRESH=True VENDOR_REFRESH_INTERVAL_MINUTES=5 python run_production.py
- REQUEST_TIMEOUT=600 LOG_LEVEL=INFO python run_production.py
- CONTINUE_WITHOUT_DATA=True python run_production.py
"""
