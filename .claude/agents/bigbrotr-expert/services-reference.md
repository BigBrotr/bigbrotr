# Services Reference

Complete documentation for all BigBrotr services with configuration, API, and usage examples.

## Service Architecture

All services inherit from `BaseService[ConfigT]` and follow these patterns:
- Receive `Brotr` via constructor (dependency injection)
- Configuration via Pydantic models loaded from YAML
- Implement `async def run() -> None` for main logic
- Use `run_forever(interval)` for continuous operation

---

## Initializer - Database Bootstrap

**Location**: `src/services/initializer.py`

One-shot service for seeding the database with initial relay data from a seed file.

### Configuration

```yaml
# yaml/services/initializer.yaml
seed:
  enabled: true
  file_path: "data/seed_relays.txt"
```

**Configuration Models**:
- `SeedConfig`: enabled (bool), file_path (str)
- `InitializerConfig`: seed (SeedConfig)

### Public Methods

```python
async def run() -> None
```
Run seeding sequence:
1. Load relay URLs from seed file
2. Parse and validate URLs (creates Relay objects)
3. Insert valid relays as candidates for validation

Logs warnings for invalid URLs and continues processing.

### Usage

```python
from core import Brotr
from services import Initializer

brotr = Brotr.from_yaml("yaml/core/brotr.yaml")
initializer = Initializer.from_yaml("yaml/services/initializer.yaml", brotr=brotr)

async with brotr:
    await initializer.run()
```

### Seed File Format

```text
# Relay URLs (one per line, # for comments)
wss://relay.damus.io
wss://relay.nostr.band
wss://nos.lol

# Comments and blank lines are ignored
```

---

## Finder - Relay Discovery

**Location**: `src/services/finder.py`

Discovers Nostr relay URLs from APIs and database events.

### Configuration

```yaml
# yaml/services/finder.yaml
interval: 3600.0  # Seconds between cycles

concurrency:
  max_parallel: 5

events:
  enabled: true
  batch_size: 1000
  kinds: [2, 3, 10002]  # Kinds to scan for relay URLs

api:
  enabled: true
  sources:
    - url: "https://api.nostr.watch/v1/online"
      enabled: true
      timeout: 30.0
    - url: "https://api.nostr.watch/v1/offline"
      enabled: true
      timeout: 30.0
  delay_between_requests: 1.0
```

**Configuration Models**:
- `ConcurrencyConfig`: max_parallel (1-20)
- `EventsConfig`: enabled, batch_size, kinds
- `ApiSourceConfig`: url, enabled, timeout
- `ApiConfig`: enabled, sources, delay_between_requests

### Discovery Sources

**Event Scanning**:
- Kind 2: Relay URL in content (deprecated)
- Kind 3: Relay URLs in JSON content (contact list)
- Kind 10002: Relay URLs in r-tags (NIP-65)
- Any event: r-tags

**API Fetching**:
- nostr.watch online/offline APIs
- Custom API sources

### Public Methods

```python
async def run() -> None
```
Run single discovery cycle. Discovers relays and inserts as candidates into `service_data` table.

### Internal Methods

```python
async def _find_from_events() -> None
```
Scan database events for relay URLs using cursor-based pagination.

**Cursor State**: Stored in `service_data` table as:
```python
("finder", "cursor", "events", {"last_timestamp": int, "last_id": hex_string})
```

```python
async def _find_from_api() -> None
```
Fetch relay URLs from external APIs.

### Usage

```python
from core import Brotr
from services import Finder

brotr = Brotr.from_yaml("yaml/core/brotr.yaml")
finder = Finder.from_yaml("yaml/services/finder.yaml", brotr=brotr)

async with brotr:
    async with finder:
        await finder.run_forever(interval=3600)
```

---

## Validator - Relay Validation

**Location**: `src/services/validator.py`

Validates candidate relay URLs discovered by the Finder service. Tests WebSocket connectivity and adds working relays to the database.

### Configuration

