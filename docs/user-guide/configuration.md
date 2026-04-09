# Configuration Reference

Complete reference for BigBrotr's YAML configuration system with Pydantic v2 validation.

---

## Overview

BigBrotr uses hierarchical YAML configuration with Pydantic model validation:

1. **YAML files** define all non-sensitive settings
2. **Environment variables** supply secrets (passwords, private keys)
3. **Pydantic models** validate and enforce constraints at startup
4. **Sensible defaults** allow minimal configuration for most deployments

### Configuration Loading

```mermaid
flowchart TD
    A["CLI invocation<br/><small>python -m bigbrotr &lt;service&gt;</small>"] --> B["Brotr.from_yaml<br/><small>config/brotr.yaml</small>"]
    B --> C["Service.from_yaml<br/><small>config/services/&lt;service&gt;.yaml</small>"]
    C --> D["Pydantic validation<br/><small>field constraints, cross-field checks</small>"]
    D --> E["Environment variable resolution<br/><small>DB_*_PASSWORD, NOSTR_PRIVATE_KEY_&lt;SERVICE&gt;</small>"]
    E --> F["Service starts<br/><small>validated configuration</small>"]

```

### File Structure

Each deployment has its own configuration directory:

```text
deployments/
+-- bigbrotr/config/
|   +-- brotr.yaml
|   +-- services/
|       +-- seeder.yaml
|       +-- finder.yaml
|       +-- validator.yaml
|       +-- monitor.yaml
|       +-- synchronizer.yaml
|       +-- refresher.yaml
|       +-- ranker.yaml
|       +-- assertor.yaml
|       +-- api.yaml
|       +-- dvm.yaml
+-- lilbrotr/config/
    +-- brotr.yaml
    +-- services/
        +-- seeder.yaml
        +-- finder.yaml
        +-- validator.yaml
        +-- monitor.yaml
        +-- synchronizer.yaml
        +-- refresher.yaml
        +-- ranker.yaml
        +-- assertor.yaml
        +-- api.yaml
        +-- dvm.yaml
```

!!! tip
    See the `bigbrotr` deployment for a working example of all configuration files.

---

## Environment Variables

| Variable | Required | Used By | Description |
|----------|----------|---------|-------------|
| `DB_ADMIN_PASSWORD` | Yes | PostgreSQL admin, PGBouncer | Admin user password for database initialization and PGBouncer auth |
| `DB_WRITER_PASSWORD` | Yes | Writer services | Writer role password (seeder, finder, validator, monitor, synchronizer) |
| `DB_READER_PASSWORD` | Yes | Read-only services | Reader role password (postgres-exporter, Api, Dvm) |
| `DB_REFRESHER_PASSWORD` | Yes | Refresher | Refresher role password (matview ownership for REFRESH CONCURRENTLY) |
| `DB_RANKER_PASSWORD` | Yes | Ranker | Ranker role password (read-only access to canonical facts) |
| `NOSTR_PRIVATE_KEY_MONITOR` | No | Monitor | Service-specific key used for Monitor publishing and NIP-66 write probes. Blank/unset generates one ephemeral key at config creation. |
| `NOSTR_PRIVATE_KEY_SYNCHRONIZER` | No | Synchronizer | Service-specific key used for NIP-42-authenticated relay reads. Blank/unset generates one ephemeral key at config creation. |
| `NOSTR_PRIVATE_KEY_DVM` | No | Dvm | Service-specific key used for NIP-89/NIP-90 signing. Blank/unset generates one ephemeral key at config creation. |
| `NOSTR_PRIVATE_KEY_ASSERTOR` | No | Assertor | Service-specific key used for NIP-85 assertion signing and optional provider profile publishing. Blank/unset generates one ephemeral key at config creation. |
| `GRAFANA_PASSWORD` | Docker only | Grafana | Grafana admin password |

### Setting Environment Variables

**Docker Compose** (`.env` file):

