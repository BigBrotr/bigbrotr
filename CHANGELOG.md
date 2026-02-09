# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

---

## [4.0.0] - 2026-02-09

Major architectural restructuring: all code moved under `bigbrotr` namespace package with diamond DAG dependency graph. Nine design problems resolved. No functional or behavioral changes — pure structural refactor.

### BREAKING CHANGES

- **All imports changed**: `from core.X` / `from models.X` / `from services.X` / `from utils.X` → `from bigbrotr.core.X` / `from bigbrotr.models.X` / `from bigbrotr.services.X` / `from bigbrotr.utils.X`
- **CLI entry point changed**: `python -m services <name>` → `python -m bigbrotr <name>` (or `bigbrotr <name>` via console script)
- **Deployment directories renamed**: `implementations/` → `deployments/`
- **Config directories renamed**: `yaml/core/brotr.yaml` → `config/brotr.yaml` (flattened); `yaml/services/` → `config/services/`
- **NIP models extracted**: `from models.nips.nip11 import Nip11` → `from bigbrotr.nips.nip11 import Nip11`
- **YAML loader moved**: `from utils.yaml import load_yaml` → `from bigbrotr.core.yaml import load_yaml`
- **Dependency files removed**: `requirements.txt` / `requirements-dev.txt` deleted; use `pip install -e .` or `pip install -e ".[dev]"`

### Refactored

- **Namespace package**: All source code moved under `src/bigbrotr/` to eliminate pip namespace collisions from generic top-level names (`core`, `models`, `services`, `utils`)
- **Diamond DAG architecture**: Five-layer dependency graph (`services → {core, nips, utils} → models`) replacing the previous linear four-layer stack
- **NIP extraction**: `models/nips/` (18 files with I/O logic: HTTP, DNS, SSL, WebSocket, GeoIP) extracted to `bigbrotr/nips/` as a separate package, restoring models layer purity
- **YAML loader**: `utils/yaml.py` moved to `core/yaml.py` (resolving upward layer dependency — only consumers were in core)
- **CLI decoupled**: `services/__main__.py` moved to `bigbrotr/__main__.py` with sync `cli()` wrapper for console_scripts entry point
- **Monitoring directories merged**: `grafana/` + `prometheus/` → `monitoring/grafana/` + `monitoring/prometheus/` in each deployment
- **Root cleanup**: Deleted `alembic.ini`, `migrations/`, `requirements*.txt`, `requirements*.in`; moved `generate_sql.py` and `templates/` to `tools/`
- **Deleted `src/__init__.py`**: Removed the 107-line file with 36 re-exports that violated the src-layout pattern

### Changed

- **pyproject.toml**: Version `3.0.4` → `4.0.0`; `known-first-party = ["bigbrotr"]`; `include = ["bigbrotr*"]`; `files = ["src/bigbrotr"]` (mypy); `source = ["src/bigbrotr"]` (coverage); added `[project.scripts] bigbrotr = "bigbrotr.__main__:cli"`
- **100+ source files**: Moved under `src/bigbrotr/` with updated imports
- **40+ test files**: Updated with `bigbrotr`-prefixed imports and ~100 mock patch targets rewritten
- **3 Dockerfiles + 3 docker-compose files**: Updated paths, commands, and volume mounts
- **CI workflow**: Updated for new deployment and source paths
- **12 deployment YAML configs**: Updated `_template/yaml/` → `_template/config/` in comments
- **6 service module docstrings**: Updated example paths from `yaml/` to `config/`

### Fixed

- **Stale NIP class references** (pre-existing, exposed by restructuring):
  - `Nip11FetchMetadata` → `Nip11InfoMetadata` (renamed in v3.1.0 but `__init__.py` not updated)
  - `Nip66RttLogs` → `Nip66RttMultiPhaseLogs`
  - `RttDependencies` → `Nip66RttDependencies`
  - `Nip66TestFlags` → `Nip66TestSelection` + `Nip66TestOptions`

### Added

- **Console script**: `bigbrotr` command via `[project.scripts]` in pyproject.toml
- **Integration test infrastructure**: `tests/integration/conftest.py` with testcontainers-based ephemeral PostgreSQL; `tests/integration/test_database_roundtrip.py`
- **SQL generation tooling**: `tools/generate_sql.py` + `tools/templates/sql/` (Jinja2 templates for deployment SQL files)

### Documentation

