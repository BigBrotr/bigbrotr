# BigBrotr

**A Production-Grade Nostr Data Archiving and Monitoring System**

[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![PostgreSQL](https://img.shields.io/badge/postgresql-14+-blue.svg)](https://www.postgresql.org/)
[![License](https://img.shields.io/badge/license-TBD-lightgrey.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-development-yellow.svg)](PROJECT_STATUS.md)

---

## Overview

BigBrotr is a modular, production-grade system for archiving and monitoring the Nostr protocol ecosystem. Built on Python and PostgreSQL, it provides comprehensive network monitoring, event synchronization, and statistical analysis.

### Key Features

- 🏗️ **Three-Layer Architecture**: Clean separation between Core, Service, and Implementation layers
- 💉 **Dependency Injection**: Testable, flexible component composition
- ⚡ **Production-Ready Core**: Enterprise-grade connection pooling, retry logic, configuration management
- 🔌 **Modular Services**: Enable/disable services per implementation
- 📊 **Comprehensive Monitoring**: Relay health checks (NIP-11, NIP-66)
- 🐳 **Docker Compose**: Easy deployment and orchestration
- 🌐 **Network Support**: Clearnet and Tor (SOCKS5 proxy)
- 🎯 **Type-Safe**: Full type hints and Pydantic validation

---

## Quick Start

### Prerequisites

- Python 3.9+
- PostgreSQL 14+
- Docker & Docker Compose (recommended)
- Git

### Installation

```bash
# Clone repository
git clone https://github.com/yourusername/bigbrotr.git
cd bigbrotr

# Install dependencies
pip install -r requirements.txt

# Set up environment
cp implementations/bigbrotr/.env.example implementations/bigbrotr/.env
# Edit .env with your DB_PASSWORD
```

### Running with Docker Compose

```bash
cd implementations/bigbrotr
docker-compose up -d
```

### Manual Setup

```python
from core.pool import ConnectionPool
from core.brotr import Brotr

# Create connection pool
pool = ConnectionPool.from_yaml("implementations/bigbrotr/config/core/pool.yaml")

# Create Brotr interface
brotr = Brotr.from_yaml("implementations/bigbrotr/config/core/brotr.yaml")

# Use it
async with brotr.pool:
    # Insert event
    await brotr.insert_event(
        event_id="...",
        pubkey="...",
        created_at=1699876543,
        kind=1,
        tags=[],
        content="Hello Nostr!",
        sig="...",
        relay_url="wss://relay.example.com",
        relay_network="clearnet",
        relay_inserted_at=1699876000,
        seen_at=1699876543
    )

    # Cleanup orphaned records
    deleted = await brotr.cleanup_orphans()
    print(deleted)  # {"events": 10, "nip11": 5, "nip66": 3}
```

---

## Architecture

### Three-Layer Design

```
┌─────────────────────────────────────┐
│     Implementation Layer            │
│  (YAML configs, SQL schemas, etc.)  │
└─────────────────────────────────────┘
                ▲
                │ Uses
                │
┌─────────────────────────────────────┐
│       Service Layer                 │
│  (Finder, Monitor, Synchronizer)    │
└─────────────────────────────────────┘
                ▲
                │ Leverages
                │
┌─────────────────────────────────────┐
│        Core Layer                   │
│  (Pool, Brotr, Service wrapper)     │
└─────────────────────────────────────┘
```

### Core Components

- **ConnectionPool** (`src/core/pool.py`): Enterprise-grade PostgreSQL connection management
  - Async pooling with asyncpg
  - Automatic retry with exponential backoff
  - PGBouncer compatibility
  - Connection recycling
  - ~580 lines, production-ready ✅

- **Brotr** (`src/core/brotr.py`): High-level database interface
  - Dependency injection for ConnectionPool
  - Stored procedure wrappers
  - Batch operations
  - Cleanup utilities
  - ~775 lines, production-ready ✅

- **Service** (`src/core/service.py`): Generic lifecycle wrapper
  - Logging, health checks, statistics
  - Wraps any service
  - Design complete, implementation pending ⚠️

### Service Layer (Planned)

- **Finder**: Relay discovery
- **Monitor**: Relay health checks (NIP-11, NIP-66)
- **Synchronizer**: Event collection from relays
- **Priority Synchronizer**: Priority relay sync
- **Initializer**: Database bootstrap
- **API**: REST endpoints (Phase 3)
- **DVM**: Data Vending Machine (Phase 3)

---

## Project Structure

```
bigbrotr/
├── src/
│   ├── core/                    # Foundation components ✅
│   │   ├── pool.py              # Connection pool (production-ready)
│   │   ├── brotr.py             # Database interface (production-ready)
│   │   ├── service.py           # Service wrapper (design complete)
│   │   ├── config.py            # Config management (pending)
│   │   ├── logger.py            # Logging system (pending)
│   │   └── utils.py             # Shared utilities (pending)
│   │
│   ├── services/                # Service implementations ⚠️
│   │   ├── initializer.py       # Database seeding
│   │   ├── finder.py            # Relay discovery
│   │   ├── monitor.py           # Health checks
│   │   ├── synchronizer.py      # Event collection
│   │   └── ...
│   │
│   └── dockerfiles/             # Container definitions
│
├── implementations/
│   └── bigbrotr/                # Primary implementation
│       ├── config/              # YAML configurations
│       │   ├── core/            # Core component configs
│       │   ├── services/        # Service configs
│       │   ├── postgres/        # PostgreSQL configs
│       │   └── pgbouncer/       # PGBouncer configs
│       ├── data/                # Seed data, relay lists
│       ├── docker-compose.yaml  # Deployment orchestration
│       └── .env                 # Environment variables (not in repo)
│
├── tests/                       # Test suite
│   ├── test_composition.py      # Core composition tests ✅
│   └── test_service_wrapper.py  # Service wrapper tests (reference)
│
├── docs/
│   └── old/                     # Archived documentation
│
├── PROJECT_SPECIFICATION.md     # Complete technical spec
├── PROJECT_STATUS.md            # Current project status
├── README.md                    # This file
├── CLAUDE.md                    # Claude AI instructions
└── requirements.txt             # Python dependencies
```

---

## Documentation

### Primary Documentation

- **[PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md)** - Complete technical specification
  - Architecture overview
  - Core components API
  - Service layer design
  - Database schema
  - Configuration system
  - Deployment guide
  - Design patterns reference

- **[PROJECT_STATUS.md](PROJECT_STATUS.md)** - Current project status
  - Completed work
  - Pending tasks
  - Recent refactorings
  - Code metrics
  - Next steps

### Archived Documentation

- **[docs/old/](docs/old/)** - Historical refactoring and design documents
  - Dependency Injection refactoring
  - Composition pattern evolution
  - Service wrapper design
  - Pool improvements
  - Timeout separation rationale

---

## Development Status

**Current Phase**: Core Infrastructure Development

| Component | Status | Lines | Coverage |
|-----------|--------|-------|----------|
| ConnectionPool | ✅ Production Ready | ~580 | Manual ✅ |
| Brotr | ✅ Production Ready | ~775 | Manual ✅ |
| Service Wrapper | ⚠️ Design Complete | - | Design only |
| Services | ⚠️ Pending | - | - |

**Overall Progress**: ~20% (Core: 60%, Services: 0%)

See [PROJECT_STATUS.md](PROJECT_STATUS.md) for detailed progress tracking.

---

## Key Design Decisions

### 1. Dependency Injection

Reduced Brotr.__init__ parameters from 28 to 12 (57% reduction):

```python
# Before: 28 parameters (16 pool + 12 brotr)
brotr = Brotr(host="...", port=5432, database="...", user="...", ...)

# After: 12 parameters (1 pool + 11 brotr) - Dependency Injection
pool = ConnectionPool(host="...", database="...")
brotr = Brotr(pool=pool, default_batch_size=200)
```

**Benefits**: Testability, pool sharing, cleaner API

### 2. Composition with Public Pool

```python
# Brotr HAS-A pool (not IS-A)
brotr.pool.fetch(...)      # Pool operations (explicit)
brotr.insert_event(...)    # Brotr operations (business logic)
```

**Benefits**: Clear separation, explicit API, no method conflicts

### 3. Service Wrapper for Cross-Cutting Concerns

```python
# Generic wrapper for logging, health checks, stats
service = Service(pool, name="db_pool")
async with service:
    # Automatic logging, health checks, statistics
    await service.instance.fetch(...)
```

**Benefits**: DRY, separation of concerns, uniform interface

---

## Configuration

### YAML-Based Configuration

```yaml
# implementations/bigbrotr/config/core/pool.yaml
database:
  host: localhost
  port: 5432
  database: brotr
  user: admin

limits:
  min_size: 5
  max_size: 20

timeouts:
  acquisition: 10.0

retry:
  max_attempts: 3
  exponential_backoff: true
```

### Environment Variables

```bash
# Database credentials
DB_PASSWORD=your_secure_password

# Tor proxy (optional)
SOCKS5_PROXY_URL=socks5://127.0.0.1:9050

# Service configs
IMPLEMENTATION=bigbrotr
CONFIG_DIR=implementations/bigbrotr/config
```

---

## Technology Stack

### Core

- **Language**: Python 3.9+
- **Database**: PostgreSQL 14+
- **Connection Pooling**: asyncpg + PGBouncer
- **Validation**: Pydantic 2.x
- **Config Format**: YAML

### Libraries

- **asyncpg**: PostgreSQL async driver
- **pydantic**: Configuration validation
- **PyYAML**: YAML parsing
- **nostr-tools** (1.4.0): Nostr protocol library

### Future

- **FastAPI**: REST API framework (Phase 3)
- **pytest**: Testing framework
- **structlog**: Structured logging
- **prometheus-client**: Metrics

### Infrastructure

- **Docker**: Containerization
- **Docker Compose**: Orchestration
- **PostgreSQL**: Data storage
- **PGBouncer**: Connection pooling
- **Tor**: Network privacy (optional)

---

## Design Patterns

| Pattern | Application | Purpose |
|---------|-------------|---------|
| Dependency Injection | Brotr receives pool | Testability, flexibility |
| Composition over Inheritance | Brotr HAS-A pool | Clear separation |
| Decorator/Wrapper | Service wraps services | Cross-cutting concerns |
| Factory Method | from_yaml(), from_dict() | Config-driven construction |
| Template Method | _call_delete_procedure() | DRY for similar operations |
| Protocol/Duck Typing | ManagedService | Flexible, non-invasive |

---

## Contributing

**Status**: Private development, not accepting contributions yet.

**Internal Guidelines**:
- Type hints required for all public APIs
- Docstrings for all classes and methods
- DRY principle - no code duplication
- Design patterns over quick hacks
- Tests for new features

---

## Roadmap

### Phase 1: Core Infrastructure (Current - 60% Complete)

- ✅ ConnectionPool implementation
- ✅ Brotr implementation with dependency injection
- ✅ Helper methods and DRY improvements
- ⚠️ Service wrapper implementation
- ⚠️ Logger module
- ⚠️ Config module

### Phase 2: Service Layer (Planned)

- Initializer service
- Finder service
- Monitor service
- Synchronizer service
- Priority Synchronizer service

### Phase 3: Public Access (Future)

- REST API service
- Data Vending Machine (DVM)
- Authentication and authorization
- Rate limiting

### Phase 4: Production Hardening (Future)

- Comprehensive test suite
- Performance optimization
- Monitoring and observability
- Documentation
- Deployment automation

---

## Testing

```bash
# Run composition tests
python3 tests/test_composition.py

# Output:
# Testing Brotr with Composition Pattern (Dependency Injection)
# All tests passed! ✓
```

**Current Testing**: Manual testing via test scripts
**Planned**: pytest-based unit and integration tests

---

## License

**TBD** - To be determined before public release.

---

## Links

- **Documentation**: [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md)
- **Status**: [PROJECT_STATUS.md](PROJECT_STATUS.md)
- **Issues**: GitHub Issues (TBD)
- **Nostr Protocol**: [nostr.com](https://nostr.com)
- **nostr-tools**: [PyPI](https://pypi.org/project/nostr-tools/)

---

## Contact

**Repository**: https://github.com/yourusername/bigbrotr
**Status**: Private development, not production-ready

---

<p align="center">
  <strong>Built with ❤️ for the Nostr ecosystem</strong>
</p>
