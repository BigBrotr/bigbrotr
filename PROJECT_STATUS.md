# BigBrotr Project Status

**Last Updated**: 2025-11-30
**Version**: 1.0.0-dev
**Status**: Core Complete, Service Layer in Progress (2/7)

---

## Executive Summary

BigBrotr is a modular Nostr data archiving and monitoring system built on Python and PostgreSQL. The project follows a three-layer architecture (Core, Service, Implementation) with dependency injection for testability and flexibility.

**Current Phase**: Service Layer Development

| Metric | Value |
|--------|-------|
| Core Layer | 100% Complete |
| Service Layer | 29% Complete (2/7 services) |
| Unit Tests | 90 passing |

---

## Layer Status

### Core Layer - COMPLETE

The core layer is production-ready and provides the foundation for all services.

| Component | Status | Description |
|-----------|--------|-------------|
| Pool | Done | PostgreSQL connection management |
| Brotr | Done | Database interface + stored procedures |
| BaseService | Done | Abstract base class with state persistence |
| Logger | Done | Structured logging wrapper |

### Service Layer - IN PROGRESS

| Service | Status | Description |
|---------|--------|-------------|
| Initializer | Done | Database bootstrap, schema verification |
| Finder | Done | Relay discovery from APIs |
| Monitor | Pending | Relay health monitoring |
| Synchronizer | Pending | Event collection |
| Priority Synchronizer | Pending | Priority-based sync |
| API | Pending (Phase 3) | REST endpoints |
| DVM | Pending (Phase 3) | Data Vending Machine |

### Implementation Layer - COMPLETE

| Component | Status |
|-----------|--------|
| YAML Configs | Done |
| SQL Schemas | Done |
| Docker Compose | Done |
| Seed Data | Done |

---

## Test Coverage

### Unit Tests

| Test File | Status |
|-----------|--------|
| test_pool.py | Passing |
| test_brotr.py | Passing |
| test_initializer.py | Passing |
| test_finder.py | Passing |
| test_logger.py | Passing |
| **Total** | **90 tests passing** |

### Test Command

```bash
source .venv/bin/activate
pytest tests/unit/ -v
# 90 passed in 0.69s
```

---

## Recent Changes

### 2025-11-30: Architecture Improvements

- Added `run_forever(interval)` to BaseService for continuous operation
- Added `_load_state()` / `_save_state()` for automatic state persistence
- Refactored Finder to use single-cycle `run()` pattern
- Rewrote `__main__.py` CLI from scratch
- Added `discovery_interval` to FinderConfig
- Updated all markdown documentation

### 2025-11-29: Documentation Rewrite

- Rewrote CLAUDE.md with current architecture
- Rewrote README.md with accurate status
- Rewrote PROJECT_SPECIFICATION.md v6.0
- Rewrote PROJECT_STATUS.md

### 2025-11-28: Service Refactoring

- Services now receive `Brotr` instead of `Pool`
- Added `CONFIG_CLASS` attribute for automatic config parsing
- All tests passing

---

## Architecture Decisions

### Current Patterns

| Pattern | Application |
|---------|-------------|
| Dependency Injection | Services receive `Brotr` |
| Composition | Brotr HAS-A Pool |
| Abstract Base Class | `BaseService` |
| Factory Methods | `from_yaml()`, `from_dict()` |
| CONFIG_CLASS | Automatic config parsing |
| State Persistence | Auto load/save via context manager |

### Key Design Decisions

1. **Services receive Brotr, not Pool**: Provides access to both pool operations (`self._brotr.pool`) and business logic (`self._brotr.insert_*`)

2. **CONFIG_CLASS for automatic parsing**: Services define `CONFIG_CLASS` attribute, and `from_dict()` automatically parses YAML into Pydantic model

3. **State persistence via service_state table**: Services save/load state using `SERVICE_NAME` constant, automatically via context manager

4. **run() is single-cycle**: `run()` executes one cycle, `run_forever(interval)` handles the loop

---

## File Structure

```
bigbrotr/
├── src/
│   ├── core/
│   │   ├── __init__.py
│   │   ├── pool.py
│   │   ├── brotr.py
│   │   ├── base_service.py
│   │   └── logger.py
│   │
│   └── services/
│       ├── __init__.py
│       ├── __main__.py
│       ├── initializer.py      (Done)
│       ├── finder.py           (Done)
│       ├── monitor.py          (Pending)
│       ├── synchronizer.py     (Pending)
│       └── ...
│
├── implementations/bigbrotr/
│   ├── yaml/
│   ├── postgres/init/
│   └── docker-compose.yaml
│
├── tests/unit/                  # 90 tests
│
├── CLAUDE.md
├── README.md
├── PROJECT_SPECIFICATION.md
└── PROJECT_STATUS.md
```

---

## Next Steps

### Immediate Priority

1. **Monitor Service**: Implement relay health monitoring (NIP-11, NIP-66)
   - Connect to relays
   - Fetch NIP-11 metadata
   - Store health status

2. **Synchronizer Service**: Implement event collection from relays
   - WebSocket connections
   - Event subscription
   - Batch storage

### Phase 3 (Future)

3. **API Service**: REST endpoints for data access
4. **DVM Service**: Data Vending Machine protocol

---

## Development Commands

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

### Testing

```bash
pytest tests/unit/ -v              # All tests
pytest tests/unit/test_finder.py   # Specific file
pytest -k "health_check"           # Pattern matching
pytest --cov=src                   # With coverage
```

### Running Services

```bash
cd implementations/bigbrotr
python -m services initializer
python -m services finder
python -m services finder --log-level DEBUG
```

### Docker

```bash
cd implementations/bigbrotr
docker-compose up -d
docker-compose logs -f
```

---

## Dependencies

### Production

| Package | Version | Purpose |
|---------|---------|---------|
| asyncpg | 0.30.0 | PostgreSQL driver |
| pydantic | 2.10.4 | Configuration |
| pyyaml | 6.0.2 | YAML parsing |
| aiohttp | 3.13.2 | HTTP client |
| nostr-tools | 1.4.0 | Nostr protocol |

### Development

| Package | Purpose |
|---------|---------|
| pytest | Testing |
| pytest-asyncio | Async tests |
| pytest-cov | Coverage |
| pytest-mock | Mocking |

---

## Known Issues

None at this time. All 90 tests passing.

---

## Contact

**Project**: BigBrotr
**Status**: Active Development
**Branch**: `develop`
