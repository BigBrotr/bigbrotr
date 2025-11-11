# BigBrotr Project Specification

## Project Overview

**BigBrotr** is a modular, implementation-based Nostr data archiving and monitoring system built on Python. The project follows a flexible architecture where the core source code (`src/`) can be configured through different implementations to create customized Nostr data collection and analysis systems.

### Architecture Philosophy

The project separates core functionality from implementation-specific configurations:
- **Core Code** (`src/`): Reusable components, services, and interfaces
- **Implementations** (`implementations/<name>/`): Custom configurations, parameters, and deployment specifications
- **Extensibility**: New implementations can be created by defining configuration files without modifying core code

## Current Implementation: BigBrotr

The primary implementation focuses on comprehensive data archiving and continuous monitoring of the Nostr network, storing complete event data, relay information, and metadata.

### Alternative Implementation Example: LilBrotr
A future lightweight implementation could archive only essential data (excluding tags and content) with parameters optimized for low-performance hardware, while maintaining the same service architecture.

## Technology Stack

- **Language**: Python 3.9+
- **Database**: PostgreSQL with PGBouncer connection pooling
- **Libraries**:
  - `nostr-tools` (v1.4.0): Comprehensive Nostr protocol implementation
  - `asyncpg`: Async PostgreSQL driver
  - `aiohttp`: Async HTTP client
  - `aiofiles`: Async file operations
  - `prometheus-client`: Metrics and monitoring
- **Infrastructure**: Docker Compose for orchestration
- **Network**: Support for clearnet and Tor (via SOCKS5 proxy)

## Project Structure

```
bigbrotr/
├── implementations/
│   └── bigbrotr/                    # Primary implementation
│       ├── config/
│       │   ├── brotr.yaml           # Core implementation configuration
│       │   ├── pgbouncer/           # Connection pooler configuration
│       │   ├── postgres/            # Database configuration
│       │   │   ├── init/            # Database initialization scripts
│       │   │   └── postgresql.conf  # PostgreSQL configuration
│       │   └── services/            # Service-specific configurations
│       ├── data/                    # Implementation data files
│       │   ├── postgres/            # PostgreSQL data volume
│       │   ├── priority_relays.txt  # High-priority relay list
│       │   └── seed_relays.txt      # Initial relay seed list
│       ├── docker-compose.yaml      # Container orchestration
│       └── .env                     # Sensitive configuration (not in repo)
└── src/
    ├── core/                        # Core components
    │   ├── brotr.py                # Database interface implementation
    │   ├── config.py               # Configuration management
    │   ├── database.py             # Database connection with PGBouncer
    │   ├── log.py                  # Standardized logging
    │   ├── service.py              # Base service classes
    │   └── utils.py                # Shared utilities
    ├── docker/                      # Service Dockerfiles
    └── services/                    # Service implementations
        ├── initializer.py           # Database seeding (mandatory)
        ├── monitor.py               # Relay health monitoring (mandatory)
        ├── synchronizer.py          # Event synchronization (mandatory)
        ├── priority_synchronizer.py # Priority relay sync (alternative)
        ├── api.py                   # REST API (optional, future)
        ├── dvm.py                   # Data vending machine (optional, future)
        └── finder.py                # Event discovery (optional, future)
```

## Core Components

### 1. Database Layer (`src/core/database.py`)

**Purpose**: Provides connection pooling and database access through PGBouncer.

**Requirements**:
- Implement `Database` class with PGBouncer support
- Handle connection pooling efficiently
- Support both sync and async operations
- Provide connection retry logic
- Environment-based configuration

### 2. Brotr Interface (`src/core/brotr.py`)

**Current State**: Contains legacy direct database connection code using `psycopg2`.

**Required Updates**:
- Extend the `Database` class instead of direct connection
- Maintain existing method signatures for backward compatibility
- Add implementation-specific configuration loading from `brotr.yaml`
- Standardize batch operations for performance

**Core Methods** (must be maintained):
- `insert_event()`: Insert single event with relay association
- `insert_event_batch()`: Batch event insertion
- `insert_relay()`: Insert relay information
- `insert_relay_batch()`: Batch relay insertion
- `insert_relay_metadata()`: Insert relay NIP-11/NIP-66 metadata
- `insert_relay_metadata_batch()`: Batch metadata insertion
- `delete_orphan_events()`: Cleanup orphaned records

