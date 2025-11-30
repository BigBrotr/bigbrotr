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
| `MONITOR_PRIVATE_KEY` | No | Nostr private key for NIP-66 write tests (hex) | `5a2b3c4d...` (64 hex chars) |

### Setting Environment Variables

**Docker Compose** (recommended):
```bash
# Create .env file
cp implementations/bigbrotr/.env.example implementations/bigbrotr/.env
nano implementations/bigbrotr/.env  # Edit DB_PASSWORD
```

**Shell Export**:
```bash
export DB_PASSWORD=your_secure_password
export MONITOR_PRIVATE_KEY=your_hex_private_key  # Optional
```

**Systemd Service**:
```ini
[Service]
Environment="DB_PASSWORD=your_secure_password"
Environment="MONITOR_PRIVATE_KEY=your_hex_private_key"
```

---

## Configuration Files

### File Structure

Each implementation has its own YAML configuration:

```
implementations/
├── bigbrotr/yaml/                    # Full-featured configuration
│   ├── core/
│   │   └── brotr.yaml                # Database and pool configuration
│   └── services/
│       ├── initializer.yaml          # Schema verification, seed file
│       ├── finder.yaml               # Relay discovery settings
│       ├── monitor.yaml              # Health monitoring (Tor enabled)
│       └── synchronizer.yaml         # Event sync (high concurrency)
│
└── lilbrotr/yaml/                    # Lightweight configuration (overrides only)
    ├── core/
    │   └── brotr.yaml                # Same pool settings
    └── services/
        └── synchronizer.yaml         # Tor disabled, lower concurrency
```

**Note**: LilBrotr uses minimal configuration overrides. Services not explicitly configured inherit defaults from their Pydantic models.

### Loading Configuration

Services load configuration via factory methods:

```python
# From YAML file
service = MyService.from_yaml("yaml/services/myservice.yaml", brotr=brotr)

# From dictionary
config_dict = {"interval": 1800.0, "tor": {"enabled": False}}
service = MyService.from_dict(config_dict, brotr=brotr)
```

---

## Core Configuration

### Brotr Configuration (`yaml/core/brotr.yaml`)

```yaml
# Connection pool configuration
pool:
  # Database connection parameters
  database:
    host: pgbouncer              # Database host (Docker service name)
    port: 5432                   # Database port
    database: bigbrotr           # Database name
    user: admin                  # Database user
    # password: loaded from DB_PASSWORD environment variable

  # Connection pool size limits
  limits:
    min_size: 5                  # Minimum connections in pool
    max_size: 20                 # Maximum connections in pool
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
  max_batch_size: 1000           # Maximum items per batch operation

# Query timeouts
timeouts:
  query: 60.0                    # Standard query timeout (seconds)
  procedure: 90.0                # Stored procedure timeout (seconds)
  batch: 120.0                   # Batch operation timeout (seconds)
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

### Initializer (`yaml/services/initializer.yaml`)

```yaml
# Schema verification settings
verify:
  extensions: true      # Verify PostgreSQL extensions
  tables: true          # Verify tables exist
  procedures: true      # Verify stored procedures exist
  views: true           # Verify views exist

# Expected schema elements
schema:
  extensions:
    - pgcrypto          # For hash functions
    - btree_gin         # For GIN indexes
  tables:
    - relays
    - events
    - events_relays
    - nip11
    - nip66
    - relay_metadata
    - service_state
  procedures:
    - insert_event
    - insert_relay
    - insert_relay_metadata
    - delete_orphan_events
    - delete_orphan_nip11
    - delete_orphan_nip66
  views:
    - relay_metadata_latest

# Seed relay configuration
seed:
  enabled: true                     # Enable relay seeding
  file_path: data/seed_relays.txt   # Path to seed file (relative to workdir)
```

### Finder (`yaml/services/finder.yaml`)

```yaml
# Cycle interval (seconds between discovery runs)
interval: 3600.0                 # 1 hour (Range: >= 60.0)

# Event scanning (discovers relays from stored events)
events:
  enabled: true                  # Enable event-based discovery