- **README.md**: Version badge, five-layer diamond DAG architecture diagram, updated all paths/commands/project structure tree, test count → 1896
- **All docs/*.md**: Updated for new paths, imports, and architecture (ARCHITECTURE, CONFIGURATION, DATABASE, DEPLOYMENT, DEVELOPMENT, OVERVIEW, TECHNICAL)
- **CLAUDE.md**: Rewritten for bigbrotr namespace and diamond DAG architecture
- **CONTRIBUTING.md**: Updated paths and install commands
- **Agent knowledge base**: All 7 `.claude/agents/bigbrotr-expert/` files updated

---

## [3.0.4] - 2026-02-07

Architecture refinement release: domain logic extracted from core to `services/common/`, three-tier architecture formalized, and comprehensive test and documentation alignment.

### Refactored
- **`services/common/` package**: Extracted domain queries, constants, and mixins from `core/` into a new shared service infrastructure package with three stable modules:
  - `constants.py`: `ServiceName` and `DataType` StrEnum classes replacing all hardcoded service/data-type strings
  - `mixins.py`: `BatchProgressMixin` and `NetworkSemaphoreMixin` (moved from `core/service.py` and `utils/progress.py`)
  - `queries.py`: 13 domain SQL query functions parameterized with enum values (moved from `core/queries.py`)
- **Core layer purified**: `core/` is now a generic infrastructure facade with zero domain logic
  - Renamed `core/service.py` to `core/base_service.py` (contains only `BaseService` and `BaseServiceConfig`)
  - Removed `core/queries.py` (absorbed into `services/common/queries.py`)
  - Removed `BatchProgress`, `NetworkSemaphoreMixin` from core
- **Brotr API simplified**:
  - Removed `retry` parameter from facade methods (retry always handled internally by Pool)
  - Removed `conn` parameter from `_call_procedure` (use `transaction()` instead)
  - Removed `default_query_limit` and `materialized_views` from `BrotrConfig`
  - Simplified `refresh_matview()` injection prevention (regex guard only)
  - Fixed `result or 0` to `result if result is not None else 0` for correct falsy handling
- **Model layer decoupled**: NIP models (`nip11/fetch`, `nip66/*`) now use stdlib `logging` instead of `core.logger`, maintaining zero core dependencies
- **Model caching**: All frozen dataclasses (`Relay`, `EventRelay`, `Metadata`, `RelayMetadata`) now cache `to_db_params()` in `__post_init__`
- **Service registry**: Uses `ServiceEntry` NamedTuple with `ServiceName` enum keys instead of raw tuples
- **`utils/transport.py`**: Decoupled from `core.logger` (stdlib `logging` only)
- **`utils/progress.py`**: Deleted (functionality moved to `services/common/mixins.py`)

### Changed
- **Monitor service**: Aligned `MetadataFlags` and `CheckResult` with `MetadataType` enum values (`nip11` -> `nip11_info`); removed unused `nip66_probe` field
- **Infrastructure**: Removed `CHECK` constraints from `relay_metadata.metadata_type` across all implementations; validation handled in Python enum layer
- **Implementation configs**: Standardized `.env.example`, `docker-compose.yaml`, and `04_functions_cleanup.sql` across template, bigbrotr, and lilbrotr

### Added
- **69 new unit tests** for `services/common/`:
  - `test_constants.py` (15 tests): `ServiceName` and `DataType` StrEnum value and behavior coverage
  - `test_mixins.py` (15 tests): `BatchProgressMixin` and `NetworkSemaphoreMixin` initialization, composition, and edge cases
  - `test_queries.py` (39 tests): All 13 domain SQL query functions with mocked Brotr, SQL fragment verification, and edge cases
- Total test count: **1854** (up from 1776)

### Documentation
- **Three-tier architecture**: Reframed documentation around Foundation (core + models), Active (services + utils), and Implementation tiers
- **All docs updated**: `ARCHITECTURE.md`, `DEVELOPMENT.md`, `TECHNICAL.md`, `README.md`, `CLAUDE.md` reflect renamed files and `services/common/`
- **Agent knowledge base updated**: `AGENT.md`, `core-reference.md`, `architecture-index.md` aligned with new structure
- **YAML template comments**: Fixed `BaseServiceConfig` file path references in all 4 service templates
- Removed deprecated `test_nip11_nip66.ipynb` notebook

### Chore
- Bumped version to 3.0.4
- Updated secrets baseline line numbers
- Added `AUDIT_REPORT.*` pattern to `.gitignore`
- Removed stale `RESTRUCTURING_PLAN.md`

---

## [3.0.3] - 2026-02-06

Documentation-focused release with comprehensive docstring rewrites, standardized file headers, and cleaned up project documentation.

### Documentation
- **Core layer**: Rewrote docstrings for all core modules (pool, brotr, service, metrics, logger)
- **Models layer**: Rewrote docstrings for all data model modules
- **Services layer**: Rewrote docstrings for services and utilities
- **SQL**: Rewrote SQL file headers and function documentation
- **YAML**: Standardized YAML configuration file headers
- **Tests**: Cleaned up test documentation and removed redundant comments
- **Project docs**: Rewrote project documentation and cleaned up markdown files
- **Agents**: Fixed outdated references and cleaned up agent knowledge base

### Chore
- Updated secrets baseline line numbers

---

## [3.0.2] - 2026-02-05

Code quality and maintainability release with FieldSpec pattern, module reorganization, and comprehensive test restructuring.

### Changed
- **FieldSpec pattern**: Consolidated field parsing with `FieldSpec` dataclass for consistent validation and transformation across NIP models
- **Module reorganization**:
  - Logger now at `src/core/logger.py`, imported as `from core.logger import Logger`
  - Renamed `base_service` to `service` and consolidated mixins
  - Added `NetworkSemaphoreMixin` for simplified service code
- **NIP-11 refactoring**:
  - Migrated to FieldSpec pattern for improved type safety
  - Simplified structure with keyword-only arguments in `create` method
- **NIP-66 refactoring**:
  - Migrated to FieldSpec pattern for improved code quality
  - Extracted `GeoExtractor` helper class for geolocation logic
  - Extracted `CertificateExtractor` helper class for SSL certificate parsing
  - Decomposed RTT method into focused phase methods
  - Added keyword-only arguments in `create` method
- **Models**: Added fail-fast validation and unified `from_db_params` API across all models
- **Core**: Improved type safety and simplified database operations
- **Services**: Updated imports for module renames, simplified code structure
- **Utils**: Moved `NetworkType` enum for better organization, improved configuration flexibility

### Refactored
- **Monitor service**: Updated NIP-11 API usage and decomposed tag building logic
- **Test structure**:
  - Renamed `test_cli.py` to `test_main.py`
  - Renamed `test_base_service.py` to `test_service.py`
  - Moved `test_logger.py` to `tests/unit/core/` to match `src/core/logger.py` location
  - Restructured NIP-11 tests into focused modules (`test_nip11.py`, `test_data.py`, `test_logs.py`, `test_fetch.py`)
  - Restructured NIP-66 tests into focused modules (`test_nip66.py`, `test_rtt.py`, `test_ssl.py`, `test_geo.py`, `test_net.py`, `test_dns.py`, `test_http.py`, `test_logs.py`)
  - Added comprehensive tests for `base.py` and `parsing.py`
  - Updated tests for fail-fast validation and simplified return types

### Style
- Reordered imports per isort conventions
- Combined nested if statements per ruff SIM102

### Chore
- Added EditorConfig for consistent coding styles
- Cleaned up project configuration
- Removed versioned release notes from repository
- Removed auto-generated footer from agents README

---

## [3.0.1] - 2026-02-04

Major refactoring release with new NIP models architecture, Python-side hash computation, and comprehensive documentation alignment.

### Added
- **NIP-11 subpackage** (`src/models/nips/nip11/`):
  - `Nip11` main class with database serialization
  - `Nip11FetchData` with relay info document structure
  - `Nip11FetchLogs` for fetch status tracking
  - HTTP fetch implementation with SSL fallback
- **NIP-66 subpackage** (`src/models/nips/nip66/`):
  - `Nip66` aggregate class with database serialization
  - `Nip66RttMetadata` with WebSocket probe testing
  - `Nip66SslMetadata` with certificate validation
  - `Nip66GeoMetadata` with MaxMind GeoLite2 lookup
  - `Nip66NetMetadata` with ASN lookup
  - `Nip66DnsMetadata` with comprehensive record lookup
  - `Nip66HttpMetadata` from WebSocket handshake
  - Data and logs models for all metadata types
- **NIP base classes** (`src/models/nips/base.py`) for content-addressed storage
- **Async DNS utility** (`src/utils/dns.py`) with IPv4/IPv6 support
- **Retry configuration** for all metadata types in Monitor
- `py.typed` markers for nips subpackages

### Changed
- **Hash computation moved to Python**: SHA-256 hashing now performed in Python instead of PostgreSQL for better portability
- **SQL schema updated**: All implementations (bigbrotr, lilbrotr, template) updated for BYTEA metadata id
- **Monitor service refactored** to use new nips metadata classes
- **Brotr updated** for Python-side metadata hash computation
- **Logging standardized** across all models, utils, and services
- **Default max_batch_size reduced** from 10000 to 1000
- **Network config classes separated** to fix partial YAML override inheritance
- **Metrics endpoint secured** with standardized ports

### Fixed
- Runtime imports for Pydantic models restored
- Column name in `relay_metadata_latest` materialized view corrected
- Null byte validation added to Event content
- Logger-related issues resolved (#124, #78, #99, #141, #92)
- Documentation aligned with actual codebase:
  - BigBrotr Expert reference files updated for NIP subpackages
  - Database column name corrected (`metadata.data` → `metadata.metadata`)
  - BaseService constructor signature documented (config is optional)
  - Version references aligned across all files

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
- **MetadataType expanded** from 4 to 7 types:
  - `nip11_info` - NIP-11 relay information document
  - `nip66_rtt` - Round-trip time measurements
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

[Unreleased]: https://github.com/bigbrotr/bigbrotr/compare/v3.0.4...HEAD
[3.0.4]: https://github.com/bigbrotr/bigbrotr/compare/v3.0.3...v3.0.4
[3.0.3]: https://github.com/bigbrotr/bigbrotr/compare/v3.0.2...v3.0.3
[3.0.2]: https://github.com/bigbrotr/bigbrotr/compare/v3.0.1...v3.0.2
[3.0.1]: https://github.com/bigbrotr/bigbrotr/compare/v3.0.0...v3.0.1
[3.0.0]: https://github.com/bigbrotr/bigbrotr/compare/v2.0.0...v3.0.0
[2.0.0]: https://github.com/bigbrotr/bigbrotr/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/bigbrotr/bigbrotr/releases/tag/v1.0.0