**Note**: Each implementation provides its own SQL procedures but must implement these standard interfaces.

### 3. Service Base Classes (`src/core/service.py`)

**Purpose**: Provide standardized service lifecycle and capabilities.

**Required Classes**:

#### BaseService
- Configuration acquisition from YAML files
- Logging setup via `src/core/log.py`
- Health and status endpoints
- Graceful startup/shutdown
- Database connection management
- Abstract `run()` method for service logic

#### LoopService (extends BaseService)
- Continuous loop execution
- Configurable intervals
- Error recovery
- Metrics collection

**Key Features**:
- Docker and non-Docker compatibility
- Signal handling for graceful shutdown
- Prometheus metrics integration
- Standardized error handling

### 4. Configuration Management (`src/core/config.py`)

**Purpose**: Centralized configuration loading and validation.

**Requirements**:
- Load from YAML files in `implementations/<name>/config/`
- Environment variable override support
- Configuration validation
- Default value handling
- Sensitive data from `.env` file

### 5. Logging (`src/core/log.py`)

**Purpose**: Standardized logging across all services.

**Requirements**:
- Structured logging format
- Multiple log levels
- Service-specific loggers
- Log rotation support
- JSON output for log aggregation

### 6. Utilities (`src/core/utils.py`)

**Purpose**: Shared helper functions.

**Potential Functions**:
- URL sanitization
- Timestamp utilities
- Retry decorators
- Network helpers
- Data validation

## Database Schema

### Core Tables

#### `relays`
- Primary registry of all Nostr relays
- Tracks URL, network type (clearnet/tor), insertion timestamp

#### `events`
- Complete Nostr event storage
- Includes computed `tagvalues` column for efficient tag searching
- Full event data: id, pubkey, created_at, kind, tags, content, sig

#### `events_relays`
- Junction table for event-relay relationships
- Tracks when events were first seen on specific relays

#### `nip11`
- Deduplicated NIP-11 relay information
- Content-based hashing for deduplication
- One record can be referenced by multiple relay metadata entries

#### `nip66`
- NIP-66 relay test results
- Tracks openability, readability, writability, and RTT metrics
- Content-based deduplication like NIP-11

#### `relay_metadata`
- Snapshots of relay metadata at specific points in time
- References NIP-11 and NIP-66 records
- Tracks connection and metadata fetch success

### Required Views

#### Existing Views
- `relay_metadata_latest`: Latest metadata per relay
- `readable_relays`: Currently readable relays sorted by RTT

#### Missing View (TO BE ADDED)
- **`relay_last_event_timestamp`**: Associates each relay in `events_relays` with the highest event timestamp for that relay
- **Purpose**: Critical for synchronization services to track sync progress per relay
- **Implementation**: Should join `events_relays` with `events` to find max `created_at` per relay

### Stored Procedures

All procedures are defined in `implementations/<name>/config/postgres/init/05_procedures.sql`:
- `insert_event()`: Atomic event+relay+junction insertion
- `insert_relay()`: Relay insertion with conflict handling
- `insert_relay_metadata()`: Metadata insertion with automatic NIP-11/NIP-66 deduplication
- `delete_orphan_events()`: Cleanup function

## Services

### Mandatory Services

#### 1. Initializer Service
**Purpose**: Database initialization and seeding
- Load seed relays from `seed_relays.txt`
- Insert initial relay data
- Verify database connectivity
- Run once at startup

#### 2. Monitor Service
**Purpose**: Continuous relay health monitoring
- Test relay connectivity (NIP-66)
- Fetch relay information (NIP-11)
- Update relay metadata
- Track relay availability over time

#### 3. Synchronizer Service (OR Priority Synchronizer)
**Purpose**: Event collection from relays
- Connect to readable relays
- Subscribe to event streams
- Store events with relay associations
- Track synchronization progress per relay

**Note**: Only one synchronizer type runs per implementation.

### Optional Services (Future Implementation)

#### 4. API Service
- REST API for data access
- Query interface for events
- Relay statistics endpoints
- WebSocket support for real-time updates

