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

def calculate_optimal_workers(system_info):
    """Calculate optimal worker count based on system resources"""
    cpu_count = system_info['cpu_count']
    memory_gb = system_info['available_memory_gb']
    
    # Memory-based worker calculation (each worker needs ~200-300MB)
    memory_based_workers = int(memory_gb / 0.3)  # Conservative estimate
    
    # CPU-based worker calculation with caps for different system sizes
    if cpu_count >= 32:
        # High-CPU systems: limit to prevent memory exhaustion
        cpu_based_workers = min(MAX_WORKERS, max(8, cpu_count // 3))
    elif cpu_count >= 16:
        # Medium-high CPU systems
        cpu_based_workers = min(MAX_WORKERS, max(6, cpu_count // 2))
    elif cpu_count >= 8:
        # Medium CPU systems
        cpu_based_workers = min(MAX_WORKERS, cpu_count + 2)
    else:
        # Low CPU systems: standard formula
        cpu_based_workers = min(MAX_WORKERS, (cpu_count * 2) + 1)
    
    # Use the most conservative estimate
    optimal_workers = min(memory_based_workers, cpu_based_workers, MAX_WORKERS)
    
    # Ensure minimum of 2 workers
    return max(2, optimal_workers)

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
    """Run Waitress server for Windows"""
    try:
        from waitress import serve
        print("🏃 Starting Waitress server (Windows)...")
        
        # Waitress configuration optimized for the application
        serve(
            app,
            host=host,
            port=port,
            threads=8,
            connection_limit=1000,
            cleanup_interval=30,
            channel_timeout=120,
            log_socket_errors=True,
            ident='Map-Dashboard'
        )
    except ImportError:
        print("❌ Waitress not installed. Install with: pip install waitress")
        return False
    except Exception as e:
        print(f"❌ Waitress server failed: {e}")
        return False
    
    return True

def run_gunicorn_server(workers, host='0.0.0.0', port=5001):
    """Run Gunicorn server for Linux/Unix"""
    try:
        import gunicorn.app.base
        
        class OptimizedGunicornApp(gunicorn.app.base.BaseApplication):
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
        
        # Optimized Gunicorn configuration
        options = {
            'bind': f'{host}:{port}',
            'workers': workers,
            'worker_class': 'gthread',  # Better for I/O bound applications
            'threads': 2,
            'timeout': REQUEST_TIMEOUT,
            'keepalive': 2,
            'max_requests': 1000,  # Restart workers periodically
            'max_requests_jitter': 100,
            'worker_connections': 1000,
            'preload_app': True,  # Load app before forking
            'worker_tmp_dir': '/dev/shm' if os.path.exists('/dev/shm') else '/tmp',
            
            # Logging
            'accesslog': '-',
            'errorlog': '-',
            'loglevel': LOG_LEVEL.lower(),
            
            # Security and stability
            'limit_request_line': 8190,
            'limit_request_fields': 100,
            'limit_request_field_size': 8190,
            
            # Process naming
            'proc_name': 'map-dashboard',
            
            # Graceful timeout
            'graceful_timeout': 30,
        }
        
        print(f"🏃 Starting Gunicorn server (Linux/Unix)...")
        print(f"   Workers: {workers}")
        print(f"   Threads per worker: {options['threads']}")
        print(f"   Timeout: {options['timeout']}s")
        print(f"   Binding to: {options['bind']}")
        
        app_runner = OptimizedGunicornApp(app, options)
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
            debug=DEBUG,
            threaded=True,
            use_reloader=False
        )
        return True
    except Exception as e:
        print(f"❌ Development server failed: {e}")
        return False

def main():
    """Main server startup function"""
    print("🚀 MAP DASHBOARD PRODUCTION SERVER")
    print("=" * 50)
    
    # Setup signal handlers for graceful shutdown
    setup_signal_handlers()
    
    # Get system information
    system_info = get_system_info()
    print(f"💻 System Info:")
    print(f"   Platform: {system_info['platform']} ({system_info['architecture']})")
    print(f"   CPUs: {system_info['cpu_count']}")
    print(f"   Memory: {system_info['total_memory_gb']:.1f}GB total, {system_info['available_memory_gb']:.1f}GB available")
    
    # Check memory requirements
    if not check_memory_requirements():
        print("⚠️  Memory warning issued but continuing...")
    
    # Calculate optimal worker count
    optimal_workers = calculate_optimal_workers(system_info)
    print(f"⚙️  Calculated optimal workers: {optimal_workers}")
    
    # Pre-load application data
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
    print(f"   Environment: {'Development' if DEBUG else 'Production'}")
    
    # Start appropriate server
    success = False
    
    if is_windows:
        print("🪟 Windows platform detected, using Waitress...")
        success = run_waitress_server(host, port)
    else:
        print("🐧 Linux/Unix platform detected, using Gunicorn...")
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
