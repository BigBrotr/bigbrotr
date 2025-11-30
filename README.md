# BigBrotr

**A Production-Grade Nostr Data Archiving and Monitoring System**

[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![PostgreSQL](https://img.shields.io/badge/postgresql-14+-blue.svg)](https://www.postgresql.org/)
[![Tests](https://img.shields.io/badge/tests-90%20passing-brightgreen.svg)](tests/)
[![License](https://img.shields.io/badge/license-TBD-lightgrey.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-development-yellow.svg)](PROJECT_STATUS.md)

---

## Overview

BigBrotr is a modular, production-grade system for archiving and monitoring the Nostr protocol ecosystem. Built on Python and PostgreSQL, it provides comprehensive network monitoring, event synchronization, and relay discovery.

### Key Features

- **Three-Layer Architecture**: Clean separation between Core, Service, and Implementation layers
- **Dependency Injection**: Testable, flexible component composition
- **Production-Ready Core**: Enterprise-grade pooling, retry logic, configuration management
- **State Persistence**: Services automatically save/load state to database
- **Docker Compose**: Easy deployment and orchestration
- **Network Support**: Clearnet and Tor (SOCKS5 proxy)
- **Type-Safe**: Full type hints and Pydantic validation

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

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

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

# Run services
python -m services initializer
python -m services finder
```

### Manual Setup

```python
from core import Brotr
from services import Initializer, Finder

# Create brotr (includes pool)
brotr = Brotr.from_yaml("implementations/bigbrotr/yaml/core/brotr.yaml")

# Run services
async with brotr.pool:
    # Initialize database
    initializer = Initializer(brotr=brotr)
    await initializer.run()

    # Discover relays (continuous)
    finder = Finder(brotr=brotr)
    async with finder:
        await finder.run_forever(interval=3600)
```

---

## Architecture

### Three-Layer Design

```
Implementation Layer (implementations/bigbrotr/)
          ↑ Uses (YAML configs, SQL schemas)
Service Layer (src/services/)
          ↑ Leverages (Initializer, Finder, Monitor...)
Core Layer (src/core/)
          PRODUCTION READY (Pool, Brotr, BaseService, Logger)
```

### Core Components

| Component | Purpose | Status |
|-----------|---------|--------|
| **Pool** | PostgreSQL connection management | Production Ready |
| **Brotr** | Database interface + stored procedures | Production Ready |
| **BaseService** | Abstract base class with state persistence | Production Ready |
| **Logger** | Structured logging | Production Ready |

### Service Layer

| Service | Purpose | Status |
|---------|---------|--------|
| **Initializer** | Database bootstrap, schema verification | Production Ready |
| **Finder** | Relay discovery from APIs | Production Ready |
| Monitor | Relay health checks (NIP-11, NIP-66) | Pending |
| Synchronizer | Event collection from relays | Pending |
| API | REST endpoints | Pending (Phase 3) |
| DVM | Data Vending Machine | Pending (Phase 3) |

---

## Project Structure

```
bigbrotr/
├── src/
│   ├── core/                    # Foundation components
│   │   ├── pool.py              # PostgreSQL connection management
│   │   ├── brotr.py             # Database interface
│   │   ├── base_service.py      # Abstract base for services
│   │   └── logger.py            # Structured logging
│   │
│   └── services/                # Service implementations
│       ├── __main__.py          # CLI entry point
│       ├── initializer.py       # Database bootstrap
│       ├── finder.py            # Relay discovery
│       └── ...                  # Other services
│
├── implementations/
│   └── bigbrotr/                # Primary implementation
│       ├── yaml/                # YAML configurations
│       │   ├── core/            # Core component configs
│       │   └── services/        # Service configs
│       ├── postgres/            # PostgreSQL schemas
│       ├── docker-compose.yaml  # Deployment
│       └── .env                 # Environment variables
│
├── tests/                       # Test suite (90 tests)
│   └── unit/                    # Unit tests
│
├── PROJECT_SPECIFICATION.md     # Complete technical spec
├── PROJECT_STATUS.md            # Current project status
├── CLAUDE.md                    # AI assistant guidance
└── README.md                    # This file
```

---

## Configuration

### YAML-Based Configuration

```yaml
# implementations/bigbrotr/yaml/core/brotr.yaml
pool:
  database:
    host: localhost
    port: 5432
    database: bigbrotr
    user: admin

  limits:
    min_size: 5
    max_size: 20
```

### Environment Variables

```bash
# Database credentials (required)
DB_PASSWORD=your_secure_password
```

---

## Usage Examples

### Running Services via CLI

```bash
cd implementations/bigbrotr

# Run initializer (one-shot)
python -m services initializer

# Run finder (continuous)
python -m services finder
python -m services finder --log-level DEBUG
```

### Programmatic Usage

```python
import asyncio
from core import Brotr
from services import Initializer, Finder

async def main():
    brotr = Brotr.from_yaml("yaml/core/brotr.yaml")

    async with brotr.pool:
        # Initialize database
        initializer = Initializer(brotr=brotr)
        await initializer.run()

        # Run finder continuously
        finder = Finder.from_yaml("yaml/services/finder.yaml", brotr=brotr)
        async with finder:
            await finder.run_forever(interval=3600)

asyncio.run(main())
```

---

## Development

### Running Tests

```bash
# Activate virtual environment
source .venv/bin/activate

# Run all tests
pytest tests/unit/ -v

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/unit/test_finder.py -v
```

### Test Statistics

- Total tests: 90
- All passing

---

## Technology Stack

### Core

| Technology | Version | Purpose |
|------------|---------|---------|
| Python | 3.9+ | Programming language |
| PostgreSQL | 14+ | Database storage |
| asyncpg | 0.30.0 | Async PostgreSQL driver |
| Pydantic | 2.10.4 | Configuration validation |
| PyYAML | 6.0.2 | YAML parsing |
| aiohttp | 3.13.2 | Async HTTP client |
| nostr-tools | 1.4.0 | Nostr protocol library |

### Infrastructure

| Technology | Purpose |
|------------|---------|
| Docker | Containerization |
| Docker Compose | Service orchestration |
| PGBouncer | Connection pooling |

---

## Development Status

**Current Phase**: Core Complete, Service Layer in Progress

| Component | Status | Completion |
|-----------|--------|------------|
| Core Layer | Production Ready | 100% |
| Service Layer | In Progress | 29% (2/7) |
| Testing | Active | 90 tests |

See [PROJECT_STATUS.md](PROJECT_STATUS.md) for detailed progress tracking.

---

## Roadmap

### Phase 1: Core Infrastructure - COMPLETE

- Pool implementation
- Brotr implementation
- BaseService abstract class
- Logger module

### Phase 2: Service Layer - IN PROGRESS

- Initializer service - DONE
- Finder service - DONE
- Monitor service - Next
- Synchronizer service

### Phase 3: Public Access - PLANNED

- REST API service
- Data Vending Machine (DVM)

---

## Documentation

- **[PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md)** - Complete technical specification
- **[PROJECT_STATUS.md](PROJECT_STATUS.md)** - Current project status and metrics
- **[CLAUDE.md](CLAUDE.md)** - AI assistant guidance

---

## Contributing

**Status**: Private development, not accepting contributions yet.

---

## License

**TBD** - To be determined before public release.

---

## Links

- **Documentation**: [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md)
- **Status**: [PROJECT_STATUS.md](PROJECT_STATUS.md)
- **Nostr Protocol**: [nostr.com](https://nostr.com)

---

<p align="center">
  <strong>Built for the Nostr ecosystem</strong>
</p>
