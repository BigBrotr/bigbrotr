# Core Components Reference

Complete API reference for BigBrotr's core layer (Pool, Brotr, BaseService, MetricsServer, Logger).

## Pool - PostgreSQL Client

**Location**: `src/core/pool.py`

**Note**: In Docker deployments, Pool connects to PGBouncer (port 5432 internal) which handles connection pooling at infrastructure level. The Pool class provides application-level connection management.

### Configuration

```python
from core import Pool, PoolConfig, DatabaseConfig

# From YAML
pool = Pool.from_yaml("config.yaml")

# From dict (Docker: host=pgbouncer, local: host=localhost)
pool = Pool.from_dict({
    "database": {
        "host": "pgbouncer",  # or "localhost" for local dev
        "port": 5432,
        "database": "bigbrotr",
        "user": "admin"
    },
    "limits": {
        "min_size": 5,
        "max_size": 20,
        "max_queries": 50000,
        "max_inactive_connection_lifetime": 300.0
    },
    "timeouts": {
        "acquisition": 10.0,
        "health_check": 5.0
    },
    "retry": {
        "max_attempts": 3,
        "initial_delay": 1.0,
        "max_delay": 10.0,
        "exponential_backoff": True
    }
})
```

**Configuration Models**:
- `DatabaseConfig`: host, port, database, user, password (from `DB_PASSWORD` env)
- `LimitsConfig`: min_size, max_size, max_queries, max_inactive_connection_lifetime
- `TimeoutsConfig`: acquisition, health_check
- `RetryConfig`: max_attempts, initial_delay, max_delay, exponential_backoff
- `ServerSettingsConfig`: application_name, timezone

### Public Methods

#### Connection Lifecycle

```python
async def connect() -> None
```
Establish connection pool with exponential backoff retry. Raises `ConnectionError` if all attempts fail.

```python
async def close() -> None
```
Close pool and release all connections. Thread-safe with lock.

#### Connection Acquisition

```python
def acquire() -> AbstractAsyncContextManager[asyncpg.Connection]
```
Acquire connection from pool. Use with `async with`:
```python
async with pool.acquire() as conn:
    await conn.execute("SELECT 1")
```

```python
async def acquire_healthy(
    max_retries: int = 3,
    health_check_timeout: Optional[float] = None
) -> AsyncIterator[asyncpg.Connection]
```
Acquire connection with health check (`SELECT 1`). Retries on failure.

```python
async def transaction() -> AsyncIterator[asyncpg.Connection]
```
Acquire connection with transaction management. Auto-commit on success, rollback on exception.

#### Query Methods

```python
async def fetch(query: str, *args, timeout: Optional[float] = None) -> list[asyncpg.Record]
```
Execute query and return all rows.

```python
async def fetchrow(query: str, *args, timeout: Optional[float] = None) -> Optional[asyncpg.Record]
```
Execute query and return single row.

```python
async def fetchval(query: str, *args, column: int = 0, timeout: Optional[float] = None) -> Any
```
Execute query and return single value.

```python
async def execute(query: str, *args, timeout: Optional[float] = None) -> str
```
Execute query without returning results. Returns status string.

```python
async def executemany(query: str, args_list: list[tuple], timeout: Optional[float] = None) -> None
```
Execute query multiple times with different parameters.

### Properties

```python
@property
def is_connected() -> bool
```
Check if pool is connected.

```python
@property
def config() -> PoolConfig
```
Get pool configuration.

```python
@property
def metrics() -> dict[str, Any]
```
Get pool metrics: `size`, `idle_size`, `min_size`, `max_size`, `free_size`, `utilization`, `is_connected`.

### Context Manager

```python
async with Pool.from_yaml("config.yaml") as pool:
    result = await pool.fetch("SELECT * FROM events LIMIT 10")
```

---

## Brotr - Database Interface

**Location**: `src/core/brotr.py`

High-level interface for database operations using stored procedures.

### Configuration

```python
from core import Brotr, BrotrConfig

# From YAML (includes pool config)
brotr = Brotr.from_yaml("config.yaml")

# From dict
brotr = Brotr.from_dict({
    "pool": {...},  # Pool config dict
    "batch": {"max_batch_size": 10000},
    "timeouts": {
        "query": 60.0,
        "procedure": 90.0,
        "batch": 120.0
    }
})

# With existing Pool
brotr = Brotr(pool=existing_pool, config=BrotrConfig())
```

**Configuration Models**:
- `BatchConfig`: max_batch_size (1-100000)
- `TimeoutsConfig`: query, procedure, batch

### Public Attributes

```python
pool: Pool  # Direct access to connection pool
```

### Insert Operations

```python
async def insert_events(records: list[EventRelay]) -> tuple[int, int]
```
Insert events atomically. Returns `(inserted, skipped)` counts.

**Parameters**:
- `records`: List of `EventRelay` dataclass instances

**Example**:
```python
from models import EventRelay, Relay

relay = Relay("wss://relay.example.com")
event_relay = EventRelay.from_nostr_event(nostr_event, relay)
inserted, skipped = await brotr.insert_events([event_relay])
```

