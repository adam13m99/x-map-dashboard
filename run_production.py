import os
import sys
import platform
import multiprocessing
import signal
import time
import psutil
from pathlib import Path

# Add current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import config first to apply memory optimizations early
try:
    from config import (
        MEMORY_OPTIMIZATION, MAX_WORKERS, REQUEST_TIMEOUT, 
        DEBUG, LOG_LEVEL, MAX_MEMORY_GB
    )
    print("✅ Memory optimization settings applied from config")
except ImportError:
    print("⚠️  Config not found, using default memory settings")
    # Apply default memory optimization
    default_memory_settings = {
        'MALLOC_ARENA_MAX': '2',
        'MALLOC_MMAP_THRESHOLD_': '131072', 
        'MALLOC_TRIM_THRESHOLD_': '131072',
        'MALLOC_TOP_PAD_': '131072',
        'MALLOC_MMAP_MAX_': '65536'
    }
    for key, value in default_memory_settings.items():
        os.environ.setdefault(key, value)

# Import app after memory optimization is applied
try:
    from app import app, load_data
except ImportError as e:
    print(f"❌ Failed to import app: {e}")
    print("Make sure app.py is in the current directory")
    sys.exit(1)

def get_system_info():
    """Get system information for optimal configuration"""
    try:
        cpu_count = multiprocessing.cpu_count()
        memory_gb = psutil.virtual_memory().total / (1024**3)
        available_gb = psutil.virtual_memory().available / (1024**3)
        
        return {
            'cpu_count': cpu_count,
            'total_memory_gb': memory_gb,
            'available_memory_gb': available_gb,
            'platform': platform.system(),
            'architecture': platform.architecture()[0]
        }
    except Exception as e:
        print(f"⚠️  Could not get system info: {e}")
        return {
            'cpu_count': multiprocessing.cpu_count(),
            'total_memory_gb': 4.0,
            'available_memory_gb': 2.0,
            'platform': platform.system(),
            'architecture': '64bit'
        }

