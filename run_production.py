import os
import sys
import platform
import multiprocessing
import signal
import time
import psutil
import atexit
from pathlib import Path

# Add current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import config first to apply memory optimizations early
try:
    from config import (
        MEMORY_OPTIMIZATION, MAX_WORKERS, REQUEST_TIMEOUT, 
        DEBUG, LOG_LEVEL, MAX_MEMORY_GB,
        # NEW: Auto-refresh settings
        ENABLE_AUTO_REFRESH, VENDOR_REFRESH_INTERVAL_MINUTES,
        ORDER_REFRESH_INTERVAL_MINUTES, print_config_summary
    )
    print("✅ Memory optimization settings applied from config")
    
    # Print enhanced configuration summary with auto-refresh info
    print_config_summary()
    
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
    from app import app, load_data, stop_auto_refresh
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
    """Setup graceful shutdown handlers with auto-refresh cleanup"""
    def signal_handler(signum, frame):
        print(f"\n🛑 Received signal {signum}, shutting down gracefully...")
        
        # NEW: Stop auto-refresh system before shutting down
        try:
            print("🔄 Stopping auto-refresh system...")
            stop_auto_refresh()
            time.sleep(1)  # Give threads time to clean up
            print("✅ Auto-refresh system stopped")
        except Exception as e:
            print(f"⚠️  Error stopping auto-refresh: {e}")
        
        print("👋 Shutdown complete")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # NEW: Also register cleanup function for normal exit
    atexit.register(cleanup_on_exit)

def cleanup_on_exit():
    """Cleanup function called on normal exit"""
    try:
        stop_auto_refresh()
    except:
        pass  # Ignore errors during cleanup

def pre_load_data():
    """Load data with enhanced error handling"""
    print("📊 Loading application data...")
    start_time = time.time()
    
    try:
        load_data()
        load_time = time.time() - start_time
        print(f"✅ Data loading completed in {load_time:.2f} seconds")
        
        # NEW: Show auto-refresh status after data loading
        if ENABLE_AUTO_REFRESH:
            print(f"🔄 Auto-refresh will start in {60}s with intervals:")
            print(f"   📊 Vendors: every {VENDOR_REFRESH_INTERVAL_MINUTES} minutes")
            print(f"   📋 Orders: every {ORDER_REFRESH_INTERVAL_MINUTES} minutes")
        else:
            print("🔄 Auto-refresh is disabled")
        
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
    """Run Waitress server for Windows with increased timeouts and auto-refresh support"""
    try:
        from waitress import serve
        print("🏃 Starting Waitress server (Windows) with auto-refresh support...")
        
        # Enhanced Waitress configuration for auto-refresh compatibility
        serve(
            app,
            host=host,
            port=port,
            threads=4,  # Reduced threads for single worker stability
            connection_limit=500,  # Reduced connections
            cleanup_interval=60,  # Increased cleanup interval
            channel_timeout=300,  # Increased from 120 to 300 seconds
            log_socket_errors=True,
            ident='Map-Dashboard-AutoRefresh',
            # Additional timeout settings for auto-refresh
            send_bytes=18000,  # Increased send buffer
            asyncore_use_poll=True,  # Better for many connections
            # NEW: Enhanced settings for background threads
            max_request_body_size=1073741824,  # 1GB request body limit
        )
    except ImportError:
        print("❌ Waitress not installed. Install with: pip install waitress")
        return False
    except Exception as e:
        print(f"❌ Waitress server failed: {e}")
        return False
    
    return True

