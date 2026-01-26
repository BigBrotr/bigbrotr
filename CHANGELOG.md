# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

---

## [3.0.0] - 2026-01-26

Major release with four-layer architecture, expanded NIP-66 compliance, and comprehensive AI-assisted development tooling.

### Breaking Changes
- Service `initializer` renamed to `seeder`
- Service config classes now extend `BaseServiceConfig` instead of `BaseModel`
- Constructor signature changed: `__init__(brotr, config)` instead of `__init__(config, brotr)`
- MetadataType values changed: `nip66_rtt` split into granular types

### Added
- **Four-layer architecture**: Added Utils layer between Core and Services
- **New Utils module** (`src/utils/`):
  - `NetworkConfig` - Multi-network configuration (clearnet, tor, i2p, loki)
  - `KeysConfig` - Nostr keypair configuration from environment
  - `BatchProgress` - Batch processing progress tracking dataclass
  - `transport.py` - Multi-network transport factory (aiohttp/aiohttp-socks)
  - `yaml.py` - YAML configuration loading utilities
  - `parsing.py` - URL and data parsing utilities
- **Prometheus metrics** (`src/core/metrics.py`):
  - `SERVICE_INFO` - Static service metadata
  - `SERVICE_GAUGE` - Point-in-time values with labels
  - `SERVICE_COUNTER` - Cumulative counters with labels
  - `CYCLE_DURATION_SECONDS` - Histogram for cycle duration percentiles
- **MetadataType expanded** from 4 to 8 types:
  - `nip11` - NIP-11 relay information document
  - `nip66_rtt` - Round-trip time measurements
  - `nip66_probe` - Connectivity probe results (openable, readable, writable)
  - `nip66_ssl` - SSL certificate information
  - `nip66_geo` - Geolocation data
  - `nip66_net` - Network information (ASN, ISP)
  - `nip66_dns` - DNS resolution data
  - `nip66_http` - HTTP header analysis
- **Validator service** - Streaming relay validation with multi-network support
  - NIP-42 authentication support
  - Probabilistic candidate selection (Efraimidis-Spirakis algorithm)
  - Automatic cleanup of failed candidates (configurable threshold)
