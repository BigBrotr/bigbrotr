"""Application-wide constants for Bigbrotr services."""
from enum import Enum


class NetworkType(str, Enum):
    """Relay network types."""
    CLEARNET = "clearnet"
    TOR = "tor"


# Database connection pool settings
DB_POOL_MIN_SIZE_PER_WORKER = 2
DB_POOL_MAX_SIZE_PER_WORKER = 5
DB_POOL_ACQUIRE_TIMEOUT = 30  # seconds to wait for connection from pool

# Health check server settings
HEALTH_CHECK_PORT = 8080

# Time constants
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400

# Timeout multipliers
RELAY_TIMEOUT_MULTIPLIER = 2

# Binary search constants for relay processing
BINARY_SEARCH_MIN_RANGE = 1

# Retry and backoff settings
DEFAULT_MAX_RETRIES = 5
DEFAULT_RETRY_BASE_DELAY = 1  # seconds
DEFAULT_DB_RETRY_DELAY = 30  # seconds for database operations
DEFAULT_DB_OPERATION_RETRIES = 3  # retries for individual database operations
DEFAULT_DB_OPERATION_RETRY_DELAY = 5  # seconds between database operation retries

# Service shutdown settings
WORKER_GRACEFUL_SHUTDOWN_TIMEOUT = 30  # seconds to wait for workers before termination
WORKER_FORCE_SHUTDOWN_TIMEOUT = 5  # seconds to wait after termination signal

# Relay failure tracking settings
DEFAULT_FAILURE_THRESHOLD = 0.1  # 10% failure rate threshold for alerts
DEFAULT_FAILURE_CHECK_INTERVAL = 100  # Check failure rate every N relays

# Default configuration values
DEFAULT_MONITOR_LOOP_INTERVAL_MINUTES = 15
DEFAULT_SYNCHRONIZER_LOOP_INTERVAL_MINUTES = 15
DEFAULT_SYNCHRONIZER_BATCH_SIZE = 500
DEFAULT_SYNCHRONIZER_RELAY_METADATA_THRESHOLD_HOURS = 12
DEFAULT_TORPROXY_TIMEOUT = 10  # seconds for Tor connectivity tests
DEFAULT_INITIALIZER_RETRY_DELAY = 10  # seconds between service readiness checks

# Test URLs for Tor connectivity
TOR_CHECK_HTTP_URL = "https://check.torproject.org"
TOR_CHECK_WS_URL = "wss://echo.websocket.events"

# Logging emoji prefixes (for consistent log parsing)
LOG_PREFIX_ERROR = "❌"
LOG_PREFIX_WARNING = "⚠️"
LOG_PREFIX_SUCCESS = "✅"
LOG_PREFIX_INFO = "📦"
LOG_PREFIX_PROCESS = "🔄"
LOG_PREFIX_WAIT = "⏳"
LOG_PREFIX_START = "🚀"
LOG_PREFIX_SEARCH = "🔍"
LOG_PREFIX_NETWORK = "🌐"
LOG_PREFIX_TIMER = "⏰"