```python
async def insert_relays(records: list[Relay]) -> int
```
Insert relays atomically. Returns count of inserted relays.

```python
async def insert_relay_metadata(records: list[RelayMetadata]) -> int
```
Insert relay metadata atomically. Hash computed in Python via `hashlib.sha256()`. Returns count.

### Service Data Operations

```python
async def upsert_service_data(records: list[tuple[str, str, str, dict]]) -> int
```
Upsert service data records. Returns count.

**Tuple format**: `(service_name, data_type, key, value_dict)`
```python
records = [
    # Candidates for Validator (written by Seeder and Finder)
    ("validator", "candidate", "wss://relay.example.com", {}),
    # Cursor for Synchronizer
    ("synchronizer", "cursor", "events", {"last_id": "abc123"})
]
await brotr.upsert_service_data(records)
```

```python
async def get_service_data(
    service_name: str,
    data_type: str,
    key: Optional[str] = None
) -> list[dict[str, Any]]
```
Get service data records. Returns list of dicts with `key`, `value`, `updated_at`.

```python
async def delete_service_data(keys: list[tuple[str, str, str]]) -> int
```
Delete service data records. Returns count.

**Tuple format**: `(service_name, data_type, key)`

### Cleanup Operations

```python
async def delete_orphan_events() -> int
```
Delete events not referenced by any relay. Returns count.

```python
async def delete_orphan_metadata() -> int
```
Delete metadata not referenced by any relay_metadata. Returns count.

```python
async def cleanup_orphans(include_relays: bool = False) -> dict[str, int]
```
Delete all orphaned records. Returns `{"metadata": n, "events": n, "relays": n}`.

```python
async def refresh_metadata_latest() -> None
```
Refresh the `relay_metadata_latest` materialized view.

### Properties

```python
@property
def config() -> BrotrConfig
```
Get Brotr configuration.

### Context Manager

```python
async with brotr:
    await brotr.insert_relays([relay1, relay2])
```

---

## BaseService - Service Base Class

**Location**: `src/core/base_service.py`

Abstract base class for all services with lifecycle management.

### Class Attributes

```python
SERVICE_NAME: ClassVar[str] = "base_service"
CONFIG_CLASS: ClassVar[Optional[type[BaseModel]]] = None
MAX_CONSECUTIVE_FAILURES: ClassVar[int] = 5
```

### Subclass Requirements

1. Set `SERVICE_NAME` class attribute
2. Set `CONFIG_CLASS` for automatic config parsing
3. Implement `async def run() -> None` method

**Example**:
```python
from core import BaseService, BaseServiceConfig

class MyServiceConfig(BaseServiceConfig):
    interval: float = 60.0

class MyService(BaseService[MyServiceConfig]):
    SERVICE_NAME = "myservice"
    CONFIG_CLASS = MyServiceConfig

    async def run(self) -> None:
        # Service logic here
        pass
```

### Constructor

```python
def __init__(self, brotr: Brotr, config: ConfigT | None = None) -> None
```

**Parameters**:
- `brotr`: Database interface instance (required)
- `config`: Service configuration (optional). If `None`, creates default config via `CONFIG_CLASS()`.

**Protected Attributes**:
- `_brotr: Brotr` - Database interface
- `_config: ConfigT` - Service configuration
- `_logger: Logger` - Structured logger
- `_shutdown_event: asyncio.Event` - Shutdown signal

### Public Methods

```python
@abstractmethod
async def run() -> None
```
Execute main service logic. Must be implemented by subclass.

```python
def request_shutdown() -> None
```
Request graceful shutdown. Thread-safe for signal handlers.

```python
async def run_forever(
    interval: float,
    max_consecutive_failures: Optional[int] = None
) -> None
```
Run service continuously with interval between cycles.

**Parameters**:
- `interval`: Seconds to wait between `run()` cycles
- `max_consecutive_failures`: Stop after N consecutive errors (0 = unlimited)

```python
async def wait(timeout: float) -> bool
```
Wait for shutdown event or timeout. Returns `True` if shutdown requested.

**Usage in run() method**:
```python
async def run(self) -> None:
    while self.is_running:
        # Do work
        if await self.wait(60):
            break  # Shutdown requested
```

### Properties

```python
@property
def is_running() -> bool
```
Check if service is running (shutdown not requested).

```python
@property
def config() -> Optional[ConfigT]
```
Get service configuration (typed to CONFIG_CLASS).

### Factory Methods

```python
@classmethod
def from_yaml(cls, config_path: str, brotr: Brotr, **kwargs) -> "BaseService"
```
Create service from YAML file.

```python
@classmethod
def from_dict(cls, data: dict, brotr: Brotr, **kwargs) -> "BaseService"
```
Create service from dict.

### Context Manager

```python
async with service:
    await service.run()
```

---

## Logger - Structured Logging

**Location**: `src/core/logger.py`

Structured key-value logger with optional JSON output.