- **Full multi-network support** in all services:
  - Clearnet (wss://, ws://)
  - Tor (.onion via SOCKS5 proxy)
  - I2P (.i2p via SOCKS5 proxy)
  - Lokinet (.loki via SOCKS5 proxy)
- **Monitor service restructured**:
  - `BatchProgress` for tracking check progress
  - `CheckResult` for individual relay check results
  - `Nip66RelayMetadata` for NIP-66 compliant output
- **31 AI agents** for development assistance:
  - 29 generic agents (python-pro, security-auditor, etc.)
  - 2 specialized agents (nostr-expert, bigbrotr-expert)
- **3 audit commands** (`/audit-quick`, `/audit-core`, `/audit-full`)
- NIP-42 authentication support in Validator, Monitor, and Synchronizer
- Comprehensive docstrings across all models and services
- Keys model for loading Nostr keypairs from environment variables

### Changed
- **Architecture**: Three-layer → Four-layer (Core, Utils, Services, Implementation)
- **Test structure** reorganized to `tests/unit/{core,models,services,utils}/`
- **Config inheritance**: All service configs now extend `BaseServiceConfig`
- **Constructor order**: `(brotr, config)` instead of `(config, brotr)` for consistency
- Finder now stores candidates in `service_data` table (Validator picks them up)
- Monitor checks use `service_data` checkpoints for efficient scheduling
- Synchronizer uses `relay_metadata_latest` view for faster relay selection
- Improved error handling and logging across all services
- Enhanced test coverage with 411+ unit tests

### Fixed
- Race conditions in Monitor metrics collection (added `asyncio.Lock`)
- Resource leaks in Monitor client shutdown (added `try/finally`)
- Memory optimization in Monitor with chunked relay processing

### Migration Guide

**1. Update service imports:**
```python
# Before (v2.x)
from pydantic import BaseModel
class MyServiceConfig(BaseModel):
    interval: float = 300.0

# After (v3.0.0)
from core import BaseServiceConfig
class MyServiceConfig(BaseServiceConfig):
    # interval is inherited from BaseServiceConfig
    pass
```

**2. Update constructor signatures:**
```python
# Before (v2.x)
def __init__(self, config: MyConfig, brotr: Brotr):
    self._config = config
    self._brotr = brotr

# After (v3.0.0)
def __init__(self, brotr: Brotr, config: MyConfig | None = None):
    super().__init__(brotr=brotr, config=config or MyConfig())
```

**3. Update MetadataType references:**
```python
# Before (v2.x)
type = MetadataType.NIP66_RTT  # Was used for all NIP-66 data

# After (v3.0.0)
type = MetadataType.NIP66_RTT    # Only for RTT measurements
type = MetadataType.NIP66_PROBE  # For connectivity checks
type = MetadataType.NIP66_SSL    # For SSL certificate data
type = MetadataType.NIP66_GEO    # For geolocation
type = MetadataType.NIP66_NET    # For network info
type = MetadataType.NIP66_DNS    # For DNS data
type = MetadataType.NIP66_HTTP   # For HTTP headers
```

---

## [2.0.0] - 2025-12

Complete architectural rewrite from monolithic prototype to modular, enterprise-ready system.

### Added
- Three-layer architecture (Core, Service, Implementation)
- Multiple implementations: BigBrotr (full) and LilBrotr (lightweight)
- Core components: Pool, Brotr, BaseService, Logger
- Services: Seeder, Finder, Monitor, Synchronizer
- Async database driver (asyncpg) with connection pooling
- PGBouncer for connection management
- BYTEA storage for 50% space savings
- Pydantic configuration validation
- YAML-driven configuration
- Service state persistence
- Graceful shutdown handling
- NIP-11 and NIP-66 content deduplication
- 174 unit tests with pytest
- Pre-commit hooks (ruff, mypy)
- Comprehensive documentation (ARCHITECTURE, CONFIGURATION, DATABASE, DEVELOPMENT, DEPLOYMENT)
- GitHub Actions CI pipeline (lint, typecheck, test matrix Python 3.11-3.14, Docker build)
- Issue templates (bug report, feature request)
- Pull request template
- CHANGELOG.md (Keep a Changelog format)
- CONTRIBUTING.md (contribution guidelines)
- SECURITY.md (security policy)
- CODE_OF_CONDUCT.md (Contributor Covenant)

### Changed
- Architecture: Monolithic → Three-layer modular design
- Configuration: Environment variables → YAML + Pydantic
- Database driver: psycopg2 (sync) → asyncpg (async)
- Storage format: CHAR (hex) → BYTEA (binary)
- Service name: syncronizer → synchronizer (fixed typo)
- Multicore: multiprocessing.Pool → aiomultiprocess

### Removed
- pgAdmin (use external tools instead)
- pandas dependency
- secp256k1/bech32 dependencies (using nostr-sdk)

### Fixed
- Connection pooling (was creating new connections per operation)
- State persistence (services now resume from last state)
- Configuration validation (now validates at startup)
- Graceful shutdown (services handle SIGTERM properly)

---

## [1.0.0] - 2025-06

Initial prototype release.

### Added
- Full event archiving from Nostr relays
- Relay monitoring with NIP-11 support
- Connectivity testing (openable, readable, writable)
- RTT measurement for all operations
- Tor support for .onion relays
- Multicore processing with multiprocessing.Pool
- Time-window stack algorithm for large event volumes
- Docker Compose deployment
- PostgreSQL database with stored functions
- 8,865 seed relay URLs

### Known Issues
- No async database (synchronous psycopg2)
- No connection pooling
- Finder service not implemented (stub only)
- No unit tests
- No configuration validation
- No graceful shutdown
- No state persistence
- Typo in service name ("syncronizer")

---

[Unreleased]: https://github.com/bigbrotr/bigbrotr/compare/v3.0.0...HEAD
[3.0.0]: https://github.com/bigbrotr/bigbrotr/compare/v2.0.0...v3.0.0
[2.0.0]: https://github.com/bigbrotr/bigbrotr/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/bigbrotr/bigbrotr/releases/tag/v1.0.0
