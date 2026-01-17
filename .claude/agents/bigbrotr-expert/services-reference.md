# Services Reference

Complete documentation for all BigBrotr services with configuration, API, and usage examples.

## Service Architecture

All services inherit from `BaseService[ConfigT]` and follow these patterns:
- Receive `Brotr` via constructor (dependency injection)
- Configuration via Pydantic models loaded from YAML
- Implement `async def run() -> None` for main logic
- Use `run_forever(interval)` for continuous operation

---

## Seeder - Database Bootstrap

**Location**: `src/services/seeder.py`

One-shot service for seeding the database with initial relay data from a seed file.

### Configuration

```yaml
# yaml/services/seeder.yaml
seed:
  enabled: true
  file_path: "data/seed_relays.txt"
```

**Configuration Models**:
- `SeedConfig`: enabled (bool), file_path (str)
- `SeederConfig`: seed (SeedConfig)

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
from services import Seeder

brotr = Brotr.from_yaml("yaml/core/brotr.yaml")
seeder = Seeder.from_yaml("yaml/services/seeder.yaml", brotr=brotr)

async with brotr:
    await seeder.run()
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
Run single discovery cycle. Discovers relays and inserts as candidates into `service_data` table with `service_name='validator'` so the Validator service can pick them up.

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

Validates candidate relay URLs discovered by the Seeder and Finder services. Uses streaming architecture with batch processing for efficient validation at scale.

### Configuration

```yaml
# yaml/services/validator.yaml
interval: 28800.0  # 8 hours between validation cycles

metrics:
  enabled: true
  port: 8002

processing:
  chunk_size: 100  # Candidates per batch
  max_candidates: null  # Limit per cycle (null = unlimited)

cleanup:
  enabled: true
  max_failures: 100  # Remove candidates after N failed attempts

networks:
  clearnet:
    enabled: true
    max_tasks: 50
    timeout: 10.0
  tor:
    enabled: true
    proxy_url: "socks5://tor:9050"
    max_tasks: 10
    timeout: 30.0
  i2p:
    enabled: false
    proxy_url: "socks5://i2p:4447"
    max_tasks: 5
    timeout: 45.0
  loki:
    enabled: false
    proxy_url: "socks5://lokinet:1080"
    max_tasks: 5
    timeout: 30.0
```

**Configuration Models**:
- `NetworkConfig`: clearnet, tor, i2p, loki (each with enabled, proxy_url, max_tasks, timeout)
- `ProcessingConfig`: chunk_size, max_candidates
- `CleanupConfig`: enabled, max_failures
- `ValidatorConfig`: interval, metrics, networks, processing, cleanup

### Validation Process (Streaming Architecture)

1. **Cleanup Phase** (if enabled): Remove exhausted candidates with `failed_attempts >= max_failures`
2. **Fetch Chunk**: Load chunk of candidates from `service_data` table
   - Candidates written by Seeder and Finder with `service_name='validator'`
   - Chunk size controlled by `processing.chunk_size`
3. **Validate in Parallel**:
   - Per-network semaphores limit concurrency (`max_tasks`)
   - Network detection (clearnet, tor, i2p, loki) from URL
   - Use appropriate proxy and timeout per network
   - Test WebSocket connectivity via `is_nostr_relay()` helper
4. **Persist Results**:
   - **Success**: Insert into `relays` table, delete from candidates
   - **Failure**: Increment `failed_attempts` in candidate data
5. **Repeat**: Continue until all candidates processed or `max_candidates` reached

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

### Multi-Network Support

**Automatic Detection**:
- `.onion` URLs → Tor network
- `.i2p` URLs → I2P network
- `.loki` URLs → Lokinet network
- Others → Clearnet

**Per-Network Configuration**:
- `enabled`: Whether to process relays on this network
- `proxy_url`: SOCKS5 proxy URL for overlay networks
- `max_tasks`: Maximum concurrent validations
- `timeout`: Connection timeout in seconds

**Proxy Configuration**:
```python
network_config = self._config.networks.get(relay.network)
if network_config.enabled and network_config.proxy_url:
    # Use proxy for overlay networks
    ...
```

---

## Monitor - Relay Health Monitoring

**Location**: `src/services/monitor.py`

Monitors relay health and metadata with full NIP-66 compliance.

### Configuration

```yaml
# yaml/services/monitor.yaml
interval: 3600.0

metrics:
  enabled: true
  port: 8003

networks:
  clearnet:
    enabled: true
    max_tasks: 50
    timeout: 30.0
  tor:
    enabled: true
    proxy_url: "socks5://tor:9050"
    max_tasks: 10
    timeout: 60.0
  i2p:
    enabled: false
    proxy_url: "socks5://i2p:4447"
    max_tasks: 5
    timeout: 90.0
  loki:
    enabled: false
    proxy_url: "socks5://lokinet:1080"
    max_tasks: 5
    timeout: 60.0

keys: {}  # Keys loaded from PRIVATE_KEY env var

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
  city_database_path: "static/GeoLite2-City.mmdb"
  asn_database_path: "static/GeoLite2-ASN.mmdb"
  country_database_path: "static/GeoLite2-Country.mmdb"
  update_frequency: "monthly"

concurrency:
  max_processes: 1
  batch_size: 50

selection:
  min_age_since_check: 3600
```

**Configuration Models**:
- `NetworkConfig`: clearnet, tor, i2p, loki (each with enabled, proxy_url, max_tasks, timeout)
- `KeysConfig`: keys (loaded from PRIVATE_KEY env)
- `PublishingConfig`: enabled, destination, relays
- `ChecksConfig`: open, read, write, nip11, ssl, dns, geo
- `GeoConfig`: city_database_path, asn_database_path, country_database_path, update_frequency
- `ConcurrencyConfig`: max_processes, batch_size
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

metrics:
  enabled: true
  port: 8004

networks:
  clearnet:
    enabled: true
    max_tasks: 10
    timeout: 30.0
  tor:
    enabled: true
    proxy_url: "socks5://tor:9050"
    max_tasks: 5
    timeout: 60.0
  i2p:
    enabled: false
    proxy_url: "socks5://i2p:4447"
    max_tasks: 3
    timeout: 90.0
  loki:
    enabled: false
    proxy_url: "socks5://lokinet:1080"
    max_tasks: 3
    timeout: 60.0

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

sync_timeouts:
  relay_clearnet: 1800.0  # 30 min max per relay
  relay_tor: 3600.0       # 60 min for Tor
  relay_i2p: 3600.0
  relay_loki: 3600.0

concurrency:
  max_parallel: 10
  max_processes: 4
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
- `NetworkConfig`: clearnet, tor, i2p, loki (each with enabled, proxy_url, max_tasks, timeout)
- `FilterConfig`: ids, kinds, authors, tags, limit
- `TimeRangeConfig`: default_start, use_relay_state, lookback_seconds
- `SyncTimeoutsConfig`: relay_clearnet, relay_tor, relay_i2p, relay_loki
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
    "seeder": (Seeder, SeederConfig),
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