```yaml
# yaml/services/validator.yaml
interval: 300.0  # Seconds between validation cycles

connection_timeout: 10.0  # WebSocket connection timeout (1.0-60.0)
max_candidates_per_run: null  # Limit per cycle (null = unlimited)

concurrency:
  max_parallel: 10  # Concurrent validations (1-100)

tor:
  enabled: true
  host: "127.0.0.1"
  port: 9050

# Keys loaded from PRIVATE_KEY environment variable (optional for NIP-42)
```

**Configuration Models**:
- `TorConfig`: enabled, host, port, proxy_url (property)
- `KeysConfig`: keys (auto-loaded from `PRIVATE_KEY` env)
- `ConcurrencyConfig`: max_parallel (1-100)
- `ValidatorConfig`: interval, connection_timeout, max_candidates_per_run, concurrency, tor, keys

### Validation Process

1. **Fetch Candidates**: Load from `service_data` table where `(service_name='validator', data_type='candidate')`
2. **Probabilistic Selection** (if max_candidates_per_run set):
   - Probability = `1 / (1 + retry_count)`
   - Candidates with fewer retries more likely to be selected
3. **Test Connectivity**:
   - Build WebSocket client with nostr-sdk
   - Configure Tor proxy for .onion relays
   - Apply connection timeout
   - Attempt connection with `client.add_relay()` and `client.connect()`
4. **Handle Results**:
   - **Success**: Insert into `relays` table, delete from candidates
   - **Failure**: Increment `retry_count` in candidate value

### Public Methods

```python
async def run() -> None
```
Run single validation cycle. Processes candidates and updates database.

### Internal Methods

```python
async def _validate_relay(url: str) -> bool
```
Test single relay WebSocket connectivity.

**Network Handling**:
- Clearnet relays: Direct WebSocket connection
- `.onion` relays: Route through Tor SOCKS5 proxy
- Connection timeout enforced
- NIP-42 authentication attempted if keys configured

### Usage

```python
from core import Brotr
from services import Validator

brotr = Brotr.from_yaml("yaml/core/brotr.yaml")
validator = Validator.from_yaml("yaml/services/validator.yaml", brotr=brotr)

async with brotr:
    async with validator:
        await validator.run_forever(interval=300)
```

**Environment Variables**:
- `DB_PASSWORD`: Database password (required)
- `PRIVATE_KEY`: Nostr private key (optional, for NIP-42 authenticated relays)

**State Storage**:
Candidates stored in `service_data` table:
```python
("validator", "candidate", relay_url, {"failed_attempts": int})
```

### Tor Network Support

**Automatic Detection**:
- `.onion` URLs detected as Tor network
- SOCKS5 proxy automatically configured
- Separate timeout handling

**Proxy Configuration**:
```python
if relay.network == "tor" and self.config.tor.enabled:
    opts = ClientOptions().proxy(self.config.tor.proxy_url)
    builder = builder.opts(opts)
```

---

## Monitor - Relay Health Monitoring

**Location**: `src/services/monitor.py`

Monitors relay health and metadata with full NIP-66 compliance.

### Configuration

```yaml
# yaml/services/monitor.yaml
interval: 3600.0

tor:
  enabled: true
  host: "127.0.0.1"
  port: 9050

keys:
  # Keys loaded from PRIVATE_KEY env var

publishing:
  enabled: true
  destination: "monitored_relay"  # or "configured_relays", "database_only"
  relays: []

checks:
  open: true
  read: true
  write: true
  nip11: true
  ssl: true
  dns: true
  geo: true

geo:
  database_path: "/usr/share/GeoIP/GeoLite2-City.mmdb"
  asn_database_path: null

timeouts:
  clearnet:
    request: 30.0
    relay: 1800.0
  tor:
    request: 60.0
    relay: 3600.0

concurrency:
  max_parallel: 50
  batch_size: 50

selection:
  min_age_since_check: 3600
```

**Configuration Models**:
- `TorConfig`: enabled, host, port, proxy_url
- `KeysConfig`: keys (loaded from PRIVATE_KEY env)
- `PublishingConfig`: enabled, destination, relays
- `ChecksConfig`: open, read, write, nip11, ssl, dns, geo
- `GeoConfig`: database_path, asn_database_path
- `TimeoutsConfig`: clearnet, tor (each with request, relay)
- `ConcurrencyConfig`: max_parallel, batch_size
- `SelectionConfig`: min_age_since_check