```bash
cp deployments/bigbrotr/.env.example deployments/bigbrotr/.env
# Edit and set DB_ADMIN_PASSWORD, DB_WRITER_PASSWORD, DB_REFRESHER_PASSWORD,
# DB_READER_PASSWORD, DB_RANKER_PASSWORD, GRAFANA_PASSWORD, and optionally the per-service
# Nostr keys NOSTR_PRIVATE_KEY_MONITOR, NOSTR_PRIVATE_KEY_SYNCHRONIZER,
# NOSTR_PRIVATE_KEY_DVM, NOSTR_PRIVATE_KEY_ASSERTOR
```

**Shell**:

```bash
export DB_WRITER_PASSWORD=your_writer_password
export NOSTR_PRIVATE_KEY_MONITOR=your_hex_private_key
export NOSTR_PRIVATE_KEY_SYNCHRONIZER=your_hex_private_key
export NOSTR_PRIVATE_KEY_DVM=your_hex_private_key
export NOSTR_PRIVATE_KEY_ASSERTOR=your_assertor_hex_private_key
```

**Systemd**:

```ini
[Service]
Environment="DB_WRITER_PASSWORD=your_writer_password"
Environment="NOSTR_PRIVATE_KEY_MONITOR=your_hex_private_key"
Environment="NOSTR_PRIVATE_KEY_SYNCHRONIZER=your_hex_private_key"
Environment="NOSTR_PRIVATE_KEY_DVM=your_hex_private_key"
Environment="NOSTR_PRIVATE_KEY_ASSERTOR=your_assertor_hex_private_key"
```

---

## CLI Arguments

```text
python -m bigbrotr <service> [options]

positional arguments:
  service                 seeder | finder | validator | monitor | synchronizer | refresher | ranker | assertor | api | dvm

options:
  --config PATH           Service config path (overrides default)
  --brotr-config PATH     Brotr config path (default: config/brotr.yaml)
  --log-level LEVEL       DEBUG | INFO | WARNING | ERROR (default: INFO)
  --once                  Run one cycle and exit
```

---

## Core Configuration (brotr.yaml)

The Brotr configuration controls the database connection pool and query behavior shared by all services. Per-service pool overrides (`user`, `password_env`, `min_size`, `max_size`) are set in each service's YAML file under a `pool:` section (see [Pool Overrides](#pool-overrides)).

!!! tip "API Reference"
    See [`bigbrotr.core.pool.PoolConfig`](../reference/core/pool.md) and [`bigbrotr.core.brotr.BrotrConfig`](../reference/core/brotr.md) for the config class APIs.

### Full Example

```yaml
pool:
  database:
    host: pgbouncer                          # Database/PGBouncer hostname
    port: 5432                               # Connection port
    database: bigbrotr                       # Database name
    user: admin                              # Database user (overridden per-service)
    password_env: DB_ADMIN_PASSWORD                # Env var for password (overridden per-service)

  limits:
    min_size: 2                              # Minimum pool connections (overridden per-service)
    max_size: 20                             # Maximum pool connections (overridden per-service)
    max_queries: 50000                       # Queries before connection recycle
    max_inactive_connection_lifetime: 300.0  # Idle connection timeout (seconds)

  timeouts:
    acquisition: 10.0                        # Connection acquisition timeout

  retry:
    max_attempts: 3                          # Connection retry attempts
    initial_delay: 1.0                       # Initial retry delay (seconds)
    max_delay: 10.0                          # Maximum retry delay (seconds)
    exponential_backoff: true                # Use exponential backoff

  server_settings:
    application_name: bigbrotr               # Auto-set to service name if omitted
    timezone: UTC                            # Session timezone
    statement_timeout: 300000                # Max query time (milliseconds)

batch:
  max_size: 1000                             # Records per bulk insert

timeouts:
  query: 60.0                                # Standard query timeout (seconds)
  batch: 120.0                               # Batch operation timeout
  cleanup: 90.0                              # Cleanup procedure timeout
  refresh: null                              # Materialized view refresh (null = no timeout)
```