### Constructor

```python
from core.logger import Logger

logger = Logger("service_name")  # Key-value output
json_logger = Logger("service_name", json_output=True)  # JSON output
```

### Methods

All methods accept `**kwargs` for structured key-value pairs:

```python
def debug(msg: str, **kwargs: Any) -> None
def info(msg: str, **kwargs: Any) -> None
def warning(msg: str, **kwargs: Any) -> None
def error(msg: str, **kwargs: Any) -> None
def critical(msg: str, **kwargs: Any) -> None
def exception(msg: str, **kwargs: Any) -> None  # Includes traceback
```

### Output Formats

**Key-value** (default):
```python
logger.info("cycle_completed", events=100, duration=2.5)
# Output: cycle_completed events=100 duration=2.5

logger.info("error", path="/my path/file")
# Output: error path="/my path/file"
```

**JSON**:
```python
json_logger.info("cycle_completed", events=100, duration=2.5)
# Output: {"message": "cycle_completed", "events": 100, "duration": 2.5}
```

### Value Escaping

- Values with spaces, `=`, or quotes are automatically quoted
- Internal quotes are escaped with backslash
- Empty strings are quoted

---

## MetricsServer - Prometheus Metrics

**Location**: `src/core/metrics.py`

HTTP server exposing Prometheus metrics for service monitoring.

### Configuration

```python
from core import MetricsConfig, MetricsServer, start_metrics_server

# Configuration model
config = MetricsConfig(
    enabled=True,      # Enable metrics collection
    port=8000,         # HTTP port for /metrics endpoint
    host="0.0.0.0",    # Bind address
    path="/metrics"    # Endpoint path
)
```

### Metrics

**Service Information** (set once at startup):
```python
from core.metrics import SERVICE_INFO

SERVICE_INFO.info({
    "service": "validator",
    "version": "2.0.0"
})
```

**Service Gauges** (point-in-time values):
```python
from core.metrics import SERVICE_GAUGE

# Current state metrics
SERVICE_GAUGE.labels(service="validator", name="candidates").set(150)
SERVICE_GAUGE.labels(service="validator", name="consecutive_failures").set(0)
SERVICE_GAUGE.labels(service="monitor", name="relays_checked").set(500)
```

**Service Counters** (cumulative totals):
```python
from core.metrics import SERVICE_COUNTER

# Cumulative metrics
SERVICE_COUNTER.labels(service="validator", name="total_validated").inc()
SERVICE_COUNTER.labels(service="validator", name="total_promoted").inc(10)
SERVICE_COUNTER.labels(service="monitor", name="cycles_completed").inc()
```

**Cycle Duration Histogram**:
```python
from core.metrics import CYCLE_DURATION_SECONDS

# Tracks cycle duration for percentiles (p50/p95/p99)
with CYCLE_DURATION_SECONDS.labels(service="validator").time():
    await run_cycle()
```

### Starting the Server

```python
from core import start_metrics_server, MetricsConfig

# Start with default config
server = await start_metrics_server()

# Start with custom config
config = MetricsConfig(port=8001, host="127.0.0.1")
server = await start_metrics_server(config)

# Stop on shutdown
await server.stop()
```

### Integration with BaseService

BaseService automatically integrates metrics:
- Tracks `cycles_success` and `cycles_failed` counters
- Records `CYCLE_DURATION_SECONDS` for each cycle
- Updates `consecutive_failures` gauge
- Updates `last_cycle_timestamp` gauge

Services add their own metrics via `set_gauge()` and `inc_counter()` helpers.

---

## Usage Patterns

### Complete Service Example

```python
from core import Pool, Brotr, BaseService, BaseServiceConfig

class MyConfig(BaseServiceConfig):
    interval: float = 60.0

class MyService(BaseService[MyConfig]):
    SERVICE_NAME = "myservice"
    CONFIG_CLASS = MyConfig

    async def run(self) -> None:
        self._logger.info("run_started")

        # Database operations
        relays = await self._brotr.pool.fetch("SELECT * FROM relays LIMIT 10")

        self._logger.info("run_completed", relay_count=len(relays))

# Usage
brotr = Brotr.from_yaml("yaml/core/brotr.yaml")
service = MyService.from_yaml("yaml/services/myservice.yaml", brotr=brotr)

async with brotr:
    async with service:
        await service.run_forever(interval=60.0)
```

### Error Handling

```python
# Pool connection with retry
try:
    await pool.connect()
except ConnectionError as e:
    logger.error("connection_failed", error=str(e))

# Transaction with automatic rollback
async with brotr.pool.transaction() as conn:
    await conn.execute("INSERT INTO relays ...")
    # Auto-rollback on exception, auto-commit on success

# Service with max failures
await service.run_forever(
    interval=60.0,
    max_consecutive_failures=5  # Stop after 5 consecutive errors
)
```

### Signal Handling

```python
import signal

def handle_shutdown(signum, frame):
    service.request_shutdown()  # Thread-safe

signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

await service.run_forever(interval=60.0)
```