# External API discovery
api:
  enabled: true                  # Enable API-based discovery
  sources:
    - url: https://api.nostr.watch/v1/online
      enabled: true
      timeout: 30.0              # Request timeout (Range: 1.0-120.0)
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
| `api.enabled` | bool | `true` | - | Enable API discovery |
| `api.sources[].timeout` | float | `30.0` | 1.0-120.0 | Request timeout |
| `api.delay_between_requests` | float | `1.0` | 0.0-10.0 | Inter-request delay |

### Monitor (`yaml/services/monitor.yaml`)

```yaml
# Cycle interval
interval: 3600.0                 # 1 hour (Range: >= 60.0)

# Tor proxy for .onion relays
tor:
  enabled: true                  # Enable Tor proxy
  host: "tor"                    # Tor proxy host (Docker service name)
  port: 9050                     # Tor proxy port (Range: 1-65535)

# Nostr keys for NIP-66 write tests
keys:
  # public_key loaded from config, private_key from MONITOR_PRIVATE_KEY env
  public_key: "79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"

# Timeouts for relay checks
timeouts:
  clearnet: 30.0                 # Clearnet timeout (Range: 5.0-120.0)
  tor: 60.0                      # Tor timeout (Range: 10.0-180.0)

# Concurrency settings
concurrency:
  max_parallel: 50               # Max concurrent checks (Range: 1-500)
  batch_size: 50                 # Relays per DB batch (Range: 1-500)

# Relay selection criteria
selection:
  min_age_since_check: 3600      # Min seconds since last check (Range: >= 0)
```

#### Monitor Configuration Reference

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `interval` | float | `3600.0` | >= 60.0 | Seconds between cycles |
| `tor.enabled` | bool | `true` | - | Enable Tor proxy |
| `tor.host` | string | `127.0.0.1` | - | Tor SOCKS5 host |
| `tor.port` | int | `9050` | 1-65535 | Tor SOCKS5 port |
| `timeouts.clearnet` | float | `30.0` | 5.0-120.0 | Clearnet timeout |
| `timeouts.tor` | float | `60.0` | 10.0-180.0 | Tor timeout |
| `concurrency.max_parallel` | int | `50` | 1-500 | Concurrent checks |
| `concurrency.batch_size` | int | `50` | 1-500 | DB batch size |
| `selection.min_age_since_check` | int | `3600` | >= 0 | Re-check interval |

### Synchronizer (`yaml/services/synchronizer.yaml`)

```yaml
# Cycle interval
interval: 900.0                  # 15 minutes (Range: >= 60.0)

# Tor proxy for .onion relays
tor:
  enabled: true
  host: "tor"
  port: 9050

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

# Network-specific timeouts
timeouts:
  clearnet:
    request: 30.0                # WebSocket timeout (Range: 5.0-120.0)
    relay: 1800.0                # Max time per relay (Range: 60.0-14400.0)
  tor:
    request: 60.0
    relay: 3600.0

# Concurrency settings
concurrency:
  max_parallel: 10               # Parallel connections per process (Range: 1-100)
  max_processes: 10              # Worker processes (Range: 1-32)
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
| `filter.limit` | int | `500` | 1-5000 | Events per request |
| `time_range.lookback_seconds` | int | `86400` | 3600-604800 | Lookback window |
| `timeouts.clearnet.request` | float | `30.0` | 5.0-120.0 | WebSocket timeout |
| `timeouts.clearnet.relay` | float | `1800.0` | 60.0-14400.0 | Per-relay timeout |
| `concurrency.max_parallel` | int | `10` | 1-100 | Connections per process |
| `concurrency.max_processes` | int | `10` | 1-32 | Worker processes |
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
chmod 600 implementations/bigbrotr/.env

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
from services.synchronizer import SynchronizerConfig
import yaml

with open("yaml/services/synchronizer.yaml") as f:
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
- Check `pool.database.host` matches your database hostname
- In Docker, use service names (`postgres`, `pgbouncer`)
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
timeouts:
  clearnet: 60.0  # Increase timeout
  tor: 120.0      # Tor needs more time
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
    host: pgbouncer
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