!!! note
    In production, `brotr.yaml` typically only contains `pool.database.host` and `pool.database.database`. The `user`, `password_env`, `min_size`, and `max_size` are set per-service via pool overrides.

### Field Reference

#### DatabaseConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host` | string | `localhost` | Database/PGBouncer hostname |
| `port` | int | `5432` | Connection port (1-65535) |
| `database` | string | `bigbrotr` | Database name |
| `user` | string | `admin` | Database username (typically overridden per-service via pool overrides) |
| `password_env` | string | `DB_ADMIN_PASSWORD` | Environment variable containing password (typically overridden per-service) |

#### LimitsConfig

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `min_size` | int | `2` | 1-100 | Minimum pool connections (typically overridden per-service) |
| `max_size` | int | `20` | 1-200 | Maximum pool connections (must be >= min_size) |
| `max_queries` | int | `50000` | >= 100 | Queries before connection recycle |
| `max_inactive_connection_lifetime` | float | `300.0` | - | Idle connection timeout (seconds) |

#### TimeoutsConfig

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `acquisition` | float | `10.0` | >= 0.1 | Connection acquisition timeout |

#### RetryConfig

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `max_attempts` | int | `3` | 1-10 | Maximum retry attempts |
| `initial_delay` | float | `1.0` | >= 0.1 | Initial delay between retries |
| `max_delay` | float | `10.0` | >= initial_delay | Maximum retry delay |
| `exponential_backoff` | bool | `true` | - | Use exponential backoff |

#### ServerSettingsConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `application_name` | string | `bigbrotr` | Application name in pg_stat_activity (auto-set to service name at startup) |
| `timezone` | string | `UTC` | Session timezone |
| `statement_timeout` | int | `300000` | Max query time in milliseconds (0 = no limit) |

#### BatchConfig

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `max_size` | int | `1000` | 1-100000 | Records per bulk operation |

#### TimeoutsConfig

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `query` | float or null | `60.0` | >= 0.1 | Standard query timeout |
| `batch` | float or null | `120.0` | >= 0.1 | Batch insert timeout |
| `cleanup` | float or null | `90.0` | >= 0.1 | Cleanup procedure timeout |
| `refresh` | float or null | `null` | >= 0.1 | Materialized view refresh timeout |

---

## Pool Overrides

Each service declares its own database connection settings in its YAML config file under a `pool:` section. These overrides are merged into the shared `brotr.yaml` configuration at startup. This enables per-service role isolation and right-sized connection pools.

### Example

```yaml
# config/services/monitor.yaml
pool:
  user: writer
  password_env: DB_WRITER_PASSWORD
  min_size: 1
  max_size: 3

# ... rest of monitor config
```

### Override Fields

| Field | Type | Description |
|-------|------|-------------|
| `user` | string | Database role for this service (e.g., `writer`, `reader`, `refresher`) |
| `password_env` | string | Environment variable containing the role's password |
| `min_size` | int | Minimum pool connections for this service |
| `max_size` | int | Maximum pool connections for this service |
| `application_name` | string | Override for `pg_stat_activity` (auto-set to service name if omitted) |

### Merge Behavior

At startup, `__main__.py` extracts the `pool:` section from the service config and applies it to the shared brotr config:

- `user` / `password_env` → `pool.database.user` / `pool.database.password_env`
- `min_size` / `max_size` → `pool.limits.min_size` / `pool.limits.max_size`
- `application_name` → `pool.server_settings.application_name` (defaults to service name)

If no `pool:` section is present, the service uses the brotr.yaml defaults.

### Production Pool Sizing

