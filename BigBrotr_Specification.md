# BigBrotr Project Specification v3.0

## Project Overview

**BigBrotr** is a modular, implementation-based Nostr data archiving and monitoring system built on Python. The project follows a flexible architecture where core source code can be configured through different implementations to create customized Nostr data collection and analysis systems.

### Architecture Philosophy

The project separates concerns into three distinct layers:

1. **Core Layer** (`src/core/`): Reusable foundation components providing database access, configuration management, logging, and service lifecycle management

2. **Implementation Layer** (`implementations/<n>/`): Configuration files, database schemas, deployment specifications, and data files that define how a specific instance behaves

3. **Service Layer** (`src/services/`): Modular services that can be enabled/disabled per implementation, leveraging core components to perform specific tasks

This separation allows:
- Creating new implementations without modifying core code
- Adding new services that automatically benefit from core infrastructure
- Evolving database schemas while maintaining standard interfaces
- Scaling from minimal to comprehensive implementations

**Important Note**: This project is in initial development stage. There is no backward compatibility requirement - the architecture can evolve freely based on implementation experience and emerging requirements.

### Current Implementation: BigBrotr

The primary implementation focuses on comprehensive data archiving of the Nostr network with continuous relay monitoring and event synchronization.

**Alternative Example**: A "LilBrotr" implementation could use minimal database schema (events without content/tags), reduced monitoring frequency, and lower resource requirements while reusing the same core and services.

## Technology Stack

