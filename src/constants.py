"""Application-wide constants for BigBrotr services."""

# Database connection pool settings
DB_POOL_MIN_SIZE_PER_WORKER = 2
DB_POOL_MAX_SIZE_PER_WORKER = 5

# Health check server settings
HEALTH_CHECK_PORT = 8080

# Time constants
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400

# Timeout multipliers
RELAY_TIMEOUT_MULTIPLIER = 2

# Binary search constants for relay processing
BINARY_SEARCH_MIN_RANGE = 1

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
