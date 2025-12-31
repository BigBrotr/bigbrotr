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
pytest tests/ -v                             # All tests
pytest tests/services/test_synchronizer.py -v # Single file
pytest -k "health_check" -v                  # Pattern match
pytest tests/ --cov=src --cov-report=html    # With coverage

# Code quality
ruff check src/ tests/                       # Lint
ruff format src/ tests/                      # Format
mypy src/                                    # Type check
pre-commit run --all-files                   # All hooks

# Run services (from implementations/bigbrotr/)
python -m services seeder
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
  └── seeder.py, finder.py, validator.py, monitor.py, synchronizer.py
        │
        ▼
Core Layer (src/core/)
  └── pool.py, brotr.py, base_service.py, logger.py
        │
        ▼
Models Layer (src/models/)
  └── Event, Relay, EventRelay, Keys, Metadata, Nip11, Nip66, RelayMetadata
```

**Note on Data Storage**: The `Nip11` and `Nip66` Python models are stored in the unified
`metadata` table using content-addressed deduplication (SHA-256 hash). The `relay_metadata`
table links relays to metadata records via the `type` column (`nip11`, `nip66_rtt`, `nip66_ssl`, `nip66_geo`).

### Core Components
- **Pool** (`src/core/pool.py`): Async PostgreSQL connection pooling with retry logic
- **Brotr** (`src/core/brotr.py`): Database interface with stored procedure wrappers
- **BaseService** (`src/core/base_service.py`): Abstract service base with state persistence and lifecycle management
- **Logger** (`src/core/logger.py`): Structured key=value logging

### Services
- **Seeder**: One-shot relay seeding for validation
- **Finder**: Continuous relay URL discovery from APIs and events
- **Validator**: Relay validation and functional testing with Tor support
- **Monitor**: NIP-11/NIP-66 health monitoring with comprehensive checks
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

5. Write tests in `tests/services/test_myservice.py`

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

## Specialized Agents

This project uses two specialized knowledge agents located in `.claude/agents/`:

### Nostr Expert Agent

**Location:** `.claude/agents/nostr-expert/`

For questions about the Nostr protocol, NIPs, event formats, and protocol implementation.

**Knowledge Base** (in `.claude/resources/`):
- **NIPs**: All 94 Nostr Implementation Possibility specifications
- **rust-nostr**: Complete Rust library with Python bindings (nostr-sdk)
- **Khatru**: Go relay framework for relay development

**Capabilities:**
1. **Protocol expertise**: Explain any NIP, event kind, tag, or message format
2. **Python client development**: Generate code using nostr-sdk
3. **Go relay development**: Guide implementation with Khatru framework
4. **Event validation**: Check events against NIP specifications
5. **Best practices**: Security, privacy, and implementation patterns

**Quick Reference Files:**
- `nip-index.md` - NIPs organized by category
- `kind-index.md` - All 150+ event kinds
- `tag-index.md` - Common tags and usage
- `nostr-sdk-python-reference.md` - Python SDK documentation
- `khatru-reference.md` - Khatru framework documentation

**When to Use:**
- Understanding Nostr protocol details
- Implementing NIP specifications
- Writing Nostr client code (Python)
- Developing relays (Go/Khatru)
- Validating event structures
- Protocol compliance questions

---

### BigBrotr Expert Agent

**Location:** `.claude/agents/bigbrotr-expert/`

For developing, troubleshooting, and extending the BigBrotr codebase.

**Expertise Areas:**
1. **Core layer**: Pool, Brotr, BaseService, Logger
2. **Service layer**: Seeder, Finder, Validator, Monitor, Synchronizer
3. **Data models**: Event, Relay, Metadata, Keys, Nip11, Nip66
4. **Database**: PostgreSQL schema, stored procedures, views, indexes
5. **Testing**: Unit tests, fixtures, mocking strategies

**Capabilities:**
1. **Development**: Write new services, modify existing code, add features
2. **Architecture**: Navigate three-layer design, understand component relationships
3. **Database**: Work with schema, procedures, queries, migrations
4. **Testing**: Write comprehensive tests following project patterns
5. **Troubleshooting**: Debug issues, analyze errors, optimize performance

**Quick Reference Files:**
- `architecture-index.md` - Component relationships and design patterns
- `core-reference.md` - Pool, Brotr, BaseService, Logger API reference
- `services-reference.md` - All services with configs and workflows
- `models-reference.md` - Data models and database mappings
- `database-reference.md` - Schema, procedures, views, sample queries
- `testing-reference.md` - Testing patterns, fixtures, examples

**When to Use:**
- Adding new services or features
- Modifying existing BigBrotr code
- Understanding architecture and patterns
- Writing or debugging tests
- Database schema questions
- Performance optimization
- Troubleshooting errors

---

## Agent Collaboration

The two agents work together for Nostr-related BigBrotr development:

```
┌───────────────────────────────────────────────────┐
│              Development Workflow                 │
├───────────────────────────────────────────────────┤
│                                                   │
│   ┌─────────────────┐      ┌──────────────────┐   │
│   │  NOSTR EXPERT   │      │ BIGBROTR EXPERT  │   │
│   │                 │      │                  │   │
│   │ • Protocol      │◄────►│ • Codebase       │   │
│   │ • NIPs          │      │ • Architecture   │   │
│   │ • nostr-sdk     │      │ • Database       │   │
│   │ • Validation    │      │ • Testing        │   │
│   └─────────────────┘      └──────────────────┘   │
│                                                   │
└───────────────────────────────────────────────────┘
```

**Example Collaboration:**
- **Nostr Expert**: Provides NIP-66 specification details and event structure
- **BigBrotr Expert**: Implements Monitor service following architecture patterns
- **Result**: Protocol-compliant implementation with proper testing and integration

---

## When to Use Which Agent

### Use Nostr Expert for:
- "How does NIP-17 gift wrapping work?"
- "What are the valid event kinds for long-form content?"
- "How do I create a zap request event?"
- "Write Python code to subscribe to kind 1 events"
- "What tags are required for NIP-65 relay lists?"

### Use BigBrotr Expert for:
- "How do I add a new service to BigBrotr?"
- "What's the database schema for relay metadata?"
- "How does cursor-based pagination work in Finder?"
- "Write tests for the Monitor service"
- "How do I create a new implementation variant?"

### Use Both for:
- "Implement NIP-66 monitoring events in BigBrotr"
- "Add support for NIP-96 file storage service"
- "Validate events according to NIP-01 in Synchronizer"
- "Create a service that publishes kind 10002 events"

---

## Agent Access

To work with an agent, read its `AGENT.md` file:

```bash
# Nostr protocol questions
cat .claude/agents/nostr-expert/AGENT.md

# BigBrotr development
cat .claude/agents/bigbrotr-expert/AGENT.md
```

Both agents have comprehensive documentation and quick reference files for efficient development.