- **Language**: Python 3.9+
- **Database**: PostgreSQL with PGBouncer connection pooling
- **Nostr Protocol Library**: `nostr-tools` 1.4.0 (BigBrotr's Python Nostr library)
- **Core Libraries**:
  - `nostr-tools` (==1.4.0): Complete Nostr protocol implementation with async API
  - `asyncpg`: Async PostgreSQL driver
  - `aiohttp`: Async HTTP client  
  - `aiofiles`: Async file operations
  - `prometheus-client`: Metrics exposure
- **Service Libraries** (future):
  - `fastapi`: REST API framework
  - `slowapi`: Rate limiting
  - Additional libraries TBD based on Phase 3 requirements
- **Infrastructure**: Docker Compose orchestration
- **Network**: Clearnet and Tor support (SOCKS5)

**Note**: Library list is subject to change as development progresses and requirements become clearer.

## nostr-tools Library Integration

### What nostr-tools Provides

BigBrotr leverages `nostr-tools` (v1.4.0), a comprehensive Python library for Nostr protocol that provides:

**✅ Already Implemented in nostr-tools** (DO NOT REIMPLEMENT):

**Key Management**:
- `generate_keypair()`: Generate cryptographically secure keypairs
- `to_bech32(prefix, data)`: Convert hex to bech32 format (nsec/npub)
- `to_hex(bech32_string)`: Convert bech32 to hex
- `validate_keypair(private_key, public_key)`: Validate keypair correspondence

**Event Operations**:
- `Event`: Complete event class with validation
  - `Event.from_dict(data)`: Create from dictionary
  - `event.to_dict()`: Serialize to dictionary
  - `event.is_valid`: Signature validation
  - `event.has_tag(name)`: Tag checking
  - `event.get_tag_values(name)`: Extract tag values
- `generate_event()`: Create and sign events with optional PoW
  - Supports all event kinds (0-65535)
  - Automatic ID generation
  - Automatic signing
  - Optional proof-of-work (target_difficulty parameter)
  - Nonce tag generation for PoW

**Relay Communication**:
- `Relay`: Relay representation with network detection
  - `Relay(url)`: Automatic clearnet/tor detection
  - `relay.is_valid`: URL validation
  - `relay.network`: Network type (clearnet/tor)
- `Client`: Async WebSocket client
  - `Client(relay, timeout, socks5_proxy_url)`: Full connection management
  - `async with client`: Context manager support
  - `client.is_connected`: Connection status
  - `client.active_subscriptions`: Subscription tracking
  - `await client.connect()`: Manual connection
  - `await client.disconnect()`: Clean disconnection
  - `await client.publish(event)`: Event publishing
  - Connection retry logic
  - Automatic reconnection

**Filtering and Subscriptions**:
- `Filter`: Advanced event filtering
  - By kinds, authors, IDs
  - Time ranges (since, until)
  - Tag-based filtering (e, p, t, etc.)
  - Limit parameter
- `fetch_events(client, filter)`: Fetch stored events
- `stream_events(client, filter)`: Real-time event streaming (async generator)

**Relay Testing (NIP-11/NIP-66)**:
- `check_connectivity(client)`: Test relay connection (returns RTT, status)
- `check_readability(client)`: Test read capability (returns RTT, status)
- `check_writability(client, private_key, public_key)`: Test write capability
- `fetch_nip11(client)`: Fetch NIP-11 relay information document
  - Returns object with: name, description, pubkey, contact, supported_nips, software, version
- `fetch_relay_metadata(client, private_key, public_key)`: Comprehensive metadata
  - Returns object with both NIP-11 and NIP-66 data

**Cryptography**:
- secp256k1-based signing and verification
- Automatic signature validation
- Event ID computation
- Secure random number generation

**Network Features**:
- Full async/await API (asyncio-based)
- SOCKS5 proxy support (Tor)
- Configurable timeouts
- Connection pooling (handled internally)
- Automatic error handling

### What BigBrotr Implements

BigBrotr focuses on:
- **Database persistence layer**: Storing events, relays, metadata
- **Service orchestration**: Coordinating multiple services
- **Batch processing**: Efficient bulk operations
- **Statistics computation**: Aggregating network data
- **Configuration management**: YAML-based configuration
- **Service lifecycle**: BaseService, LoopService patterns
- **Connection pooling**: PGBouncer integration
- **Monitoring**: Prometheus metrics
- **Public access**: API and DVM services

## Project Structure

```
bigbrotr/
├── implementations/
│   └── bigbrotr/                    # Primary implementation
│       ├── config/
│       │   ├── core/                # Core component configurations
│       │   │   └── brotr.yaml
│       │   ├── monitoring/          # Observability configurations (future)
│       │   ├── postgres/
│       │   │   ├── init/            # Schema, views, procedures
│       │   │   └── postgresql.conf
│       │   ├── pgbouncer/
│       │   └── services/            # Per-service configurations
│       ├── data/
│       │   ├── postgres/
│       │   ├── seed_relays.txt
│       │   └── priority_relays.txt
│       ├── docker-compose.yaml
│       └── .env                     # Secrets (not in repo)
│
└── src/                             # Core code and services
    ├── core/                        # Foundation components
    │   ├── pool.py                  # Connection pool management
    │   ├── brotr.py                 # Database interface
    │   ├── config.py                # Configuration loading
    │   ├── logger.py                # Logging system
    │   ├── services.py              # Service base classes
    │   └── utils.py                 # Shared utilities
    │
    ├── services/                    # Service implementations
    │   ├── initializer.py           # Database seeding
    │   ├── monitor.py               # Relay health checks
    │   ├── synchronizer.py          # Event collection
    │   ├── priority_synchronizer.py # Priority relay sync
    │   ├── api.py                   # REST API (future)
    │   ├── dvm.py                   # Data vending machine (future)
    │   └── finder.py                # Event discovery (future)
    │
    └── dockerfiles/                 # Service container definitions
```

## Core Data Model

### Primary Entities

BigBrotr tracks four main entities, each with aggregate and potentially specific views:

1. **Events**: Global network event statistics
2. **Kinds**: Event type distribution and statistics  
3. **Relays**: Relay performance and activity metrics
4. **Pubkeys**: Author activity and engagement data

### Statistical Dimensions

Each entity can be analyzed across temporal dimensions:
- **All-time**: Complete historical data
- **30 days**: Recent month activity
- **7 days**: Weekly trends
- **1 day**: Daily activity
- **1 hour**: Real-time metrics

### Data Access Philosophy

The system implements a tiered access model:

**Tier 1 - System Monitoring** (Admin Only):
- Infrastructure health and performance
- Service operational metrics
- Database performance indicators

**Tier 2 - Public Data Access** (Free Access):
- Network-wide aggregates (events, kinds, relays, pubkeys)
- Per-entity statistics (specific kind, relay, or pubkey data)
- Historical trends and growth metrics
- Complete data access via two interfaces:
  - **REST API**: Traditional HTTP requests with JSON responses
  - **DVM (NIP-90)**: Nostr-native queries with event-based responses

Both interfaces provide the same data access, offering users choice in how they consume the information.

**Tier 3 - Paid Access** (Future Consideration):
- Payment mechanisms may be introduced for premium features
- Could include advanced analytics, custom reports, or priority access
- Implementation details to be determined based on operational needs

## Development Phases

### Phase 1: Core Infrastructure (Current Priority)

**Objective**: Build stable, reusable foundation components that integrate with nostr-tools.

**Components**:

1. **Connection Pool** (`pool.py`)
   - PGBouncer integration
   - Connection lifecycle management
   - Async and sync operation support
   - Retry logic and error handling
   - Configuration from YAML

2. **Database Interface** (`brotr.py`)
   - Extends ConnectionPool
   - Standardized data insertion methods
   - Batch operation support
   - Stored procedure invocation
   - Implementation-specific configuration
   - **Uses nostr-tools for**: Event validation, relay URL validation

3. **Service Framework** (`services.py`)
   - BaseService: Common lifecycle (init, run, shutdown)
   - LoopService: Continuous execution with intervals
   - Configuration loading from YAML
   - Logging integration
   - Graceful shutdown handling
   - Health check support

4. **Configuration System** (`config.py`)
   - YAML file parsing
   - Environment variable overrides
   - Validation and defaults
   - Secrets from .env files

5. **Logging System** (`logger.py`)
   - Structured logging format
   - Service-specific loggers
   - Multiple output levels
   - Rotation support

6. **Utilities** (`utils.py`)
   - Helper functions that complement nostr-tools
   - Batch processing utilities
   - Retry decorators
   - Data validation helpers
   - **Note**: Does NOT reimplement nostr-tools functionality

**Success Criteria**:
- All core components tested independently
- Services can extend base classes without reimplementing infrastructure
- Configuration changes don't require code changes
- Clean separation between core and implementation
- Proper integration with nostr-tools library

### Phase 2: Mandatory Services (Second Priority)

**Objective**: Implement essential services for data collection and monitoring using nostr-tools.

**Services**:

1. **Initializer Service**
   - Database initialization
   - Schema verification
   - Seed relay loading
   - One-time execution at startup
   - Status reporting
   - **Uses nostr-tools for**: Relay URL validation

2. **Monitor Service**
   - Relay connectivity testing (NIP-66)
   - Relay information fetching (NIP-11)
   - Metadata persistence
   - Continuous operation
   - Configurable test intervals
   - **Uses nostr-tools for**: 
     - `check_connectivity()`, `check_readability()`, `check_writability()`
     - `fetch_nip11()`, `fetch_relay_metadata()`
     - `Client` for relay connections

3. **Synchronizer Service**
   - Event stream subscription
   - Event validation and storage
   - Relay association tracking
   - Progress monitoring
   - Error recovery
   - **Uses nostr-tools for**:
     - `Client` for WebSocket connections
     - `Filter` for event filtering
     - `stream_events()` for real-time streaming
     - `Event` for event validation

4. **Priority Synchronizer** (Alternative)
   - Focus on high-priority relays
   - Optimized for resource constraints
   - Alternative to full synchronizer
   - **Uses nostr-tools for**: Same as Synchronizer

**Service Design Considerations**:

Each service should:
- Extend BaseService or LoopService
- Load configuration from service-specific YAML
- Use Brotr interface for database operations
- Use nostr-tools for all Nostr protocol operations
- Implement proper error handling
- Support graceful shutdown
- Be independently testable

**Note**: As services are developed, the base service classes may evolve to accommodate common patterns. Consider additional base classes if clear patterns emerge (e.g., MetricsService, APIService, QueryService) but avoid premature abstraction.

### Phase 3: Public Access Layer (Future Priority)

**Objective**: Provide public access to collected data through various interfaces.

**Components Under Consideration**:

1. **Database Views**
   - Entity-based statistics views (events, kinds, relays, pubkeys)
   - Time-windowed aggregations
   - Per-entity specific views (per-kind, per-relay, per-pubkey)
   - Read-only access optimization
   - Query performance tuning

2. **REST API Service**
   - Endpoint structure for all entities
   - Time window parameter support
   - Rate limiting implementation
   - CORS configuration
   - OpenAPI documentation
   - Unified data access (same as DVM)

3. **Data Vending Machine (DVM)**
   - NIP-90 job request handling
   - Nostr-native query interface
   - Same data access as REST API
   - Event-based result formatting
   - Job queue management
   - **Uses nostr-tools for**:
     - `Client` for Nostr connections
     - `Event` for DVM request/response events
     - `generate_event()` for creating responses
     - `Filter` for event subscriptions

4. **Observability Stack**
   - Prometheus metrics collection
   - Grafana visualization dashboards
   - Admin vs public dashboard separation
   - Alert configuration
   - Performance monitoring

**Design Principles**:

- **Dual Interface**: API and DVM provide same data, different access methods
- **API First**: Design clear interfaces before implementation
- **Consistent Data**: Both interfaces query the same underlying views
- **Rate Limiting**: Prevent abuse while keeping access open
- **Future Flexibility**: Payment mechanisms can be added later if needed

**Service Base Class Evolution**:

As Phase 3 progresses, consider introducing:
- **MetricsService**: Base class for services exposing Prometheus metrics
- **HTTPService**: Base class for web-serving services (API, webhooks)
- **QueryService**: Base class for services handling data queries (shared by API and DVM)

These would extend BaseService while adding specific capabilities, avoiding duplication across API and DVM implementations.

## Database Architecture

### Core Tables

**relays**:
- Registry of all Nostr relays
- Fields: id, url, network (clearnet/tor), inserted_at

**events**:
- Complete event storage
- Fields: id, pubkey, created_at, kind, tags, content, sig
- Computed: tagvalues (for efficient tag queries)

**events_relays**:
- Event-relay associations
- Fields: event_id, relay_id, first_seen_at

**relay_metadata**:
- Relay metadata snapshots
- References to NIP-11 and NIP-66 data
- Temporal metadata tracking

**nip11**, **nip66**:
- Deduplicated relay information
- Content-based hashing
- Referenced by relay_metadata

### Views and Procedures

**Views** (implementation-specific):

All views are defined in `implementations/<n>/config/postgres/init/06_views.sql`.

**Relay Metadata Views**:
- `relay_metadata_latest`: Latest metadata snapshot for each relay, joins with NIP-11 and NIP-66 data
  - Provides unified view of most recent relay information
  - Includes all NIP-11 fields (name, description, supported NIPs, etc.)
  - Includes all NIP-66 fields (openable, readable, writable, RTTs)

**Statistics Views**:
- `events_statistics`: Global event statistics with NIP-01 event categories
  - Total counts and unique pubkeys/kinds
  - Breakdown by event type (regular, replaceable, ephemeral, addressable)
  - Time-based metrics (1h, 24h, 7d, 30d, all-time)

- `relays_statistics`: Per-relay statistics with event counts and performance metrics
  - Event counts and unique pubkeys per relay
  - First/last event timestamps
  - Average RTT metrics (last 10 measurements)

**Event Distribution Views**:
- `kind_counts_total`: Event counts by kind across all relays
  - Total events per kind
  - Unique authors per kind

- `kind_counts_by_relay`: Event counts by kind for each relay
  - Detailed kind distribution per relay
  - Unique authors per kind per relay

**Author Activity Views**:
- `pubkey_counts_total`: Event counts by public key across all relays
  - Total events per author
  - Unique kinds used
  - First/last event timestamps

- `pubkey_counts_by_relay`: Event counts by public key for each relay
  - Author activity distribution per relay
  - Kinds used array
  - First/last event timestamps per relay

**Note**: Exact view definitions and schema details are implementation-specific and will evolve during development. The views listed above are from the initial BigBrotr implementation and serve as examples.

**Stored Procedures**:

All procedures are defined in `implementations/<n>/config/postgres/init/05_procedures.sql`:

- `insert_event()`: Atomic event+relay+junction insertion
- `insert_relay()`: Relay insertion with conflict handling
- `insert_relay_metadata()`: Metadata insertion with automatic NIP-11/NIP-66 deduplication
- `delete_orphan_events()`: Cleanup orphaned events with no relay associations
- `delete_orphan_nip11()`: Cleanup orphaned NIP-11 records with no references
- `delete_orphan_nip66()`: Cleanup orphaned NIP-66 records with no references

**Design Philosophy**:
- Views provide read-optimized data access
- Procedures ensure data integrity
- Both are implementation-specific but follow standard interfaces
- Exact schema details determined per implementation needs

### Security Model

**Database Users**:
1. `admin`: Full access for services
2. `readonly_public`: View-only access for public endpoints
3. `readonly_system`: View-only for monitoring tools

Permissions are granted per implementation based on access requirements.

## Configuration Architecture

### Core Configuration

**Location**: `implementations/<n>/config/core/`

Each core component loads its configuration from YAML files:
- `brotr.yaml`: Database interface settings
- Additional configurations as components are developed

**Principles**:
- Sensible defaults in code
- YAML overrides for customization
- Environment variables for secrets
- Validation on load

### Service Configuration

**Location**: `implementations/<n>/config/services/<service>.yaml`

Each service defines:
- Service-specific parameters
- Operation intervals
- Resource limits
- Feature flags
- Endpoint definitions (for HTTP services)

**Example Structure**:
```yaml
service:
  name: monitor
  enabled: true
  
parameters:
  check_interval: 300  # seconds
  timeout: 10
  max_concurrent: 50

nostr_tools:
  socks5_proxy: null  # or socks5://127.0.0.1:9050 for Tor
  timeout: 10

features:
  nip11_fetch: true
  nip66_test: true
```

### Environment Variables

**Location**: `implementations/<n>/.env`

Sensitive configuration:
- Database credentials
- API keys
- Network proxies
- Security tokens

**Never committed to version control.**

## Docker Architecture

### Container Strategy

Each service runs in a dedicated container:
- Minimal base images (Alpine)
- Service-specific dependencies (including nostr-tools)
- Health check endpoints
- Non-root execution
- Graceful shutdown handling

### Orchestration

**docker-compose.yaml** defines:
- All service containers
- PostgreSQL and PGBouncer
- Network configuration (internal/public)
- Volume management
- Environment variables
- Service dependencies

**Network Isolation**:
- Internal network: Core services and database
- Public network: API and DVM services
- Clear separation of concerns

## Service Development Guidelines

### Creating a New Service

1. **Extend Base Class**:
   - Choose BaseService or LoopService
   - Implement abstract `run()` method
   - Call parent `__init__()` with service name

2. **Configuration**:
   - Create YAML file in implementation config
   - Load using `self.config` from base class
   - Document all parameters

3. **Database Access**:
   - Use Brotr interface via `self.brotr`
   - Leverage stored procedures
   - Implement batch operations where possible

4. **Nostr Protocol Operations**:
   - Import from `nostr_tools`
   - Use async/await properly
   - Handle connection errors
   - Never reimplement protocol functionality

5. **Error Handling**:
   - Catch and log exceptions
   - Retry transient failures
   - Graceful degradation when possible
   - Signal health status

6. **Testing**:
   - Unit tests with mocked dependencies
   - Integration tests with test database
   - Docker deployment test

### Service Lifecycle

```
[Config Load] → [Init] → [Connect DB] → [Run] → [Shutdown] → [Cleanup]
```

BaseService handles the lifecycle automatically:
- Configuration loading
- Database connection setup
- Signal handling (SIGTERM, SIGINT)
- Graceful shutdown coordination
- Resource cleanup

Services only implement the `run()` logic.

## Integration with nostr-tools

### How to Use nostr-tools

**Import Statement**:
```python
# Import what you need
from nostr_tools import (
    # Keys
    generate_keypair, to_bech32, to_hex, validate_keypair,
    
    # Events
    Event, generate_event,
    
    # Relay & Client
    Relay, Client,
    
    # Filtering
    Filter,
    
    # Streaming
    fetch_events, stream_events,
    
    # Testing
    check_connectivity, check_readability, check_writability,
    fetch_nip11, fetch_relay_metadata
)
```

**Example Service Integration**:
```python
from nostr_tools import Client, Relay, stream_events, Filter
from src.core.services import LoopService

class Synchronizer(LoopService):
    async def setup(self):
        # Setup nostr-tools client
        relay_url = self.config.get("relay_url")
        self.relay = Relay(relay_url)
        
        proxy = self.config.get("nostr_tools.socks5_proxy")
        timeout = self.config.get("nostr_tools.timeout", 10)
        
        self.client = Client(
            relay=self.relay,
            timeout=timeout,
            socks5_proxy_url=proxy
        )
        
    async def run(self):
        async with self.client:
            # Create filter
            filter_obj = Filter(kinds=[1], limit=100)
            
            # Stream events
            async for event in stream_events(self.client, filter_obj):
                # Validate (automatic in nostr-tools)
                if event.is_valid:
                    # Store in database via Brotr
                    await self.brotr.insert_event(
                        event=event.to_dict(),
                        relay_id=relay_id
                    )
```

### What NOT to Reimplement

**Never reimplement these** (use nostr-tools):
- Event creation, validation, signing
- WebSocket client and relay connections
- Cryptographic operations (key generation, signatures)
- Event filtering and queries
- NIP-11/NIP-66 relay testing
- SOCKS5 proxy support
- Tag management
- Proof-of-work generation
- Event ID computation
- Signature verification
- Bech32 encoding/decoding

### Focus BigBrotr Implementation On

BigBrotr-specific concerns:
- Database persistence layer
- Service orchestration
- Batch processing optimization
- Statistics computation
- Access control
- Monitoring and observability
- Configuration management
- Service lifecycle management

## Testing Strategy

### Unit Testing

**Target**: Individual components in isolation

**Approach**:
- Mock external dependencies (database, nostr-tools network calls)
- Test edge cases and error conditions
- Validate configuration parsing
- Test utility functions

### Integration Testing

**Target**: Component interactions

**Approach**:
- Test database via test container
- Verify service lifecycle
- Test configuration loading from files
- Validate stored procedure calls
- Test nostr-tools integration

### System Testing

**Target**: Full deployment

**Approach**:
- Docker Compose deployment
- End-to-end service operation
- Performance benchmarking
- Network failure scenarios
- Resource constraint testing
- Relay interaction testing

### Test Coverage Goals

- Core components: >90%
- Services: >80%
- Integration scenarios: Critical paths covered

## Security Considerations

### Database Security

- Connection pooling prevents exhaustion attacks
- Prepared statements prevent SQL injection
- Minimal privilege principle for database users
- Encrypted connections (SSL/TLS)
- Regular security updates

### Network Security

- Tor support for relay connections (via nostr-tools)
- URL validation and sanitization (via nostr-tools)
- Input validation on all external data
- Rate limiting on public endpoints
- Network segregation (internal/public)

### Configuration Security

- Secrets in .env files only
- Proper file permissions (600 for secrets)
- No secrets in version control
- Environment-based secret management
- Audit logging for access

## Performance Considerations

### Database Performance

- Batch inserts for bulk operations
- Efficient indexing strategy
- Content-based deduplication
- Connection pooling (PGBouncer)
- Query optimization with EXPLAIN ANALYZE
- Partitioning for large tables (if needed)

### Service Performance

- Async operations (leveraging nostr-tools async API)
- Efficient event streaming
- Memory management for large datasets
- Configurable concurrency limits
- Backpressure handling

### Future Optimization

When implementing public access:
- Response caching strategies
- Database view materialization (if needed)
- Query result pagination
- Connection keep-alive
- Response compression

## Monitoring and Observability

### Current Phase

During core and service development:
- Structured logging to stdout
- Error tracking and reporting
- Basic health checks (database connectivity)
- Service status reporting

### Future Phase

When implementing public access:

**Metrics Collection**:
- Service operational metrics (requests/sec, errors, latency)
- Database performance metrics
- System resource metrics
- Business metrics (events/sec, relay counts)

**Visualization**:
- Admin dashboards (system health, service status)
- Public dashboards (network statistics)
- Alert configuration
- Performance trending

**Tools Under Consideration**:
- Prometheus for metrics
- Grafana for visualization
- PostgreSQL exporter for DB metrics
- Custom metric exporters per service

**Implementation Note**: Metrics collection should be:
- Optional per implementation
- Minimal performance impact
- Consistent across services
- Based on common base class (MetricsService, to be defined)

## Implementation Strategy

### Starting a New Implementation

1. **Copy Template** (when available):
   - Copy `implementations/template/` to `implementations/<n>/`
   - Rename and customize configuration files

2. **Define Schema**:
   - Modify `config/postgres/init/` scripts
   - Adjust views and procedures for use case
   - Maintain standard interface contracts

3. **Configure Services**:
   - Enable/disable services in docker-compose
   - Adjust service parameters in YAML files
   - Set resource limits

4. **Deploy**:
   - Create `.env` file with secrets
   - Run `docker-compose up`
   - Monitor initialization logs

### Customization Levels

1. **Configuration Only**: Change YAML parameters, no code changes
2. **Schema Extension**: Add tables/views while maintaining standard interfaces
3. **Service Selection**: Enable only needed services
4. **Custom Services**: Add implementation-specific services extending base classes

## Development Workflow

### Phase 1 Workflow (Current)

1. Implement core component
2. Write unit tests
3. Update this specification if design evolves
4. Create integration tests
5. Document configuration options
6. Move to next component

**Current Checklist**:
- [ ] ConnectionPool class (with PGBouncer support)
- [ ] Brotr interface (extending ConnectionPool, integrating nostr-tools)
- [ ] BaseService class
- [ ] LoopService class
- [ ] Configuration management
- [ ] Logging system
- [ ] Utilities

**Note**: Database schema and procedures are already complete (✅).

### Phase 2 Workflow (Next)

1. Design service interface
2. Create service configuration YAML template
3. Implement service extending base class
4. Integrate nostr-tools for protocol operations
5. Test with core infrastructure
6. Deploy in docker-compose
7. Validate end-to-end operation
8. Document service behavior

**Service Checklist**:
- [ ] Initializer
- [ ] Monitor
- [ ] Synchronizer
- [ ] Priority Synchronizer

### Phase 3 Workflow (Future)

1. Design data access layer (views)
2. Define API/DVM interface
3. Evaluate need for new base classes
4. Implement access services (using nostr-tools for DVM)
5. Add observability
6. Performance testing
7. Security audit
8. Documentation

**Access Layer Checklist**:
- [ ] Database views finalized (all entities: events, kinds, relays, pubkeys)
- [ ] REST API service (all data accessible)
- [ ] DVM service (same data via Nostr protocol using nostr-tools)
- [ ] Monitoring stack
- [ ] Public dashboards
- [ ] Rate limiting (prevent abuse)

### Future: Implementation Template

After all phases are complete and the system is stable, create:
1. `implementations/template/` directory structure
2. Comprehensive README files and guides
3. Template configuration files
4. Implementation creation documentation

**Important**: The template should be created only after core components, services, and public access layers are fully implemented, tested, and stabilized. This ensures the template reflects complete, working examples and best practices learned during development.

## Documentation Requirements

### Code Documentation

- Docstrings for all classes and public methods
- Type hints throughout
- Inline comments for complex logic
- README in each major directory

### Configuration Documentation

- YAML schema documentation
- Parameter descriptions
- Default values and ranges
- Examples for common scenarios

### Deployment Documentation

- Prerequisites and dependencies
- Installation steps
- Configuration guide
- Troubleshooting common issues
- Security best practices

### API Documentation (Future)

- OpenAPI/Swagger specification
- Example requests and responses
- Authentication details
- Rate limiting information
- Error codes and handling

## Project Principles

### 1. Separation of Concerns

Core, implementation, and services are independent layers. Changes in one layer minimize impact on others.

### 2. Configuration Over Code

New implementations should rarely require code changes. Configuration files drive behavior.

### 3. Leverage Libraries

Use `nostr-tools` for all protocol operations. Don't reimplement standard functionality.

### 4. Fail Gracefully

Services should handle failures without crashing. Log errors, retry when appropriate, degrade gracefully.

### 5. Test Thoroughly

Every component should have tests. Integration tests verify component interactions.

### 6. Document Everything

Code, configurations, and decisions should be documented. Future maintainers (including future you) will thank you.

### 7. Keep It Simple

Avoid premature optimization. Build what's needed, refactor when patterns emerge. Don't over-engineer.

### 8. Evolve Iteratively

Complete Phase 1 before Phase 2. Let real usage inform design decisions. This specification is a living document.

## Future Considerations

### Potential Base Class Extensions

As Phase 3 progresses, consider these base classes if patterns emerge:

- **MetricsService**: Standardized Prometheus metric exposure
- **HTTPService**: Common HTTP server setup, health endpoints, graceful shutdown
- **QueryService**: Common query handling, parameter validation, result formatting (shared by API and DVM)
- **ScheduledService**: Cron-like scheduling (alternative to LoopService)

**Decision Criteria**:
- Multiple services need the same functionality
- Significant code duplication exists
- Clear abstraction boundary
- Doesn't add complexity for simple use cases

### Scalability Enhancements

When data volume grows:
- Database replication (read replicas)
- Table partitioning by time
- Event archival strategies
- Materialized view refresh strategies
- Horizontal service scaling

### Additional Features

Long-term possibilities:
- Multi-relay search queries
- Event correlation analysis
- Network topology mapping
- Relay recommendation system
- Historical data export
- Custom alert configurations

## Conclusion

BigBrotr is designed as a flexible foundation for Nostr data archiving with a clear development path:

**Phase 1** builds robust core infrastructure that integrates with nostr-tools for protocol operations.

**Phase 2** implements essential data collection services using that infrastructure and nostr-tools.

**Phase 3** adds public access layers, observability, and analytics.

This phased approach ensures:
- Stable foundation before building higher layers
- Proper integration with battle-tested nostr-tools library
- Real usage informs design decisions
- Iterative refinement based on experience
- Clear priorities and milestones

The specification is intentionally flexible in later phases, as experience from Phase 1 and Phase 2 will inform optimal approaches for Phase 3. Design decisions should be made with available information, validated with testing, and refined based on results.

**Focus on building solid fundamentals first, leveraging nostr-tools for all protocol operations, then extend thoughtfully based on actual needs.**