def run_gunicorn_server(workers, host='0.0.0.0', port=5001):
    """Run Gunicorn server for Linux/Unix with auto-refresh optimizations"""
    try:
        import gunicorn.app.base
        
        class AutoRefreshOptimizedGunicornApp(gunicorn.app.base.BaseApplication):
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
        
        # Auto-refresh optimized Gunicorn configuration
        options = {
            'bind': f'{host}:{port}',
            'workers': workers,
            'worker_class': 'sync',  # Stick with sync for debugging
            'threads': 1,  # Single thread per worker for cleaner debugging
            
            # EXTENDED TIMEOUTS - Key fix for SIGKILL issues with auto-refresh
            'timeout': 300,  # Increased from 120 to 300 seconds (5 minutes)
            'graceful_timeout': 90,  # Increased for auto-refresh cleanup
            'keepalive': 10,  # Increased keepalive for background threads
            
            # CONSERVATIVE SETTINGS for auto-refresh compatibility
            'max_requests': 200,  # Increased slightly for auto-refresh
            'max_requests_jitter': 50,  # Increased jitter
            'worker_connections': 200,  # Increased for background connections
            'preload_app': False,  # Keep disabled for easier debugging
            
            # MEMORY AND TEMP DIRECTORY OPTIMIZATIONS
            'worker_tmp_dir': '/dev/shm' if os.path.exists('/dev/shm') else '/tmp',
            
            # EXTENSIVE LOGGING for auto-refresh debugging
            'accesslog': '-',
            'errorlog': '-',
            'loglevel': 'debug',  # Maximum logging
            'access_log_format': '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" [%(D)s µs] [Auto-Refresh]',
            
            # SECURITY AND STABILITY
            'limit_request_line': 4096,
            'limit_request_fields': 100,
            'limit_request_field_size': 8190,
            
            # PROCESS NAMING for easier debugging
            'proc_name': 'map-dashboard-auto-refresh',
            
            # AUTO-REFRESH SPECIFIC SETTINGS
            'capture_output': True,  # Capture worker output
            'enable_stdio_inheritance': True,  # Better logging
            
            # WORKER LIFECYCLE MANAGEMENT with auto-refresh considerations
            'max_worker_memory': 4000000000,  # 4GB limit per worker
            'worker_memory_limit': '4GB',  # Alternative memory limit format
            
            # NEW: Auto-refresh friendly settings
            'reuse_port': True,  # Allow port reuse for restart scenarios
            'worker_tmp_dir': '/dev/shm' if os.path.exists('/dev/shm') else '/tmp',
        }
        
        print(f"🏃 Starting Gunicorn server (Linux/Unix) with auto-refresh configuration...")
        print(f"   Workers: {workers} (FORCED TO 1 FOR DEBUGGING)")
        print(f"   Threads per worker: {options['threads']}")
        print(f"   Timeout: {options['timeout']}s (EXTENDED FOR AUTO-REFRESH)")
        print(f"   Graceful timeout: {options['graceful_timeout']}s (EXTENDED)")
        print(f"   Worker temp dir: {options['worker_tmp_dir']}")
        print(f"   Binding to: {options['bind']}")
        print(f"   Max requests per worker: {options['max_requests']} (OPTIMIZED FOR AUTO-REFRESH)")
        print(f"   Auto-refresh compatible: YES")
        
        app_runner = AutoRefreshOptimizedGunicornApp(app, options)
        app_runner.run()
        
    except ImportError:
        print("❌ Gunicorn not installed. Install with: pip install gunicorn")
        return False
    except Exception as e:
        print(f"❌ Gunicorn server failed: {e}")
        return False
    
    return True

def run_development_server(host='127.0.0.1', port=5001):
    """Fallback development server with auto-refresh support"""
    print("🔧 Starting Flask development server with auto-refresh support...")
    try:
        app.run(
            host=host, 
            port=port, 
            debug=True,  # Enable debug for easier troubleshooting
            threaded=True,
            use_reloader=False,  # Disable reloader to avoid conflicts with auto-refresh
            request_handler=None  # Use default handler
        )
        return True
    except Exception as e:
        print(f"❌ Development server failed: {e}")
        return False

def check_system_limits():
    """Check system limits that might affect auto-refresh"""
    print("🔍 Checking system limits for auto-refresh compatibility...")
    
    try:
        # Check file descriptor limits
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        print(f"   File descriptors: {soft} (soft) / {hard} (hard)")
        
        if soft < 1024:
            print("   ⚠️  Low file descriptor limit - might affect auto-refresh")
        
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
            print("   🔄 Auto-refresh threads will run inside container")
        
        # NEW: Check thread limits for auto-refresh
        try:
            import threading
            current_threads = threading.active_count()
            print(f"   Active threads: {current_threads}")
            if ENABLE_AUTO_REFRESH:
                expected_threads = current_threads + 2  # vendor + order refresh threads
                print(f"   Expected with auto-refresh: ~{expected_threads} threads")
        except Exception:
            print("   Thread count: Unable to determine")
            
    except Exception as e:
        print(f"   Could not check limits: {e}")