def calculate_optimal_workers(system_info, force_single=True):
    """
    Calculate optimal worker count based on system resources.
    MODIFIED: Now forces single worker for debugging SIGKILL issues.
    """
    if force_single:
        print("🔧 Forcing single worker for debugging SIGKILL issues")
        return 1
    
    # Original logic kept for reference but not used when force_single=True
    cpu_count = system_info['cpu_count']
    memory_gb = system_info['available_memory_gb']
    
    # FIXED: More conservative memory calculation for large datasets
    # Each worker needs ~2-4GB for this application due to large datasets
    memory_based_workers = max(1, int(memory_gb / 4.0))  # 4GB per worker
    
    # CPU-based worker calculation with lower limits for memory-intensive apps
    if cpu_count >= 32:
        # High-CPU systems: much more conservative due to memory constraints
        cpu_based_workers = min(4, max(2, cpu_count // 8))  # Reduced from //3
    elif cpu_count >= 16:
        # Medium-high CPU systems
        cpu_based_workers = min(3, max(2, cpu_count // 6))  # Reduced from //2
    elif cpu_count >= 8:
        # Medium CPU systems
        cpu_based_workers = min(3, max(2, cpu_count // 4))  # Reduced significantly
    else:
        # Low CPU systems: very conservative
        cpu_based_workers = min(2, max(1, cpu_count))
    
    # Use the most conservative estimate with lower cap
    optimal_workers = min(memory_based_workers, cpu_based_workers, 4)  # Max 4 workers
    
    # Ensure minimum of 1 worker
    return max(1, optimal_workers)

def check_memory_requirements():
    """Check if system has enough memory for the application"""
    try:
        available_gb = psutil.virtual_memory().available / (1024**3)
        if available_gb < 1.0:
            print(f"⚠️  Low memory warning: {available_gb:.1f}GB available")
            print("   Consider reducing worker count or increasing system memory")
            return False
        return True
    except:
        return True  # Assume OK if we can't check

def setup_signal_handlers():
    """Setup graceful shutdown handlers"""
    def signal_handler(signum, frame):
        print(f"\n🛑 Received signal {signum}, shutting down gracefully...")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

def pre_load_data():
    """Load data with enhanced error handling"""
    print("📊 Loading application data...")
    start_time = time.time()
    
    try:
        load_data()
        load_time = time.time() - start_time
        print(f"✅ Data loading completed in {load_time:.2f} seconds")
        return True
    except Exception as e:
        print(f"❌ Critical error during data loading: {e}")
        print("🔧 Troubleshooting suggestions:")
        print("   1. Check Metabase connectivity")
        print("   2. Verify data files exist in src/ directory")
        print("   3. Check system dependencies (GDAL, GEOS, PROJ)")
        print("   4. Review memory allocation")
        
        # Try to continue without data (for debugging)
        user_choice = os.getenv('CONTINUE_WITHOUT_DATA', 'false').lower()
        if user_choice in ('true', '1', 'yes'):
            print("⚠️  Continuing without data (CONTINUE_WITHOUT_DATA=true)")
            return True
        else:
            print("💡 Set CONTINUE_WITHOUT_DATA=true to start server without data")
            return False

def run_waitress_server(host='0.0.0.0', port=5001):
    """Run Waitress server for Windows with increased timeouts"""
    try:
        from waitress import serve
        print("🏃 Starting Waitress server (Windows) with extended timeouts...")
        
        # Waitress configuration optimized for the application with longer timeouts
        serve(
            app,
            host=host,
            port=port,
            threads=4,  # Reduced threads for single worker stability
            connection_limit=500,  # Reduced connections
            cleanup_interval=60,  # Increased cleanup interval
            channel_timeout=300,  # Increased from 120 to 300 seconds
            log_socket_errors=True,
            ident='Map-Dashboard-Debug',
            # Additional timeout settings
            send_bytes=18000,  # Increased send buffer
            asyncore_use_poll=True,  # Better for many connections
        )
    except ImportError:
        print("❌ Waitress not installed. Install with: pip install waitress")
        return False
    except Exception as e:
        print(f"❌ Waitress server failed: {e}")
        return False
    
    return True

def run_gunicorn_server(workers, host='0.0.0.0', port=5001):
    """Run Gunicorn server for Linux/Unix with debugging optimizations"""
    try:
        import gunicorn.app.base
        
        class DebugOptimizedGunicornApp(gunicorn.app.base.BaseApplication):
            def __init__(self, app, options=None):
                self.options = options or {}
                self.application = app
                super().__init__()
            
            def load_config(self):
                for key, value in self.options.items():
                    if key in self.cfg.settings and value is not None:
                        self.cfg.set(key.lower(), value)
            
            def load(self):
                return self.application
        
        # Debugging-optimized Gunicorn configuration
        options = {
            'bind': f'{host}:{port}',
            'workers': workers,
            'worker_class': 'sync',  # Stick with sync for debugging
            'threads': 1,  # Single thread per worker for cleaner debugging
            
            # EXTENDED TIMEOUTS - Key fix for SIGKILL issues
            'timeout': 300,  # Increased from 120 to 300 seconds (5 minutes)
            'graceful_timeout': 60,  # Time to wait for graceful shutdown
            'keepalive': 5,  # Increased keepalive
            
            # CONSERVATIVE SETTINGS for debugging
            'max_requests': 100,  # Low number to force worker recycling
            'max_requests_jitter': 20,  # Small jitter
            'worker_connections': 100,  # Very conservative
            'preload_app': False,  # Disable preload for easier debugging
            
            # MEMORY AND TEMP DIRECTORY OPTIMIZATIONS
            'worker_tmp_dir': '/dev/shm' if os.path.exists('/dev/shm') else '/tmp',
            
            # EXTENSIVE LOGGING for debugging
            'accesslog': '-',
            'errorlog': '-',
            'loglevel': 'debug',  # Maximum logging
            'access_log_format': '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" [%(D)s]',  # Include response time
            
            # SECURITY AND STABILITY
            'limit_request_line': 4096,
            'limit_request_fields': 100,
            'limit_request_field_size': 8190,
            
            # PROCESS NAMING for easier debugging
            'proc_name': 'map-dashboard-debug',
            
            # DEBUGGING-SPECIFIC SETTINGS
            'capture_output': True,  # Capture worker output
            'enable_stdio_inheritance': True,  # Better logging
            
            # WORKER LIFECYCLE MANAGEMENT
            'max_worker_memory': 4000000000,  # 4GB limit per worker (if supported)
            'worker_memory_limit': '4GB',  # Alternative memory limit format
        }
        
        print(f"🏃 Starting Gunicorn server (Linux/Unix) with debugging configuration...")
        print(f"   Workers: {workers} (FORCED TO 1 FOR DEBUGGING)")
        print(f"   Threads per worker: {options['threads']}")
        print(f"   Timeout: {options['timeout']}s (EXTENDED FOR DEBUGGING)")
        print(f"   Graceful timeout: {options['graceful_timeout']}s")
        print(f"   Worker temp dir: {options['worker_tmp_dir']}")
        print(f"   Binding to: {options['bind']}")
        print(f"   Max requests per worker: {options['max_requests']} (LOW FOR DEBUGGING)")
        print(f"   Preload app: {options['preload_app']} (DISABLED FOR DEBUGGING)")
        
        app_runner = DebugOptimizedGunicornApp(app, options)
        app_runner.run()
        
    except ImportError:
        print("❌ Gunicorn not installed. Install with: pip install gunicorn")
        return False
    except Exception as e:
        print(f"❌ Gunicorn server failed: {e}")
        return False
    
    return True

def run_development_server(host='127.0.0.1', port=5001):
    """Fallback development server"""
    print("🔧 Starting Flask development server (fallback)...")
    try:
        app.run(
            host=host, 
            port=port, 
            debug=True,  # Enable debug for easier troubleshooting
            threaded=True,
            use_reloader=False,
            request_handler=None  # Use default handler
        )
        return True
    except Exception as e:
        print(f"❌ Development server failed: {e}")
        return False

def check_system_limits():
    """Check system limits that might cause SIGKILL"""
    print("🔍 Checking system limits...")
    
    try:
        # Check file descriptor limits
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        print(f"   File descriptors: {soft} (soft) / {hard} (hard)")
        
        if soft < 1024:
            print("   ⚠️  Low file descriptor limit - might cause issues")
        
        # Check memory limits (if available)
        try:
            soft_mem, hard_mem = resource.getrlimit(resource.RLIMIT_AS)
            if soft_mem != resource.RLIM_INFINITY:
                print(f"   Memory limit: {soft_mem / (1024**3):.1f}GB")
        except (AttributeError, OSError):
            print("   Memory limit: Not available/unlimited")
            
        # Check if we're in a container
        if os.path.exists('/.dockerenv'):
            print("   🐳 Running inside Docker container")
            print("   💡 Check container memory limits with: docker stats")
        
    except Exception as e:
        print(f"   Could not check limits: {e}")

def main():
    """Main server startup function with debugging enhancements"""
    print("🚀 MAP DASHBOARD PRODUCTION SERVER (DEBUG MODE)")
    print("=" * 60)
    
    # Setup signal handlers for graceful shutdown
    setup_signal_handlers()
    
    # Get system information
    system_info = get_system_info()
    print(f"💻 System Info:")
    print(f"   Platform: {system_info['platform']} ({system_info['architecture']})")
    print(f"   CPUs: {system_info['cpu_count']}")
    print(f"   Memory: {system_info['total_memory_gb']:.1f}GB total, {system_info['available_memory_gb']:.1f}GB available")
    
    # Check system limits
    check_system_limits()
    
    # Check memory requirements
    if not check_memory_requirements():
        print("⚠️  Memory warning issued but continuing...")
    
    # Calculate optimal worker count (FORCED TO 1 FOR DEBUGGING)
    optimal_workers = calculate_optimal_workers(system_info, force_single=True)
    print(f"⚙️  Worker count: {optimal_workers} (FORCED TO 1 FOR DEBUGGING)")
    
    # Print debugging information
    print(f"🔧 Debug Configuration:")
    print(f"   Single worker mode: ENABLED")
    print(f"   Extended timeouts: ENABLED")
    print(f"   Verbose logging: ENABLED")
    print(f"   Preload disabled: ENABLED")
    print(f"   RAM temp directory: ENABLED")
    
    # Pre-load application data
    print(f"📊 Starting data loading...")
    if not pre_load_data():
        print("❌ Failed to load application data")
        sys.exit(1)
    
    # Choose server based on platform
    is_windows = system_info['platform'] == 'Windows'
    host = '0.0.0.0'  # Bind to all interfaces for containers
    port = int(os.getenv('PORT', '5001'))
    
    print(f"🌐 Server configuration:")
    print(f"   Host: {host}")
    print(f"   Port: {port}")
    print(f"   Environment: {'Development' if DEBUG else 'Production'} (DEBUG MODE)")
    
    # Start appropriate server
    success = False
    
    if is_windows:
        print("🪟 Windows platform detected, using Waitress with extended timeouts...")
        success = run_waitress_server(host, port)
    else:
        print("🐧 Linux/Unix platform detected, using Gunicorn with debug configuration...")
        success = run_gunicorn_server(optimal_workers, host, port)
    
    # Fallback to development server if production servers fail
    if not success:
        print("⚠️  Production server failed, falling back to development server...")
        success = run_development_server(host, port)
    
    if not success:
        print("❌ All server options failed")
        sys.exit(1)

if __name__ == '__main__':
    main()