### NIP-66 Checks

**NIP-11**: Fetch relay info document via HTTP
**NIP-66 Tests**:
- Open: WebSocket connection test
- Read: REQ/EOSE subscription test
- Write: EVENT/OK publication test
- DNS: Measure resolution time
- SSL: Validate certificate
- Geo: Geolocate relay IP

### Publishing

**Kind 30166**: Relay discovery events (published to monitored relay or configured relays)
**Kind 10166**: Monitor announcements (published hourly)

### Public Methods

```python
async def run() -> None
```
Run single monitoring cycle:
1. Publish Kind 10166 announcement (if enabled)
2. Fetch relays to check
3. Process relays in parallel
4. Insert metadata batches

### Internal Methods

```python
async def _fetch_relays_to_check() -> list[Relay]
```
Fetch relays from `relay_metadata_latest` view that need checking.

```python
async def _process_relay(relay: Relay, semaphore: Semaphore) -> list[RelayMetadata]
```
Check single relay and return metadata records.

```python
async def _publish_relay_discovery(relay: Relay, nip11: Nip11, nip66: Nip66) -> None
```
Publish Kind 30166 relay discovery event.

```python
async def _publish_announcement() -> None
```
Publish Kind 10166 monitor announcement.

### Usage

```python
from core import Brotr
from services import Monitor

brotr = Brotr.from_yaml("yaml/core/brotr.yaml")
monitor = Monitor.from_yaml("yaml/services/monitor.yaml", brotr=brotr)

async with brotr:
    async with monitor:
        await monitor.run_forever(interval=3600)
```

**Environment Variables**:
- `DB_PASSWORD`: Database password
- `PRIVATE_KEY`: Nostr private key (hex or nsec)

---

## Synchronizer - Event Synchronization

**Location**: `src/services/synchronizer.py`

Synchronizes Nostr events from relays with multiprocessing support.

### Configuration

```yaml
# yaml/services/synchronizer.yaml
interval: 900.0

tor:
  enabled: true
  host: "127.0.0.1"
  port: 9050

keys:
  # Keys loaded from PRIVATE_KEY env var (for NIP-42 auth)

filter:
  ids: null  # List of event IDs (None = all)
  kinds: null  # List of event kinds (None = all)
  authors: null  # List of pubkeys (None = all)
  tags: null  # {"tag_letter": ["value1", ...]}
  limit: 500  # Events per request

time_range:
  default_start: 0  # Unix timestamp
  use_relay_state: true
  lookback_seconds: 86400  # 24 hours

timeouts:
  clearnet:
    request: 30.0
    relay: 1800.0
  tor:
    request: 60.0
    relay: 3600.0

concurrency:
  max_parallel: 10
  max_processes: 1
  stagger_delay: [0, 60]

source:
  from_database: true
  max_metadata_age: 43200  # 12 hours
  require_readable: true

overrides:
  - url: "wss://special.relay.com"
    timeouts:
      request: 120.0
      relay: 7200.0
```

**Configuration Models**:
- `TorConfig`: enabled, host, port, proxy_url
- `KeysConfig`: keys (loaded from PRIVATE_KEY env)
- `FilterConfig`: ids, kinds, authors, tags, limit
- `TimeRangeConfig`: default_start, use_relay_state, lookback_seconds
- `NetworkTimeoutsConfig`: request, relay
- `TimeoutsConfig`: clearnet, tor
- `ConcurrencyConfig`: max_parallel, max_processes, stagger_delay
- `SourceConfig`: from_database, max_metadata_age, require_readable
- `RelayOverride`: url, timeouts

### Event Filtering

**Standard Filters**:
- `ids`: Event IDs (hex strings)
- `kinds`: Event kinds (integers)
- `authors`: Author pubkeys (hex strings)
- `limit`: Max events per request

**Tag Filters**:
```yaml
filter:
  tags:
    e: ["event_id_hex"]  # Events referencing specific event
    p: ["pubkey_hex"]    # Events mentioning specific pubkey
    t: ["hashtag"]       # Events with specific hashtag
    d: ["identifier"]    # Replaceable events with specific d-tag
```

### Time Range Strategy

