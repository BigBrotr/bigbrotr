# Configuration

This document provides comprehensive documentation for BigBrotr's configuration system.

## Table of Contents

- [Overview](#overview)
- [Environment Variables](#environment-variables)
- [Configuration Files](#configuration-files)
- [Core Configuration](#core-configuration)
- [Service Configuration](#service-configuration)
- [Configuration Validation](#configuration-validation)
- [Best Practices](#best-practices)

---

## Overview

BigBrotr uses a YAML-driven configuration system with Pydantic validation. This approach provides:

- **Type Safety**: All configuration is validated at startup
- **Documentation**: Pydantic models serve as schema documentation
- **Flexibility**: YAML files are easy to read and modify
- **Security**: Sensitive data (passwords) comes from environment variables only

### Configuration Philosophy

1. **YAML for Structure** - All non-sensitive configuration in YAML files
2. **Environment for Secrets** - Only passwords and keys from environment
3. **Defaults are Safe** - Sensible defaults for all optional settings
4. **Validation at Startup** - Configuration errors fail fast

---

## Environment Variables

Only sensitive data is loaded from environment variables:

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `DB_PASSWORD` | **Yes** | PostgreSQL database password | `my_secure_password_123` |
| `PRIVATE_KEY` | **Yes** for Monitor, optional for Synchronizer | Nostr private key (hex or nsec) for write tests and NIP-42 auth | `5a2b3c4d...` (64 hex chars) or `nsec1...` |
| `GRAFANA_PASSWORD` | No | Grafana admin password | Defaults to `admin` |

### Setting Environment Variables

**Docker Compose** (recommended):
```bash
# Create .env file
cp deployments/bigbrotr/.env.example deployments/bigbrotr/.env
nano deployments/bigbrotr/.env  # Edit DB_PASSWORD
```

**Shell Export**:
```bash
export DB_PASSWORD=your_secure_password
export PRIVATE_KEY=your_hex_private_key  # Required for Monitor, optional for Synchronizer (NIP-42)
```

**Systemd Service**:
```ini
[Service]
Environment="DB_PASSWORD=your_secure_password"
Environment="PRIVATE_KEY=your_hex_private_key"
```

---

## Configuration Files

### File Structure

Each deployment has its own YAML configuration:

```
deployments/
├── bigbrotr/config/                    # Full-featured configuration
│   ├── brotr.yaml                     # Database and pool configuration
│   └── services/
│       ├── seeder.yaml               # Seed file configuration
│       ├── finder.yaml               # Relay discovery settings
│       ├── monitor.yaml              # Health monitoring (Tor enabled)
│       └── synchronizer.yaml         # Event sync (high concurrency)
│
└── lilbrotr/config/                    # Lightweight configuration (overrides only)
    ├── brotr.yaml                     # Same pool settings
    └── services/
        └── synchronizer.yaml         # Tor disabled, lower concurrency
```

**Note**: LilBrotr uses minimal configuration overrides. Services not explicitly configured inherit defaults from their Pydantic models.

### Loading Configuration

Services load configuration via factory methods:

```python
# From YAML file
service = MyService.from_yaml("config/services/myservice.yaml", brotr=brotr)

# From dictionary
config_dict = {"interval": 1800.0, "tor": {"enabled": False}}
service = MyService.from_dict(config_dict, brotr=brotr)
```

---

## Core Configuration

### Brotr Configuration (`deployments/*/config/brotr.yaml`)

```yaml
# Connection pool configuration
pool:
  # Database connection parameters - connects to PGBouncer
  database:
    host: pgbouncer              # PGBouncer service name (connects to PostgreSQL)
    port: 5432                   # PGBouncer internal port
    database: bigbrotr           # Database name
    user: admin                  # Database user
    # password: loaded from DB_PASSWORD environment variable

  # Connection pool size limits (connections to PGBouncer)
  limits:
    min_size: 5                  # Minimum connections to PGBouncer
    max_size: 20                 # Maximum connections to PGBouncer
    max_queries: 50000           # Queries per connection before recycling
    max_inactive_connection_lifetime: 300.0  # Idle timeout (seconds)

  # Pool-level timeouts
  timeouts:
    acquisition: 10.0            # Timeout for getting connection (seconds)
    health_check: 5.0            # Timeout for health check (seconds)

  # Connection retry logic
  retry:
    max_attempts: 3              # Maximum retry attempts
    initial_delay: 1.0           # Initial delay between retries (seconds)
    max_delay: 10.0              # Maximum delay between retries (seconds)
    exponential_backoff: true    # Use exponential backoff

  # PostgreSQL server settings
  server_settings:
    application_name: bigbrotr   # Application name in pg_stat_activity
    timezone: UTC                # Session timezone

# Batch operation settings
batch:
  max_size: 1000                 # Maximum items per batch operation

# Query timeouts (seconds, or null for infinite)
timeouts:
  query: 60.0                    # Standard query timeout
  batch: 120.0                   # Batch operation timeout
  cleanup: 90.0                  # Cleanup procedures (delete_orphan_*, delete_failed_*)
  refresh: null                  # Materialized view refresh (no timeout)
```

### Configuration Reference

#### Database Config

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host` | string | `localhost` | Database hostname |
| `port` | int | `5432` | Database port (1-65535) |
| `database` | string | `database` | Database name |
| `user` | string | `admin` | Database username |

#### Pool Limits

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `min_size` | int | `5` | 1-100 | Minimum pool connections |
| `max_size` | int | `20` | 1-100 | Maximum pool connections |
| `max_queries` | int | `50000` | 1-1M | Queries before connection recycle |
| `max_inactive_connection_lifetime` | float | `300.0` | 0-3600 | Idle connection timeout |

#### Retry Config

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_attempts` | int | `3` | Maximum connection retry attempts |
| `initial_delay` | float | `1.0` | Initial retry delay (seconds) |
| `max_delay` | float | `10.0` | Maximum retry delay (seconds) |
| `exponential_backoff` | bool | `true` | Use exponential backoff |

---

## Service Configuration

### Seeder (`config/services/seeder.yaml`)

```yaml
# Seed relay configuration
# Note: Network type (clearnet/tor) is auto-detected from URL
# Note: Duplicate URLs are filtered server-side (existing relays and candidates skipped)
# Note: File paths are relative to the working directory:
#       - Docker: /app (so static/seed_relays.txt = /app/static/seed_relays.txt)
#       - Local: run from deployments/bigbrotr/
seed:
  enabled: true                       # Enable relay seeding
  file_path: static/seed_relays.txt   # Path to seed file
```

**Note**: The Seeder is a one-shot service that seeds relay URLs as candidates. It does not perform schema verification - the SQL initialization scripts handle schema creation.

### Finder (`config/services/finder.yaml`)

```yaml
# Cycle interval (seconds between discovery runs)
interval: 3600.0                 # 1 hour (Range: >= 60.0)

# Event scanning (discovers relays from stored events)
events:
  enabled: true                  # Enable event-based discovery
  batch_size: 1000               # Events per batch (Range: 100-10000)
  kinds: [2, 3, 10002]           # Event kinds: 2=recommend relay, 3=contacts, 10002=relay list

# External API discovery
api:
  enabled: true                  # Enable API-based discovery
  verify_ssl: true               # Verify TLS certificates (disable only for testing)
  sources:
    - url: https://api.nostr.watch/v1/online
      enabled: true
      timeout: 30.0              # Request timeout (Range: 0.1-120.0)
    - url: https://api.nostr.watch/v1/offline
      enabled: true
      timeout: 30.0
  delay_between_requests: 1.0    # Delay between API calls (Range: 0.0-10.0)
```

#### Finder Configuration Reference

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `interval` | float | `3600.0` | >= 60.0 | Seconds between cycles |
| `events.enabled` | bool | `true` | - | Enable event scanning |
| `events.batch_size` | int | `1000` | 100-10000 | Events per batch |
| `events.kinds` | list | `[2, 3, 10002]` | - | Event kinds to scan |
| `api.enabled` | bool | `true` | - | Enable API discovery |
| `api.verify_ssl` | bool | `true` | - | Verify TLS certificates |
| `api.sources[].timeout` | float | `30.0` | 0.1-120.0 | Request timeout |
| `api.delay_between_requests` | float | `1.0` | 0.0-10.0 | Inter-request delay |
| `concurrency.max_parallel` | int | `5` | 1-20 | Concurrent API requests |

### Validator (`config/services/validator.yaml`)

```yaml
# Cycle interval (seconds between validation runs)
interval: 28800.0  # 8 hours

# Prometheus metrics endpoint
metrics:
  enabled: true
  port: 8002

# Processing configuration
processing:
  chunk_size: 100                # Candidates per batch
  max_candidates: null           # Max candidates per cycle (null = unlimited)

# Cleanup configuration
cleanup:
  enabled: true
  max_failures: 100              # Remove after N failures

# Network-specific settings
networks:
  clearnet:
    enabled: true
    max_tasks: 50                # Concurrent validations
    timeout: 10.0                # Connection timeout
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

#### Validator Configuration Reference

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `interval` | float | `28800.0` | >= 60.0 | Seconds between cycles |
| `processing.chunk_size` | int | `100` | 10-1000 | Candidates per batch |
| `processing.max_candidates` | int | `null` | >= 1 | Max candidates per cycle |
| `cleanup.enabled` | bool | `true` | - | Enable candidate cleanup |
| `cleanup.max_failures` | int | `100` | >= 1 | Remove after N failures |
| `networks.*.enabled` | bool | varies | - | Enable network |
| `networks.*.max_tasks` | int | varies | 1-100 | Concurrent validations |
| `networks.*.timeout` | float | varies | 1.0-120.0 | Connection timeout |
| `networks.*.proxy_url` | string | - | - | SOCKS5 proxy URL |

### Monitor (`config/services/monitor.yaml`)

```yaml
# Cycle interval
interval: 3600.0                 # 1 hour (Range: >= 60.0)

# Prometheus metrics endpoint
metrics:
  enabled: true
  port: 8003

# Network-specific settings
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

# Nostr keys for NIP-66 write tests (loaded from PRIVATE_KEY env)
# Required for: write tests, publishing events
keys:
  # Keys are loaded from environment variable, no config needed here

# Default relay list for publishing events
publishing:
  relays: []                     # Relay URLs for publishing

# Kind 30166 relay discovery events
discovery:
  enabled: true
  interval: 3600                 # Re-check interval (Range: >= 60)
  include:                       # Metadata to include in events
    nip11_info: true
    nip66_rtt: true
    nip66_ssl: true
    nip66_geo: true
    nip66_net: true
    nip66_dns: true
    nip66_http: true

# Kind 10166 monitor announcement
announcement:
  enabled: true
  interval: 86400                # Announcement interval (Range: >= 60)

# Geolocation database configuration
# MaxMind databases are auto-downloaded from GitHub mirror if missing
geo:
  city_database_path: "static/GeoLite2-City.mmdb"
  asn_database_path: "static/GeoLite2-ASN.mmdb"
  city_download_url: "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-City.mmdb"
  asn_download_url: "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-ASN.mmdb"
  max_age_days: 30               # Auto-update if older (null = never)

# Processing settings
processing:
  chunk_size: 100                # Relays per batch (Range: 10-1000)
  compute:                       # What metadata to compute
    nip11_info: true
    nip66_rtt: true
    nip66_ssl: true
    nip66_geo: true
    nip66_net: true
    nip66_dns: true
    nip66_http: true
  store:                         # What to store in database
    nip11_info: true
    nip66_rtt: true
    nip66_ssl: true
    nip66_geo: true
    nip66_net: true
    nip66_dns: true
    nip66_http: true
```

#### Monitor Configuration Reference

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `interval` | float | `3600.0` | >= 60.0 | Seconds between cycles |
| `networks.*.enabled` | bool | varies | - | Enable network |
| `networks.*.max_tasks` | int | varies | 1-500 | Concurrent checks |
| `networks.*.timeout` | float | varies | 5.0-180.0 | Check timeout |
| `networks.*.proxy_url` | string | - | - | SOCKS5 proxy URL |
| `discovery.enabled` | bool | `true` | - | Enable Kind 30166 events |
| `discovery.interval` | int | `3600` | >= 60 | Re-check interval |
| `announcement.enabled` | bool | `true` | - | Enable Kind 10166 events |
| `announcement.interval` | int | `86400` | >= 60 | Announcement interval |
| `geo.city_download_url` | string | GitHub URL | - | Auto-download URL for City DB |
| `geo.asn_download_url` | string | GitHub URL | - | Auto-download URL for ASN DB |
| `geo.max_age_days` | int | `30` | null or >= 1 | Auto-update threshold |
| `processing.chunk_size` | int | `100` | 10-1000 | Relays per batch |

### Synchronizer (`config/services/synchronizer.yaml`)

```yaml
# Cycle interval
interval: 900.0                  # 15 minutes (Range: >= 60.0)

# Prometheus metrics endpoint
metrics:
  enabled: true
  port: 8004

# Network-specific settings
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

# Nostr keys for NIP-42 authentication (loaded from PRIVATE_KEY env)
# Used for relays that require authentication
keys:
  # Keys are loaded from environment variable, no config needed here

# Event filter settings (null = accept all)
filter:
  ids: null                      # Event IDs to sync
  kinds: null                    # Event kinds to sync
  authors: null                  # Authors to sync
  tags: null                     # Tag filters (format: {e: [...], p: [...]})
  limit: 500                     # Events per request (Range: 1-5000)

# Time range for sync
time_range:
  default_start: 0               # Default start timestamp (0 = epoch)
  use_relay_state: true          # Use per-relay incremental state
  lookback_seconds: 86400        # Lookback window (Range: 3600-604800)

# Per-relay sync timeouts
sync_timeouts:
  relay_clearnet: 1800.0         # Max time per relay (Range: 60.0-14400.0)
  relay_tor: 3600.0
  relay_i2p: 3600.0
  relay_loki: 3600.0

# Concurrency settings
concurrency:
  max_parallel: 10               # Parallel connections per process (Range: 1-100)
  max_processes: 4               # Worker processes (Range: 1-32)
  stagger_delay: [0, 60]         # Random delay range to prevent thundering herd

# Relay source settings
source:
  from_database: true            # Fetch relays from database
  max_metadata_age: 43200        # Only sync recently checked relays (seconds)
  require_readable: true         # Only sync relays marked readable

# Per-relay overrides
overrides:
  - url: "wss://relay.damus.io"
    timeouts:
      request: 60.0
      relay: 7200.0              # 2 hours for high-traffic relay
```

#### Synchronizer Configuration Reference

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `interval` | float | `900.0` | >= 60.0 | Seconds between cycles |
| `networks.*.enabled` | bool | varies | - | Enable network |
| `networks.*.max_tasks` | int | varies | 1-100 | Connections per process |
| `networks.*.timeout` | float | varies | 5.0-120.0 | WebSocket timeout |
| `filter.limit` | int | `500` | 1-5000 | Events per request |
| `time_range.lookback_seconds` | int | `86400` | 3600-604800 | Lookback window |
| `sync_timeouts.relay_*` | float | varies | 60.0-14400.0 | Per-relay timeout |
| `concurrency.max_parallel` | int | `10` | 1-100 | Connections per process |
| `concurrency.max_processes` | int | `4` | 1-32 | Worker processes |
| `source.max_metadata_age` | int | `43200` | >= 0 | Max metadata age |

---

## Configuration Validation

### Pydantic Validation

All configuration uses Pydantic models with built-in validation:

```python
from pydantic import BaseModel, Field

class TimeoutsConfig(BaseModel):
    clearnet: float = Field(default=30.0, ge=5.0, le=120.0)
    tor: float = Field(default=60.0, ge=10.0, le=180.0)
```

### Validation Errors

Invalid configuration fails at startup with clear error messages:

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for TimeoutsConfig
clearnet
  Input should be greater than or equal to 5 [type=greater_than_equal, input_value=2.0, input_type=float]
```

### Cross-Field Validation

Some configurations have cross-field validation:

```python
class PoolLimitsConfig(BaseModel):
    min_size: int = Field(default=5, ge=1, le=100)
    max_size: int = Field(default=20, ge=1, le=100)

    @model_validator(mode='after')
    def validate_sizes(self) -> Self:
        if self.max_size < self.min_size:
            raise ValueError("max_size must be >= min_size")
        return self
```

---

## Best Practices

### 1. Start with Defaults

The default configuration is designed for typical deployments:

```yaml
# Minimal finder.yaml - uses all defaults
interval: 3600.0
```

### 2. Tune for Your Environment

Adjust based on your resources:

```yaml
# High-resource environment
concurrency:
  max_parallel: 100
  max_processes: 16

# Low-resource environment
concurrency:
  max_parallel: 5
  max_processes: 2
```

### 3. Use Per-Relay Overrides

For problematic or high-traffic relays:

```yaml
overrides:
  - url: "wss://relay.damus.io"
    timeouts:
      relay: 7200.0      # Extended timeout
  - url: "wss://slow-relay.example.com"
    timeouts:
      request: 120.0     # Longer request timeout
```

### 4. Disable Unused Features

Reduce resource usage:

```yaml
# Disable Tor if not needed
tor:
  enabled: false

# Disable event scanning in Finder
events:
  enabled: false
```

### 5. Secure Your Secrets

```bash
# .env file permissions
chmod 600 deployments/bigbrotr/.env

# Never commit secrets
echo ".env" >> .gitignore
```

### 6. Monitor Resource Usage

Adjust pool sizes based on actual usage:

```yaml
pool:
  limits:
    # Start conservative
    min_size: 2
    max_size: 10
    # Increase if you see connection wait times
```

### 7. Test Configuration Changes

Validate configuration before deployment:

```python
# Quick validation test
from bigbrotr.services.synchronizer import SynchronizerConfig
import yaml

with open("config/services/synchronizer.yaml") as f:
    config_dict = yaml.safe_load(f)

config = SynchronizerConfig(**config_dict)  # Raises on invalid config
print(f"Config valid: {config}")
```

---

## Troubleshooting

### Common Configuration Errors

**"DB_PASSWORD environment variable not set"**
```bash
export DB_PASSWORD=your_password
# Or add to .env file
```

**"Connection refused"**
- Check `pool.database.host` matches your database/PGBouncer hostname
- In Docker, use service name (`pgbouncer` for pooled connections, or `postgres` for direct)
- Outside Docker, use `localhost` or actual hostname

**"Pool exhausted"**
```yaml
pool:
  limits:
    max_size: 50  # Increase pool size
  timeouts:
    acquisition: 30.0  # Increase wait timeout
```

**"Timeout connecting to relay"**
```yaml
networks:
  clearnet:
    timeout: 60.0  # Increase timeout
  tor:
    timeout: 120.0  # Tor needs more time
```

---

## Configuration Examples

### Development Configuration

```yaml
# brotr.yaml - Development
pool:
  database:
    host: localhost
    port: 5432
  limits:
    min_size: 2
    max_size: 5
  retry:
    max_attempts: 1
```

### Production Configuration

```yaml
# brotr.yaml - Production
pool:
  database:
    host: postgres
    port: 5432
  limits:
    min_size: 10
    max_size: 50
  retry:
    max_attempts: 5
    exponential_backoff: true
```

### High-Volume Synchronizer

```yaml
# synchronizer.yaml - High volume
interval: 300.0  # 5 minutes

concurrency:
  max_parallel: 50
  max_processes: 16
  stagger_delay: [0, 30]

source:
  max_metadata_age: 7200  # Check more frequently
```

---

## Related Documentation

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture overview |
| [DATABASE.md](DATABASE.md) | Database schema documentation |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Development setup and guidelines |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Deployment instructions |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | Contribution guidelines |
| [CHANGELOG.md](../CHANGELOG.md) | Version history |