| Service | Role | min | max | Notes |
|---------|------|-----|-----|-------|
| Seeder | writer | 1 | 2 | One-shot, minimal connections |
| Finder | writer | 1 | 3 | Periodic API + event scanning |
| Validator | writer | 1 | 3 | WebSocket testing + promotion |
| Monitor | writer | 1 | 3 | Health checks + metadata persistence |
| Synchronizer | writer | 2 | 5 | Highest throughput service |
| Refresher | refresher | 1 | 3 | Materialized view refresh (needs REFRESH CONCURRENTLY) |
| Api | reader | 1 | 3 | Read-only REST API queries |
| Dvm | reader | 1 | 3 | Read-only Nostr DVM queries |

---

## Base Service Configuration

All services inherit from `BaseServiceConfig` and share these fields:

!!! tip "API Reference"
    See [`bigbrotr.core.base_service.BaseServiceConfig`](../reference/core/base_service.md) for the config class API.

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `interval` | float | `300.0` | >= 60.0 | Seconds between service cycles |
| `max_consecutive_failures` | int | `5` | >= 0 | Stop after N consecutive failures (0 = never stop) |
| `metrics.enabled` | bool | `false` | - | Enable Prometheus /metrics endpoint |
| `metrics.port` | int | `8000` | 1-65535 | Metrics HTTP port |
| `metrics.host` | string | `127.0.0.1` | - | Metrics bind address |
| `metrics.path` | string | `/metrics` | - | Metrics URL path |

---

## Network Configuration

Services that connect to relays (Validator, Monitor, Synchronizer) share a unified network configuration:

!!! tip "API Reference"
    See [`bigbrotr.services.common.configs.NetworksConfig`](../reference/services/common/configs.md) for the config class API.

```yaml
networks:
  clearnet:
    enabled: true
    proxy_url: null
    max_tasks: 50
    timeout: 10.0
  tor:
    enabled: false
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

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `enabled` | bool | varies | - | Enable this network type |
| `proxy_url` | string or null | varies | - | SOCKS5 proxy URL for overlay networks |
| `max_tasks` | int | varies | 1-200 | Maximum concurrent connections |
| `timeout` | float | varies | 1.0-120.0 | Connection timeout (seconds) |

**Defaults by network:**

| Network | enabled | proxy_url | max_tasks | timeout |
|---------|---------|-----------|-----------|---------|
| clearnet | `true` | `null` | `50` | `10.0` |
| tor | `false` | `socks5://tor:9050` | `10` | `30.0` |
| i2p | `false` | `socks5://i2p:4447` | `5` | `45.0` |
| loki | `false` | `socks5://lokinet:1080` | `5` | `30.0` |

---

## Seeder Configuration

One-shot service that seeds relay URLs from a static file.

```yaml
seed:
  file_path: "static/seed_relays.txt"        # Path to seed file (one URL per line)
  to_validate: true                           # true = insert as candidates, false = insert as relays
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `seed.file_path` | string | `static/seed_relays.txt` | Path to seed relay URLs file |
| `seed.to_validate` | bool | `true` | Insert as candidates (true) or directly as relays (false) |

---

## Finder Configuration

Discovers relay URLs from external APIs and stored Nostr events.

```yaml
api:
  enabled: true
  cooldown: 86400.0                          # Seconds before re-querying any source
  sources:
    - url: "https://api.nostr.watch/v1/online"
      expression: "[*]"                      # JMESPath expression (required)
      enabled: true
      timeout: 30.0
      connect_timeout: 10.0
      allow_insecure: false
    - url: "https://api.nostr.watch/v1/offline"
      expression: "[*]"
      enabled: true
      timeout: 30.0
  request_delay: 1.0
  max_response_size: 5242880                 # 5 MB

events:
  enabled: true
  scan_size: 500                             # Rows per paginated DB query
  batch_size: 500                            # Discovered relays to buffer before flushing
  parallel_relays: 50                        # Concurrent relay event scans
  max_relay_time: 900.0                      # Max seconds per relay (15 min)
  max_duration: 7200.0                       # Max seconds for entire event phase (2 hours)