**Per-Relay State**: Queries database for latest event timestamp per relay
**Lookback Window**: Only syncs events within last N seconds (prevents old event spam)

### Multiprocessing

**Single Process** (`max_processes: 1`):
- Parallel relay connections via asyncio.Semaphore
- Shared database connection

**Multiple Processes** (`max_processes > 1`):
- Worker pool via aiomultiprocess
- Per-process database connections
- Queue-based task distribution

### Public Methods

```python
async def run() -> None
```
Run synchronization cycle:
1. Fetch relays to sync
2. Add override relays
3. Run single-process or multiprocess sync
4. Log statistics

### Internal Methods

```python
async def _run_single_process(relays: list[Relay]) -> None
```
Sync relays using shared connection.

```python
async def _run_multiprocess(relays: list[Relay]) -> None
```
Sync relays using worker pool.

```python
async def _fetch_relays() -> list[Relay]
```
Fetch relays from `relay_metadata_latest` view.

```python
async def _get_start_time(relay: Relay) -> int
```
Get start timestamp for relay sync (latest event + 1).

### Worker Functions

```python
async def sync_relay_task(
    relay_url: str,
    relay_network: str,
    start_time: int,
    config_dict: dict,
    brotr_config: dict
) -> tuple[str, int, int, int, int]
```
Standalone task for multiprocessing. Returns `(url, events, invalid, skipped, new_end_time)`.

### Usage

```python
from core import Brotr
from services import Synchronizer

brotr = Brotr.from_yaml("yaml/core/brotr.yaml")
sync = Synchronizer.from_yaml("yaml/services/synchronizer.yaml", brotr=brotr)

async with brotr:
    async with sync:
        await sync.run_forever(interval=900)
```

**Environment Variables**:
- `DB_PASSWORD`: Database password
- `PRIVATE_KEY`: Nostr private key (optional, for NIP-42 auth)

---

## Service Registry

**Location**: `src/services/__main__.py`

All services are registered in `SERVICE_REGISTRY`:

```python
SERVICE_REGISTRY = {
    "initializer": (Initializer, InitializerConfig),
    "finder": (Finder, FinderConfig),
    "validator": (Validator, ValidatorConfig),
    "monitor": (Monitor, MonitorConfig),
    "synchronizer": (Synchronizer, SynchronizerConfig),
}
```

### Command-Line Usage

```bash
# Run service
python -m services finder --log-level DEBUG

# Service arguments
python -m services synchronizer --help
```

---

## Common Patterns

### Service Development Template

```python
from core import BaseService
from core import Brotr
from pydantic import BaseModel, Field

class MyServiceConfig(BaseModel):
    interval: float = Field(default=60.0, ge=10.0)
    batch_size: int = Field(default=100, ge=1, le=1000)

class MyService(BaseService[MyServiceConfig]):
    SERVICE_NAME = "myservice"
    CONFIG_CLASS = MyServiceConfig

    def __init__(self, brotr: Brotr, config: MyServiceConfig | None = None):
        super().__init__(brotr=brotr, config=config or MyServiceConfig())
        self._config: MyServiceConfig

    async def run(self) -> None:
        self._logger.info("run_started")

        # Database operations
        rows = await self._brotr.pool.fetch("SELECT * FROM relays LIMIT $1", self._config.batch_size)

        # Process data
        for row in rows:
            self._logger.debug("processing", url=row["url"])

        self._logger.info("run_completed", count=len(rows))
```

### Signal Handling

```python
import signal

service = MyService.from_yaml("config.yaml", brotr=brotr)

def handle_shutdown(signum, frame):
    service.request_shutdown()

signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

async with brotr:
    async with service:
        await service.run_forever(interval=60.0)
```

### Error Handling

```python
async def run(self) -> None:
    try:
        # Critical operation
        await self._do_important_work()
    except Exception as e:
        self._logger.error("critical_error", error=str(e))
        raise  # Let run_forever handle consecutive failures
```

### State Persistence

```python
# Save state
await self._brotr.upsert_service_data([
    ("myservice", "cursor", "events", {"last_id": "abc123"})
])

# Load state
results = await self._brotr.get_service_data("myservice", "cursor", "events")
if results:
    cursor = results[0]["value"]
```
