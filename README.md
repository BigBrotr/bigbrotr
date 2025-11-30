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
- **Multicore Synchronization**: Uses `aiomultiprocess` for high-performance parallel relay syncing
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
python -m services monitor
python -m services synchronizer
```

### Manual Setup

```python
from core import Brotr
from services import Initializer, Finder, Synchronizer

# Create brotr (includes pool)
brotr = Brotr.from_yaml("implementations/bigbrotr/yaml/core/brotr.yaml")

# Run services
async with brotr.pool:
    # Initialize database
    initializer = Initializer(brotr=brotr)
    await initializer.run()

    # Run synchronizer continuously
    sync = Synchronizer.from_yaml("yaml/services/synchronizer.yaml", brotr=brotr)
    async with sync:
        await sync.run_forever(interval=900)
```

---

## Architecture

### Three-Layer Design

```
Implementation Layer (implementations/bigbrotr/)
          ↑ Uses (YAML configs, SQL schemas)
Service Layer (src/services/)
          ↑ Leverages (Initializer, Finder, Monitor, Synchronizer)
Core Layer (src/core/)
          PRODUCTION READY (Pool, Brotr, BaseService, Logger)
```

### Service Layer

| Service | Purpose | Status |
|---------|---------|--------|
| **Initializer** | Database bootstrap, schema verification | Production Ready |
| **Finder** | Relay discovery from APIs | Production Ready |
| **Monitor** | Relay health checks (NIP-11, NIP-66) | Production Ready |
| **Synchronizer** | Event collection (Multicore supported) | Production Ready |
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
│       ├── monitor.py           # Relay monitoring
│       └── synchronizer.py      # Event synchronization
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
# implementations/bigbrotr/yaml/services/synchronizer.yaml
timeouts:
  clearnet:
    request: 30.0
    relay: 1800.0
  tor:
    request: 60.0
    relay: 3600.0
```

### Environment Variables

```bash
# Database credentials (required)
DB_PASSWORD=your_secure_password
```

---

## Development

### Running Tests

```bash
# Activate virtual environment
source .venv/bin/activate

# Run all tests
pytest tests/unit/ -v
```

---

## Development Status

**Current Phase**: Service Layer Implementation

| Component | Status | Completion |
|-----------|--------|------------|
| Core Layer | Production Ready | 100% |
| Service Layer | In Progress | 66% (4/6) |
| Testing | Active | 90 tests |

See [PROJECT_STATUS.md](PROJECT_STATUS.md) for detailed progress tracking.

---

## Documentation

- **[PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md)** - Complete technical specification
- **[PROJECT_STATUS.md](PROJECT_STATUS.md)** - Current project status and metrics
- **[CLAUDE.md](CLAUDE.md)** - AI assistant guidance

---

## License

**TBD** - To be determined before public release.

---

<p align="center">
  <strong>Built for the Nostr ecosystem</strong>
</p>