```

### API Reference

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `api.enabled` | bool | `true` | - | Enable API-based discovery |
| `api.cooldown` | float | `86400.0` | 1.0-604800.0 | Minimum seconds before re-querying any source |
| `api.sources[].url` | string | - | - | API endpoint URL (required) |
| `api.sources[].expression` | string | - | - | JMESPath expression for URL extraction (required) |
| `api.sources[].enabled` | bool | `true` | - | Enable this source |
| `api.sources[].timeout` | float | `30.0` | 0.1-120.0 | HTTP request timeout |
| `api.sources[].connect_timeout` | float | `10.0` | 0.1-60.0 | HTTP connect timeout (must not exceed timeout) |
| `api.sources[].allow_insecure` | bool | `false` | - | Skip TLS certificate verification |
| `api.request_delay` | float | `1.0` | 0.0-10.0 | Delay between API calls |
| `api.max_response_size` | int | `5242880` | 1024-52428800 | Maximum API response body size in bytes |

### Events Reference

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `events.enabled` | bool | `true` | - | Enable event-based relay discovery |
| `events.scan_size` | int | `500` | 10-10000 | Rows per paginated DB query |
| `events.batch_size` | int | `500` | 10-10000 | Discovered relays to buffer before flushing |
| `events.parallel_relays` | int | `50` | 1-200 | Maximum concurrent relay event scans |
| `events.max_relay_time` | float | `900.0` | 10.0-86400.0 | Maximum seconds to scan a single relay |
| `events.max_duration` | float | `7200.0` | 60.0-86400.0 | Maximum seconds for the entire event scanning phase |

---

## Validator Configuration

Tests WebSocket connectivity for candidate relays and promotes them to the relay table.

```yaml
metrics:
  enabled: true
  port: 8002

processing:
  chunk_size: 100                            # Candidates per fetch batch
  max_candidates: null                       # Max candidates per cycle (null = unlimited)
  interval: 3600.0                           # Minimum seconds before retrying a failed candidate
  allow_insecure: false                      # Fall back to insecure transport on SSL failure

cleanup:
  enabled: true                              # Enable exhausted candidate cleanup
  max_failures: 720                          # Remove candidate after N failures (~30 days if hourly)

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
```

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `processing.chunk_size` | int | `100` | 10-1000 | Candidates per fetch batch |
| `processing.max_candidates` | int or null | `null` | >= 1 | Max candidates per cycle |
| `processing.interval` | float | `3600.0` | 0.0-604800.0 | Minimum seconds before retrying a failed candidate |
| `processing.allow_insecure` | bool | `false` | - | Fall back to insecure transport on SSL failure |
| `cleanup.enabled` | bool | `true` | - | Enable exhausted candidate cleanup |
| `cleanup.max_failures` | int | `720` | >= 1 | Failure threshold for candidate removal |

---

## Monitor Configuration

Performs NIP-11 and NIP-66 health checks on validated relays and publishes monitoring events.

```yaml
interval: 3600.0

metrics:
  enabled: true
  port: 8003

keys: {}                                     # Loaded from NOSTR_PRIVATE_KEY_MONITOR or generated once

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

processing:
  chunk_size: 100                            # Relays per batch
  max_relays: null                           # Max relays per cycle (null = unlimited)
  nip11_info_max_size: 1048576               # Max NIP-11 response size (bytes)

  compute:                                   # What metadata to compute
    nip11_info: true
    nip66_rtt: true
    nip66_ssl: true
    nip66_geo: true
    nip66_net: true
    nip66_dns: true
    nip66_http: true

  store:                                     # What metadata to persist (must be subset of compute)
    nip11_info: true
    nip66_rtt: true
    nip66_ssl: true
    nip66_geo: true
    nip66_net: true
    nip66_dns: true
    nip66_http: true

  retry:                                     # Per-metadata-type retry settings
    nip11_info:
      max_attempts: 0                        # 0 = no retry
      initial_delay: 1.0
      max_delay: 10.0
      jitter: 0.5
    nip66_rtt:
      max_attempts: 0
      initial_delay: 1.0
      max_delay: 10.0
      jitter: 0.5
    # nip66_ssl, nip66_geo, nip66_net, nip66_dns, nip66_http: same structure