def check_auto_refresh_compatibility():
    """Check if the system is compatible with auto-refresh"""
    print("🔄 Checking auto-refresh compatibility...")
    
    issues = []
    
    # Check if Metabase connection details are configured
    try:
        from config import METABASE_URL, METABASE_USERNAME, METABASE_PASSWORD
        if not METABASE_URL or METABASE_URL == "https://metabase.ofood.cloud":
            if METABASE_USERNAME == "xmap@ofood.cloud" and METABASE_PASSWORD == "METABASE_PASSWORD":
                issues.append("Default Metabase credentials detected - update config.py with real credentials")
    except ImportError:
        issues.append("Metabase configuration not found")
    
    # Check memory requirements for auto-refresh
    try:
        available_gb = psutil.virtual_memory().available / (1024**3)
        if available_gb < 2.0:
            issues.append(f"Low available memory ({available_gb:.1f}GB) - auto-refresh may cause issues")
    except:
        pass
    
    # Check network connectivity (basic check)
    try:
        import socket
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        print("   ✅ Network connectivity: OK")
    except:
        issues.append("Network connectivity issues detected - may affect Metabase access")
    
    if issues:
        print("   ⚠️  Auto-refresh compatibility issues:")
        for issue in issues:
            print(f"     • {issue}")
        
        if ENABLE_AUTO_REFRESH:
            print("   💡 Consider setting ENABLE_AUTO_REFRESH=False if issues persist")
    else:
        print("   ✅ Auto-refresh compatibility: All checks passed")
    
    return len(issues) == 0

def main():
    """Main server startup function with auto-refresh enhancements"""
    print("🚀 MAP DASHBOARD PRODUCTION SERVER (AUTO-REFRESH ENABLED)")
    print("=" * 70)
    
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
    
    # NEW: Check auto-refresh compatibility
    auto_refresh_compatible = check_auto_refresh_compatibility()
    
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
    
    # NEW: Print auto-refresh information
    if ENABLE_AUTO_REFRESH:
        print(f"🔄 Auto-Refresh Configuration:")
        print(f"   Status: ENABLED")
        print(f"   Vendor refresh: Every {VENDOR_REFRESH_INTERVAL_MINUTES} minutes")
        print(f"   Order refresh: Every {ORDER_REFRESH_INTERVAL_MINUTES} minutes")
        print(f"   Compatibility: {'✅ GOOD' if auto_refresh_compatible else '⚠️  ISSUES DETECTED'}")
    else:
        print(f"🔄 Auto-Refresh: DISABLED")
    
    # Pre-load application data
    print(f"📊 Starting data loading...")
    if not pre_load_data():
        print("❌ Failed to load application data")
        if not os.getenv('CONTINUE_WITHOUT_DATA', 'false').lower() in ('true', '1', 'yes'):
            sys.exit(1)
    
    # Choose server based on platform
    is_windows = system_info['platform'] == 'Windows'
    host = '0.0.0.0'  # Bind to all interfaces for containers
    port = int(os.getenv('PORT', '5001'))
    
    print(f"🌐 Server configuration:")
    print(f"   Host: {host}")
    print(f"   Port: {port}")
    print(f"   Environment: {'Development' if DEBUG else 'Production'} (DEBUG MODE)")
    print(f"   Auto-refresh threads: {'Will start after 2min delay' if ENABLE_AUTO_REFRESH else 'Disabled'}")
    
    # Start appropriate server
    success = False
    
    if is_windows:
        print("🪟 Windows platform detected, using Waitress with auto-refresh support...")
        success = run_waitress_server(host, port)
    else:
        print("🐧 Linux/Unix platform detected, using Gunicorn with auto-refresh support...")
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
