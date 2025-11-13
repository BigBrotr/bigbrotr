# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BigBrotr is a modular Nostr data archiving and monitoring system that collects, archives, and analyzes data from the Nostr decentralized social network. The system connects to Nostr relays (servers), archives events (posts/messages), monitors relay health, and provides statistical insights.

## Architecture

The project follows a three-layer architecture:

1. **Core Layer** (`src/core/`): Foundation components - database interface, config management, logging, connection pooling
2. **Service Layer** (`src/services/`): Modular services - initializer, monitor, synchronizer, API (future), DVM (future)
3. **Implementation Layer** (`implementations/bigbrotr/`): Configuration, schemas, deployment specifics

All Nostr protocol operations use the `nostr-tools` library (v1.4.0) - never reimplement protocol functionality.

## Common Development Commands

### Running Services Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Set required environment variables (see service file for full list)
export POSTGRES_HOST=localhost
export POSTGRES_USER=admin
export POSTGRES_PASSWORD=your_password
export POSTGRES_DB=bigbrotr
export POSTGRES_PORT=5432

# Run individual services
python src/services/initializer.py        # Initialize database and seed relays
python src/services/monitor.py            # Monitor relay health
python src/services/synchronizer.py       # Sync events from relays
python src/services/priority_synchronizer.py  # Sync from priority relays
```

### Database Setup

```bash
# Initialize PostgreSQL database with schema
psql -U admin -d bigbrotr < implementations/bigbrotr/config/postgres/init/00_extensions.sql
psql -U admin -d bigbrotr < implementations/bigbrotr/config/postgres/init/01_utility_functions.sql
psql -U admin -d bigbrotr < implementations/bigbrotr/config/postgres/init/02_tables.sql
psql -U admin -d bigbrotr < implementations/bigbrotr/config/postgres/init/03_indexes.sql
psql -U admin -d bigbrotr < implementations/bigbrotr/config/postgres/init/04_integrity_functions.sql
psql -U admin -d bigbrotr < implementations/bigbrotr/config/postgres/init/05_procedures.sql
psql -U admin -d bigbrotr < implementations/bigbrotr/config/postgres/init/06_views.sql
psql -U admin -d bigbrotr < implementations/bigbrotr/config/postgres/init/99_verify.sql
```

### Docker Deployment

```bash
cd implementations/bigbrotr/

# Create .env file with required variables
# Build and run all services
docker-compose up --build

# Run specific service
docker-compose up initializer
docker-compose up monitor
```

## High-Level Architecture

### Database Interface Pattern

The `Brotr` class in `src/core/brotr.py` provides the primary database interface. All services use this pattern:

```python
from brotr import Brotr

# Initialize
db = Brotr(host, user, password, dbname, port)
db.connect()

# Use atomic stored procedures
db.insert_event(event, relay, seen_at)  # Single event
db.insert_event_batch(events, relay)     # Batch events
db.insert_relay_metadata(relay_url, metadata)

# Execute custom queries
result = db.execute("SELECT * FROM relays WHERE is_active = TRUE")
rows = db.fetchall(result)
```

### Service Lifecycle Pattern

All services follow this lifecycle:
1. Load configuration from environment variables
2. Validate configuration parameters
3. Test database connectivity
4. Execute main service logic in loop/batch
5. Handle graceful shutdown on SIGTERM/SIGINT

### Database Schema

Key tables and their relationships:
- `relays`: Registry of all Nostr relays
- `events`: All Nostr events (content stored)
- `events_relays`: Junction table linking events to relays
- `relay_metadata`: Relay capabilities snapshots over time
- `nip11`/`nip66`: Deduplicated relay metadata

Atomic operations via stored procedures:
- `insert_event()`: Insert event + relay association atomically
- `insert_relay()`: Insert/update relay with conflict handling
- `insert_relay_metadata()`: Store metadata with deduplication

Statistics views for read-optimized access:
- `events_statistics`: Global stats with time windows
- `relays_statistics`: Per-relay statistics
- `kind_counts_total/by_relay`: Event type distribution
- `pubkey_counts_total/by_relay`: Author activity

### Service Communication

Services communicate through the PostgreSQL database:
- Monitor service updates relay health status
- Synchronizer reads active relays and writes events
- Future API/DVM services will read from statistics views

No direct inter-service communication - database is the shared state.

### Nostr Protocol Integration

The project uses `nostr-tools` library for ALL protocol operations:

```python
from nostr_tools import (
    Event,                  # Event class with validation
    Relay,                  # Relay URL handling
    Client,                 # WebSocket connections
    Filter,                 # Event filtering
    validate_keypair,       # Keypair validation
    fetch_relay_metadata,   # NIP-11/66 metadata
)
```

Never reimplement: event validation, signature verification, bech32 encoding, WebSocket handling, or relay metadata fetching.

## Implementation Status

### Completed Services
- **Initializer**: Database setup and seed relay loading
- **Monitor**: Relay health monitoring with metadata collection
- **Synchronizer**: Event collection with batching and deduplication
- **Priority Synchronizer**: Optimized sync for priority relays

### Core Components
- **Brotr**: Synchronous PostgreSQL interface with type validation
- **Config**: Environment-based configuration loading
- **Logger**: Structured logging system
- **Pool**: PGBouncer connection pooling support

### In Development
- **API Service**: REST endpoints for statistics (stub)
- **DVM Service**: Nostr-native query interface (stub)
- **Finder Service**: Event discovery service (stub)

### Future Components
- Service base classes in `src/core/services.py`
- Prometheus metrics exposure
- Public data access layer (Phase 3)

## Key Implementation Notes

1. **Environment Variables**: All configuration through environment variables - no hardcoded values
2. **Error Handling**: Services must handle database disconnections and retry with exponential backoff
3. **Batch Operations**: Use batch inserts for events (`insert_event_batch`) when processing multiple items
4. **Tor Support**: Services connecting to .onion relays must use SOCKS5 proxy via `TORPROXY_HOST/PORT`
5. **Multiprocessing**: Monitor and Synchronizer use multiprocessing - respect `NUM_CORES` configuration
6. **Type Validation**: Brotr validates all inputs - don't bypass validation
7. **Stored Procedures**: Use database procedures for atomic operations - don't implement in Python