geo:
  city_database_path: "static/GeoLite2-City.mmdb"
  asn_database_path: "static/GeoLite2-ASN.mmdb"
  city_download_url: "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-City.mmdb"
  asn_download_url: "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-ASN.mmdb"
  max_age_days: 30                           # Re-download if older (null = never)
  geohash_precision: 9                       # Geohash precision (1-12)

publishing:
  relays: []                                 # Default relay list for publishing

discovery:
  enabled: true
  interval: 3600                             # Seconds between kind 30166 publishes
  include:                                   # Metadata to include in events
    nip11_info: true
    nip66_rtt: true
    nip66_ssl: true
    nip66_geo: true
    nip66_net: true
    nip66_dns: true
    nip66_http: true
  relays: []                                 # Override publishing.relays

announcement:
  enabled: true
  interval: 86400                            # Seconds between kind 10166 announcements

profile:
  enabled: false
  interval: 86400
  relays: []
  name: null
  about: null
  picture: null
  nip05: null
  website: null
  banner: null
  lud16: null
```

### Processing Reference

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `processing.chunk_size` | int | `100` | 10-1000 | Relays per batch |
| `processing.max_relays` | int or null | `null` | >= 1 | Max relays per cycle |
| `processing.nip11_info_max_size` | int | `1048576` | 1024-10485760 | Max NIP-11 response size (bytes) |
| `processing.compute.*` | bool | `true` | - | Enable computation per metadata type |
| `processing.store.*` | bool | `true` | - | Enable persistence per metadata type |

### Retry Reference

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `retry.*.max_attempts` | int | `0` | >= 0 | Max retry attempts (0 = no retry) |
| `retry.*.initial_delay` | float | `1.0` | - | Initial delay between retries |
| `retry.*.max_delay` | float | `10.0` | - | Maximum delay between retries |
| `retry.*.jitter` | float | `0.5` | - | Random jitter factor |

### Geo Reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `geo.city_database_path` | string | `static/GeoLite2-City.mmdb` | Path to MaxMind City database |
| `geo.asn_database_path` | string | `static/GeoLite2-ASN.mmdb` | Path to MaxMind ASN database |
| `geo.city_download_url` | string | GitHub mirror URL | Auto-download URL for City DB |
| `geo.asn_download_url` | string | GitHub mirror URL | Auto-download URL for ASN DB |
| `geo.max_age_days` | int or null | `30` | Re-download threshold in days (null = never) |
| `geo.geohash_precision` | int | `9` | 1-12 | Geohash precision for geolocation |

### Publishing Reference

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `publishing.relays` | list[string] | `[]` | - | Default relay list for all publishing |
| `discovery.enabled` | bool | `true` | - | Publish kind 30166 relay monitoring events |
| `discovery.interval` | int | `3600` | >= 60 | Seconds between discovery publishes |
| `discovery.include.*` | bool | `true` | - | Metadata types to include in events |
| `announcement.enabled` | bool | `true` | - | Publish kind 10166 monitor announcements |
| `announcement.interval` | int | `86400` | >= 60 | Seconds between announcements |
| `profile.enabled` | bool | `false` | - | Publish kind 0 monitor profile |
| `profile.name` | string or null | `null` | - | Display name |
| `profile.about` | string or null | `null` | - | Profile description |

---

## Synchronizer Configuration

Connects to validated relays and archives Nostr events with cursor-based resumption.

```yaml
metrics:
  enabled: true
  port: 8004

keys: {}                                     # Loaded from NOSTR_PRIVATE_KEY_SYNCHRONIZER or generated once

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

