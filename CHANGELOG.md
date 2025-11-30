# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Nothing yet

### Changed
- Nothing yet

### Fixed
- Nothing yet

---

## [2.0.0] - 2025-11

Complete architectural rewrite from monolithic prototype to modular, enterprise-ready system.

### Added
- Three-layer architecture (Core, Service, Implementation)
- Multiple implementations: BigBrotr (full) and LilBrotr (lightweight)
- Core components: Pool, Brotr, BaseService, Logger
- Services: Initializer, Finder, Monitor, Synchronizer
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
- GitHub Actions CI pipeline (lint, typecheck, test matrix Python 3.9-3.12, Docker build)
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
- secp256k1/bech32 dependencies (using nostr-tools)

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

[Unreleased]: https://github.com/bigbrotr/bigbrotr/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/bigbrotr/bigbrotr/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/bigbrotr/bigbrotr/releases/tag/v1.0.0
