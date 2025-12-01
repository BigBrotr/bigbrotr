# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BigBrotr is a modular Nostr data archiving and monitoring system built with Python 3.9+ and PostgreSQL. It provides relay discovery, health monitoring (NIP-11/NIP-66), and event synchronization with Tor network support.

## Common Commands

```bash
# Install dependencies
pip install -r requirements.txt -r requirements-dev.txt
pre-commit install

# Run tests
pytest tests/unit/ -v                        # All unit tests
pytest tests/unit/test_synchronizer.py -v    # Single file
pytest -k "health_check" -v                  # Pattern match
pytest tests/unit/ --cov=src --cov-report=html  # With coverage

# Code quality
ruff check src/ tests/                       # Lint
ruff format src/ tests/                      # Format
mypy src/                                    # Type check
pre-commit run --all-files                   # All hooks

# Run services (from implementations/bigbrotr/)
python -m services initializer
python -m services finder --log-level DEBUG
python -m services monitor
python -m services synchronizer

# Docker deployment
cd implementations/bigbrotr
docker-compose up -d
docker-compose exec postgres psql -U admin -d bigbrotr
```

## Architecture

Three-layer architecture separating concerns:

```
Implementation Layer (implementations/bigbrotr/, implementations/lilbrotr/)
  └── YAML configs, SQL schemas, Docker, seed data
        │
        ▼
Service Layer (src/services/)
  └── initializer.py, finder.py, monitor.py, synchronizer.py
        │
        ▼
Core Layer (src/core/)
  └── pool.py, brotr.py, base_service.py, logger.py
```

### Core Components
- **Pool** (`src/core/pool.py`): Async PostgreSQL connection pooling with retry logic
- **Brotr** (`src/core/brotr.py`): Database interface with stored procedure wrappers
- **BaseService** (`src/core/base_service.py`): Abstract service base with state persistence and lifecycle management
- **Logger** (`src/core/logger.py`): Structured key=value logging

### Services
- **Initializer**: One-shot database bootstrap and schema verification
- **Finder**: Continuous relay URL discovery from APIs
- **Monitor**: NIP-11/NIP-66 health monitoring with Tor support
- **Synchronizer**: Multicore event collection using aiomultiprocess

### Key Patterns
- Services receive `Brotr` via constructor (dependency injection)
- All services inherit from `BaseService[ConfigClass]`
- Configuration uses Pydantic models with YAML loading
- Passwords loaded from `DB_PASSWORD` environment variable only

## Adding a New Service

1. Create `src/services/myservice.py` with:
   - `MyServiceConfig(BaseModel)` for configuration
   - `MyService(BaseService[MyServiceConfig])` with `run()` method

2. Add configuration: `implementations/bigbrotr/yaml/services/myservice.yaml`

3. Register in `src/services/__main__.py`:
   ```python
   SERVICE_REGISTRY = {
       "myservice": (MyService, MyServiceConfig),
   }
   ```

4. Export from `src/services/__init__.py`

5. Write tests in `tests/unit/test_myservice.py`

## Creating a New Implementation

Implementations are deployment configurations that use the shared core/service layers:

```bash
# Copy an existing implementation
cp -r implementations/bigbrotr implementations/myimpl
cd implementations/myimpl

# Key files to customize:
# - yaml/core/brotr.yaml          Database connection settings
# - yaml/services/*.yaml          Service configurations
# - postgres/init/02_tables.sql   SQL schema (e.g., remove tags/content columns)
# - docker-compose.yaml           Container config, ports (avoid conflicts)
# - .env.example                  Environment template
```

**Common customizations:**
- **Essential metadata only**: Remove `tags`, `tagvalues`, `content` columns from events table (like lilbrotr - indexes all events but omits heavy fields, ~60% disk savings)
- **Tor disabled**: Set `tor.enabled: false` in service YAML files
- **Lower concurrency**: Reduce `concurrency.max_parallel` and `max_processes`
- **Different ports**: Change PostgreSQL/PGBouncer/Tor ports in docker-compose.yaml
- **Event filtering**: Set `filter.kinds` in synchronizer.yaml to store only specific event types

## Git Workflow

- **Main branch**: `main` (stable releases)
- **Development branch**: `develop` (active development)
- **Feature branches**: `feature/<name>` (from develop)
- **Commit style**: Conventional commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`)