processing:
  filters: [{}]                              # NIP-01 filter dicts (OR semantics, {} = all)
  since: 0                                   # Default start timestamp (0 = epoch)
  until: null                                # Upper bound (null = now())
  limit: 500                                 # Max events per relay request (REQ limit)
  end_lag: 86400                             # Seconds subtracted from until
  batch_size: 1000                           # Events to buffer before DB flush
  allow_insecure: false                      # Fall back to insecure transport on SSL failure

timeouts:
  relay_clearnet: 1800.0                     # Max time per clearnet relay (30 min)
  relay_tor: 3600.0                          # Max time per Tor relay (1 hour)
  relay_i2p: 3600.0
  relay_loki: 3600.0
  max_duration: 14400.0                      # Max seconds for entire sync phase (4 hours)
```

### Processing Reference

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `processing.filters` | list[dict] | `[{}]` | - | NIP-01 filter dicts for event subscription (OR semantics) |
| `processing.since` | int | `0` | >= 0 | Default start timestamp for relays without a cursor |
| `processing.until` | int or null | `null` | >= 0 | Upper bound timestamp (null = now()) |
| `processing.limit` | int | `500` | 10-5000 | Max events per relay request (REQ limit) |
| `processing.end_lag` | int | `86400` | 0-604800 | Seconds subtracted from until to compute sync end time |
| `processing.batch_size` | int | `1000` | 100-10000 | Events to buffer before flushing to the database |
| `processing.allow_insecure` | bool | `false` | - | Fall back to insecure transport on SSL failure |

### Sync Timeouts Reference

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `timeouts.relay_clearnet` | float | `1800.0` | 60.0-14400.0 | Max time per clearnet relay |
| `timeouts.relay_tor` | float | `3600.0` | 60.0-14400.0 | Max time per Tor relay |
| `timeouts.relay_i2p` | float | `3600.0` | 60.0-14400.0 | Max time per I2P relay |
| `timeouts.relay_loki` | float | `3600.0` | 60.0-14400.0 | Max time per Lokinet relay |
| `timeouts.max_duration` | float | `14400.0` | 60.0-86400.0 | Maximum seconds for the entire sync phase |

---

## Assertor Configuration

Publishes NIP-85 trusted assertion events using algorithm-aware v2 checkpoints.

```yaml
interval: 3600.0

metrics:
  enabled: true
  port: 8008

algorithm_id: global-pagerank-v1
keys:
  keys_env: NOSTR_PRIVATE_KEY_ASSERTOR
allow_insecure: false

relays:
  - wss://relay.damus.io
  - wss://nos.lol
  - wss://relay.primal.net

kinds:
  - 30382
  - 30383

batch_size: 500
min_events: 1
top_topics: 5

provider_profile:
  enabled: false
  kind0_content:
    name: BigBrotr Trusted Assertions
    about: NIP-85 trusted assertion provider
    website: https://bigbrotr.com
    picture: null
    nip05: null
    banner: null
    lud16: null
    extra_fields: {}
```

The shipped BigBrotr and LilBrotr deployments set `keys.keys_env` to
`NOSTR_PRIVATE_KEY_ASSERTOR`. If the variable is blank or unset, the config
generates one ephemeral key once at startup. If you want the Assertor to share
another service's identity, point `keys.keys_env` at that service's variable or
set both variables to the same private key value.

### Assertion Reference

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `algorithm_id` | string | `global-pagerank-v1` | lowercase slug | Stable algorithm/service-key namespace used in v2 checkpoint keys |
| `keys.keys_env` | string | `NOSTR_PRIVATE_KEY_ASSERTOR` | non-empty | Environment variable from which the signing key is loaded |
| `relays` | list[string] | 3 public relays | min 1 | Relay URLs used for NIP-85 publishing |
| `kinds` | list[int] | `[30382, 30383]` | subset of supported kinds | Assertion kinds to publish |
| `batch_size` | int | `500` | 1-50000 | Maximum eligible subjects fetched per cycle |
| `min_events` | int | `1` | >= 0 | Minimum total events required for user assertions |
| `top_topics` | int | `5` | 0-50 | Maximum number of topic tags per user assertion |
| `allow_insecure` | bool | `false` | - | Fall back to insecure SSL transport on relay certificate failure |
| `provider_profile.enabled` | bool | `false` | - | Publish a Kind 0 provider profile for the assertor identity |
| `provider_profile.kind0_content.*` | object | defaults | - | Metadata fields for the provider profile content |

---

## Configuration Validation

### Pydantic Constraints

All configuration uses Pydantic v2 models with `Field()` constraints:

```python
class LimitsConfig(BaseModel):
    min_size: int = Field(default=2, ge=1, le=100)
    max_size: int = Field(default=20, ge=1, le=200)