#### 5. DVM Service (Data Vending Machine)
- NIP-90 implementation
- Process data requests
- Generate reports and analytics

#### 6. Finder Service
- Advanced event discovery
- Cross-relay event correlation
- Missing event detection

## Configuration Files

### Implementation Configuration (`brotr.yaml`)

Located at: `implementations/<name>/config/brotr.yaml`

Contains:
- Database connection parameters
- Service enable/disable flags
- Performance tuning parameters
- Implementation-specific settings

### Service Configurations

Located at: `implementations/<name>/config/services/<service>.yaml`

Each service has its own YAML configuration with:
- Service-specific parameters
- Scheduling intervals
- Resource limits
- Feature flags

### Environment Variables (`.env`)

Located at: `implementations/<name>/.env`

Contains sensitive data:
- Database credentials
- API keys
- Network proxies
- Security tokens

**Note**: Never commit `.env` files to version control.

## Docker Architecture

### Service Dockerfiles

Each service has a dedicated Dockerfile in `src/docker/`:
- Minimal Alpine-based images
- Service-specific dependencies
- Health check endpoints
- Non-root user execution

### Docker Compose

Main orchestration file: `implementations/<name>/docker-compose.yaml`

Services:
- PostgreSQL database
- PGBouncer connection pooler
- Tor proxy (optional)
- All mandatory services
- Selected optional services

## Implementation Requirements

### Service Update Requirements

All existing services need updates to:
1. Extend appropriate base service class
2. Use new `Brotr` class with PGBouncer
3. Load configuration from YAML files
4. Implement standardized logging
5. Support both Docker and standalone operation

### nostr-tools Integration

**DO NOT REIMPLEMENT** the following (use `nostr-tools` library):
- Event creation, validation, signing
- WebSocket client and relay connections
- Cryptographic operations (key generation, signatures)
- Event filtering and queries
- NIP-11/NIP-66 relay testing
- SOCKS5 proxy support
- Tag management
- Proof-of-work generation

**Focus on implementing**:
- Database persistence layer
- Service orchestration
- Data aggregation and analytics
- Custom business logic
- Monitoring and alerting

## Development Priorities

### Phase 1: Core Infrastructure (Current)
1. ✅ Database schema and procedures
2. 🔄 Implement `Database` class with PGBouncer
3. 🔄 Update `Brotr` class to extend `Database`
4. 🔄 Create base service classes
5. 🔄 Implement configuration management
6. 🔄 Standardize logging

### Phase 2: Service Updates
1. Update Initializer service
2. Update Monitor service
3. Update Synchronizer services
4. Add missing database view for sync progress
5. Test service orchestration

### Phase 3: Optimization
1. Index optimization in database
2. Performance tuning
3. Add metrics collection
4. Implement health checks

### Phase 4: Optional Services
1. Design and implement API service
2. Create DVM service
3. Develop Finder service

## Testing Strategy

### Unit Tests
- Test each core component independently
- Mock database connections
- Validate data transformations

### Integration Tests
- Test service interactions
- Validate database operations
- Check configuration loading

### System Tests
- Full stack deployment testing
- Performance benchmarking
- Network failure scenarios

## Security Considerations

### Database Security
- Use PGBouncer for connection pooling
- Implement connection limits
- Use prepared statements to prevent SQL injection
- Regular security updates

### Network Security
- Support Tor for anonymity
- Validate all relay URLs
- Sanitize all user inputs
- Rate limiting on API endpoints

### Configuration Security
- Sensitive data in `.env` files only
- Proper file permissions
- Secrets management in production
- Audit logging

## Performance Considerations

### Database Optimization
- Batch operations for bulk inserts
- Efficient indexing strategy
- Content-based deduplication for metadata
- Partition large tables if needed

### Service Optimization
- Async operations where possible
- Connection pooling
- Efficient event streaming
- Memory management for large datasets

### Monitoring
- Prometheus metrics integration
- Service health endpoints
- Performance dashboards
- Alert configuration

## Conclusion

BigBrotr provides a flexible, implementation-based architecture for Nostr data collection and analysis. By separating core functionality from implementation-specific configurations, the system can be adapted to various use cases while maintaining code reusability and maintainability. The focus should be on leveraging existing `nostr-tools` functionality while building robust data persistence and service orchestration layers.