```

Invalid configuration fails at startup with clear error messages:

```text
pydantic_core._pydantic_core.ValidationError: 1 validation error for LimitsConfig
max_size
  Input should be greater than or equal to 1 [type=greater_than_equal]
```

### Cross-Field Validation

Some models enforce relationships between fields:

- `LimitsConfig`: `max_size` must be >= `min_size`
- `RetryConfig`: `max_delay` must be >= `initial_delay`
- `ProcessingConfig`: `store` flags must be a subset of `compute` flags
- `KeysConfig`: validates hex string length (64 chars) or nsec1 bech32 format

!!! warning
    Cross-field validation errors surface at startup. The Monitor's `store` flags must be a subset of `compute` -- you cannot store metadata that is not computed.

---

## Configuration Examples

### Minimal Development

```yaml
# brotr.yaml -- shared connection settings
pool:
  database:
    host: localhost
    port: 5432
```

```yaml
# services/finder.yaml -- per-service pool overrides
pool:
  user: writer
  password_env: DB_WRITER_PASSWORD
  min_size: 1
  max_size: 3

interval: 3600.0
```

### Production with PGBouncer

```yaml
# brotr.yaml -- host and database only, pool sizing per-service
pool:
  database:
    host: pgbouncer
    database: bigbrotr
  retry:
    max_attempts: 5
    exponential_backoff: true
```

### High-Volume Synchronizer

```yaml
# synchronizer.yaml
interval: 300.0
processing:
  batch_size: 5000
  limit: 1000
```

### Monitoring-Only (No Event Archiving)

```yaml
# monitor.yaml - run without Synchronizer
interval: 1800.0
processing:
  compute:
    nip11_info: true
    nip66_rtt: true
    nip66_ssl: true
    nip66_geo: true
    nip66_net: false        # skip network info
    nip66_dns: false        # skip DNS resolution
    nip66_http: false       # skip HTTP header check
```

---

## Troubleshooting

**"DB_WRITER_PASSWORD environment variable not set"** -- Set the environment variable or add it to your `.env` file. Writer services use `DB_WRITER_PASSWORD`, the refresher uses `DB_REFRESHER_PASSWORD`, read-only services use `DB_READER_PASSWORD`.

**"Connection refused"** -- Check `pool.database.host`. In Docker, use the service name (`pgbouncer` or `postgres`). Outside Docker, use `localhost`.

**"Pool exhausted"** -- Increase `pool.limits.max_size` or increase `pool.timeouts.acquisition`.

**"Timeout connecting to relay"** -- Increase `networks.<network>.timeout`. Tor relays typically need 30-60s.

**"Validation error for MonitorConfig"** -- The `store` flags must be a subset of `compute`. You cannot store metadata that is not computed.

---

## Related Documentation

- [Architecture](architecture.md) -- System architecture and module reference
- [Services](services.md) -- Deep dive into the nine independent services
- [Database](database.md) -- Database schema and stored procedures
- [Monitoring](monitoring.md) -- Prometheus metrics, alerting, and Grafana dashboards
