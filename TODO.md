# 📋 Project Tasks - October 29, 2025

## 🔴 HIGH Priority (Urgent)

- [ ] **[Critical Bug]** Fix inverted connection state validation in process_relay.py
  - File: [src/process_relay.py](src/process_relay.py) (lines 154-156)
  - Reason: Logic checks if connections exist and raises error, preventing function from working
  - Impact: Function cannot operate correctly, will always fail when connections exist
  - Effort: S
  - Suggested solution: Remove these validation checks since async context managers handle connection lifecycle

- [ ] **[Critical Bug]** Replace private attribute access in monitor.py
  - File: [src/monitor.py](src/monitor.py) (line 180)
  - Reason: Accessing `pool._pool` internal implementation detail
  - Impact: Code will break with multiprocessing library updates
  - Effort: M
  - Suggested solution: Track worker processes separately or use public API methods

- [ ] **[Critical Bug]** Fix race condition with global service_ready variable
  - Files: [src/monitor.py](src/monitor.py), [src/synchronizer.py](src/synchronizer.py), [src/priority_synchronizer.py](src/priority_synchronizer.py)
  - Reason: Module-level boolean modified across async contexts without synchronization
  - Impact: Health check endpoints may return inconsistent results during startup/shutdown
  - Effort: M
  - Suggested solution: Use `asyncio.Event()` instead of plain boolean

- [ ] **[Critical Bug]** Add connection pool acquisition timeout handling
  - File: [src/bigbrotr.py](src/bigbrotr.py) (lines 65-74, 109, 120, 131)
  - Reason: `pool.acquire()` can hang indefinitely if pool is exhausted
  - Impact: Services can deadlock if connection pool is exhausted
  - Effort: M
  - Suggested solution: Add explicit timeout parameter to pool.acquire() calls

- [ ] **[Critical Bug]** Decide on incomplete Finder service
  - File: [src/finder.py](src/finder.py) (lines 56-68)
  - Reason: Service has TODO comments and no actual implementation
  - Impact: Relay discovery functionality is non-functional
  - Effort: XL (to implement) or S (to remove)
  - Suggested solution: Either fully implement or remove service to avoid confusion

- [ ] **[Functional]** Add network partition error handling
  - Files: All service files
  - Reason: No handling for database becoming temporarily unavailable after initial connection
  - Impact: Services may crash instead of retrying or entering degraded mode
  - Effort: L
  - Suggested solution: Add connection health checks and automatic reconnection logic

- [ ] **[Functional]** Implement rate limiting for relay connections
  - Files: [src/monitor.py](src/monitor.py), [src/synchronizer.py](src/synchronizer.py), [src/priority_synchronizer.py](src/priority_synchronizer.py)
  - Reason: No rate limiting when connecting to external relays
  - Impact: Services could be blocked by relay operators for excessive requests
  - Effort: M
  - Suggested solution: Implement token bucket or leaky bucket rate limiting per relay

- [ ] **[Functional]** Enhance environment variable validation
  - File: [src/config.py](src/config.py)
  - Reason: Missing checks for empty strings, URL formats, robust JSON validation
  - Impact: Configuration errors may only surface at runtime
  - Effort: M
  - Suggested solution: Add comprehensive validation with descriptive error messages

- [ ] **[Functional]** Add pagination for large relay lists
  - File: [src/relay_loader.py](src/relay_loader.py) (lines 28-99, 137-166, 169-215)
  - Reason: All database queries fetch entire result sets into memory
  - Impact: High memory usage, potential OOM on large datasets (thousands of relays)
  - Effort: M
  - Suggested solution: Implement cursor-based pagination for relay fetching

- [ ] **[Code Quality]** Eliminate code duplication between synchronizers
  - Files: [src/synchronizer.py](src/synchronizer.py) and [src/priority_synchronizer.py](src/priority_synchronizer.py)
  - Reason: 265 lines of nearly identical code (95% duplication)
  - Impact: Maintenance nightmare, bug fixes must be applied twice
  - Effort: L
  - Suggested solution: Extract common synchronizer logic to shared base class or function

- [ ] **[Code Quality]** Split God Object: Bigbrotr class
  - File: [src/bigbrotr.py](src/bigbrotr.py) (lines 9-457)
  - Reason: Single 457-line class handles connection pooling, events, relays, and metadata (SRP violation)
  - Impact: Difficult to test, understand, and modify
  - Effort: XL
  - Suggested solution: Split into ConnectionManager, EventRepository, RelayRepository, MetadataRepository

- [ ] **[Performance]** Fix N+1 query pattern in get_start_time_async
  - File: [src/process_relay.py](src/process_relay.py) (lines 11-66)
  - Reason: Three sequential queries instead of one JOIN query
  - Impact: 3x database round trips per relay sync operation
  - Effort: M
  - Suggested solution: Use single JOIN query to get result in one round trip

- [ ] **[Readability]** Add module-level docstrings to all files
  - Files: All Python files in src/
  - Reason: No module-level docstrings explaining purpose, dependencies, or usage
  - Impact: New developers must read entire file to understand purpose
  - Effort: M
  - Suggested solution: Add comprehensive module docstrings at top of each file

- [ ] **[Readability]** Refactor complex process_relay function
  - File: [src/process_relay.py](src/process_relay.py) (lines 145-218)
  - Reason: 74-line function with cyclomatic complexity >15, handles entire binary search algorithm
  - Impact: Very difficult to test individual branches, high cognitive load
  - Effort: L
  - Suggested solution: Extract subfunctions: `handle_empty_batch`, `handle_full_batch`, `verify_relay_behavior`

- [ ] **[Architecture]** Reduce tight coupling to database schema
  - Files: [src/bigbrotr.py](src/bigbrotr.py), [src/relay_loader.py](src/relay_loader.py), [src/process_relay.py](src/process_relay.py)
  - Reason: SQL queries embedded in application code, schema changes require code changes
  - Impact: Difficult to evolve schema, no abstraction layer
  - Effort: XL
  - Suggested solution: Implement repository pattern or use ORM (SQLAlchemy) for schema abstraction

- [ ] **[Architecture]** Separate business logic from infrastructure
  - Files: All service files
  - Reason: Services mix business logic (what to process) with infrastructure (how to process)
  - Impact: Difficult to test business logic in isolation
  - Effort: XL
  - Suggested solution: Apply hexagonal/clean architecture, separate domain logic from adapters

- [ ] **[Architecture]** Centralize configuration management
  - File: [src/config.py](src/config.py)
  - Reason: Each service has separate config loader with many shared keys, no global validation
  - Impact: Duplication, easy to forget validating new keys
  - Effort: L
  - Suggested solution: Create BaseConfig class with shared validation, service-specific configs extend it

- [ ] **[Architecture]** Implement dependency injection
  - Files: All service files
  - Reason: Services create their own dependencies (database connections, clients)
  - Impact: Difficult to test with mocks, tight coupling
  - Effort: XL
  - Suggested solution: Use dependency injection container or factory pattern

- [ ] **[Cleanup]** Remove unused pandas dependency
  - File: [requirements.txt](requirements.txt) (line 6)
  - Reason: pandas is never imported or used anywhere in codebase
  - Impact: Unnecessary dependency, bloated Docker images (+100MB)
  - Effort: S
  - Suggested solution: Remove pandas from requirements.txt

- [ ] **[Testing]** Set up test infrastructure
  - Reason: Absolutely no test files exist in repository
  - Impact: No automated verification of correctness, high regression risk
  - Effort: XL
  - Suggested solution: Add pytest as dev dependency, create test structure: `tests/unit/`, `tests/integration/`, `tests/e2e/`, target 80%+ coverage

- [ ] **[Testing]** Add CI/CD pipeline
  - Reason: No GitHub Actions, Travis, or similar CI configuration
  - Impact: No automated testing on PR/commit
  - Effort: M
  - Suggested solution: Add GitHub Actions workflow for lint, type-check, test

- [ ] **[Refactoring]** Extract RelayProcessor base class
  - Files: [src/synchronizer.py](src/synchronizer.py), [src/priority_synchronizer.py](src/priority_synchronizer.py)
  - Reason: 95% code duplication between two services
  - Impact: Single point of maintenance, easier to add new processor types
  - Effort: L
  - Suggested solution: Create abstract BaseRelayProcessor with template method pattern

- [ ] **[Refactoring]** Introduce repository pattern
  - Files: All service files with database access
  - Reason: SQL scattered through service files
  - Impact: Testable business logic, centralized query optimization, easier to switch databases
  - Effort: XL
  - Suggested solution: Create EventRepository, RelayRepository, MetadataRepository classes

## 🟠 MEDIUM Priority (Important)

- [ ] **[Bug]** Review SQL injection risk in query construction
  - File: [src/relay_loader.py](src/relay_loader.py) (lines 52-79)
  - Reason: While using parameterized queries (safe), string concatenation for conditions could introduce issues if modified
  - Impact: Low immediate risk, but maintenance hazard
  - Effort: S

- [ ] **[Bug]** Add safe asyncpg.Record indexing
  - File: [src/process_relay.py](src/process_relay.py) (lines 28, 41, 53)
  - Reason: Direct indexing without checking if result has expected structure
  - Impact: Could raise IndexError if database schema changes
  - Effort: S

- [ ] **[Functional]** Implement relay reputation tracking
  - File: [src/process_relay.py](src/process_relay.py) (lines 186-191)
  - Reason: Binary search detects misbehaving relays but only logs warning
  - Impact: No systematic tracking of unreliable relays
  - Effort: L

- [ ] **[Functional]** Add cleanup for stale relays
  - Reason: System has insert operations but no cleanup for permanently offline relays
  - Impact: Database grows with dead entries, queries become slower
  - Effort: M

- [ ] **[Functional]** Implement graceful degradation for Tor proxy failure
  - Files: [src/monitor.py](src/monitor.py), [src/synchronizer.py](src/synchronizer.py)
  - Reason: If Tor proxy fails after startup, .onion relay processing fails completely
  - Impact: Complete service failure instead of partial operation for clearnet relays
  - Effort: M

- [ ] **[Functional]** Add per-relay retry logic for metadata fetches
  - File: [src/monitor.py](src/monitor.py) (lines 76-96)
  - Reason: Single failure logs error but doesn't retry, even for transient failures
  - Impact: Missed metadata updates due to temporary issues
  - Effort: M

- [ ] **[Functional]** Strengthen event filter validation
  - File: [src/config.py](src/config.py) (lines 111-115)
  - Reason: Doesn't validate filter value types or ranges for ids/authors/kinds
  - Impact: Invalid filter configurations could cause runtime errors in nostr-tools
  - Effort: S

- [ ] **[Functional]** Enhance health check endpoints with metrics
  - File: [src/healthcheck.py](src/healthcheck.py)
  - Reason: Binary OK/NOT READY response, no metrics (queue size, last success time, error counts)
  - Impact: Limited observability for debugging
  - Effort: M

- [ ] **[Code Quality]** Deduplicate worker functions
  - Files: [src/synchronizer.py](src/synchronizer.py) (lines 43-152), [src/priority_synchronizer.py](src/priority_synchronizer.py) (lines 44-153)
  - Reason: Identical functions except for logging messages
  - Impact: Code duplication increases maintenance burden
  - Effort: M

- [ ] **[Code Quality]** Simplify wait-for-services configuration logic
  - File: [src/functions.py](src/functions.py) (lines 201-251)
  - Reason: Complex key fallback logic repeated multiple times
  - Impact: Error-prone, keys must be synchronized across codebase
  - Effort: M

- [ ] **[Code Quality]** Standardize error handling patterns
  - Files: Multiple
  - Reason: Mix of broad `except Exception`, specific exceptions, silent swallowing
  - Impact: Inconsistent error diagnostics and recovery behavior
  - Effort: L

- [ ] **[Code Quality]** Extract magic numbers to constants
  - Files: Multiple ([src/monitor.py](src/monitor.py):179-183, [src/functions.py](src/functions.py):105-108, [src/process_relay.py](src/process_relay.py):16-62)
  - Reason: Timeout values, retry attempts, delays hardcoded throughout
  - Impact: Unclear intent, difficult to tune behavior
  - Effort: S

- [ ] **[Code Quality]** Standardize naming conventions
  - Files: Multiple
  - Reason: Mix of `relay_inserted_at` vs `inserted_at`, verbose vs terse names
  - Impact: Cognitive load, harder to grep/search
  - Effort: M

- [ ] **[Code Quality]** Add comprehensive type hints
  - Files: [src/functions.py](src/functions.py) (line 86), [src/process_relay.py](src/process_relay.py)
  - Reason: Missing type hints in several places, unused imports
  - Impact: Reduced IDE support and type checking effectiveness
  - Effort: M

- [ ] **[Code Quality]** Simplify nested conditionals in process_relay
  - File: [src/process_relay.py](src/process_relay.py) (lines 166-218)
  - Reason: 4+ levels of nesting with complex branching logic
  - Impact: Hard to test, understand, and maintain
  - Effort: L

- [ ] **[Code Quality]** Add enums for status/network types
  - Files: Multiple
  - Reason: Hardcoded strings like "tor", "clearnet" scattered through code
  - Impact: Typo-prone, no central definition
  - Effort: S

- [ ] **[Performance]** Optimize relay shuffling with database ORDER BY RANDOM()
  - File: [src/relay_loader.py](src/relay_loader.py) (lines 98, 133)
  - Reason: Fetches all relays then shuffles in Python
  - Impact: Unnecessary memory allocation and CPU for large relay lists
  - Effort: S

- [ ] **[Performance]** Reuse connection pools in relay loaders
  - File: [src/relay_loader.py](src/relay_loader.py) (lines 83, 152, 202)
  - Reason: Creates new Bigbrotr instance (connection pool) for each function call
  - Impact: Connection overhead, unnecessary pool creation/destruction
  - Effort: M

- [ ] **[Performance]** Replace synchronous file I/O with aiofiles
  - File: [src/initializer.py](src/initializer.py) (lines 22-23)
  - Reason: Using blocking file I/O in async function
  - Impact: Blocks event loop during file read
  - Effort: S

- [ ] **[Performance]** Add batch size limits to prevent OOM
  - File: [src/bigbrotr.py](src/bigbrotr.py) (lines 188-248)
  - Reason: No limit on batch size, could cause OOM or exceed PostgreSQL parameter limits
  - Impact: Service crashes on very large batches
  - Effort: M

- [ ] **[Performance]** Cache JSONB serialization results
  - File: [src/bigbrotr.py](src/bigbrotr.py) (lines 179, 239, 367-375, 439-449)
  - Reason: Tags serialized to JSON on every insert, even for identical structures
  - Impact: CPU overhead for repeated serialization
  - Effort: M

- [ ] **[Performance]** Convert priority_relay_urls list to set
  - File: [src/synchronizer.py](src/synchronizer.py) (lines 179, 189-191)
  - Reason: O(n*m) complexity checking each relay against list
  - Impact: Slow for large relay lists
  - Effort: S

- [ ] **[Performance]** Use generators for event batch filtering
  - File: [src/process_relay.py](src/process_relay.py) (lines 206-210)
  - Reason: List comprehension creates new list unnecessarily
  - Impact: Extra memory allocation and iteration
  - Effort: S

- [ ] **[Readability]** Improve variable names in binary search
  - File: [src/process_relay.py](src/process_relay.py) (lines 169, 184, 202)
  - Reason: `first_batch`, `second_batch`, `third_batch` don't convey semantic meaning
  - Impact: Hard to understand algorithm flow
  - Effort: S

- [ ] **[Readability]** Use keyword arguments for boolean flags
  - File: [src/config.py](src/config.py)
  - Reason: Call sites unclear: `fetch_relays_from_database(config, 12, True, True)`
  - Impact: Reduced readability at call sites
  - Effort: S

- [ ] **[Readability]** Reduce parameter list length
  - File: [src/bigbrotr.py](src/bigbrotr.py) (SQL functions with 25+ parameters)
  - Reason: Functions have excessive parameters (25 in insert_relay_metadata)
  - Impact: Error-prone, hard to remember parameter order
  - Effort: M (Python wrapper already uses objects, SQL function is legacy)

- [ ] **[Cleanup]** Remove unused import: setup_logging
  - File: [src/process_relay.py](src/process_relay.py) (line 8)
  - Reason: Import exists but function never called
  - Impact: Dead import, confusing for readers
  - Effort: S

- [ ] **[Cleanup]** Resolve or remove TODO comments
  - File: [src/finder.py](src/finder.py) (lines 56-68)
  - Reason: Large block of TODO comments with no implementation plan
  - Impact: Unclear ownership and timeline for implementation
  - Effort: S (to track) or XL (to implement)

- [ ] **[Cleanup]** Remove outdated comment in priority_synchronizer
  - File: [src/priority_synchronizer.py](src/priority_synchronizer.py) (line 37)
  - Reason: Comment says "No global needed" but global service_ready exists
  - Impact: Misleading comment
  - Effort: S

- [ ] **[Cleanup]** Deprecate legacy configuration keys
  - File: [src/relay_loader.py](src/relay_loader.py) (lines 11-25)
  - Reason: Supports both `database_host` and `dbhost` for backward compatibility
  - Impact: Maintenance burden, unclear which keys are canonical
  - Effort: M

- [ ] **[Cleanup]** Remove commented finder service from docker-compose
  - File: [docker-compose.yml](docker-compose.yml) (lines 95-123)
  - Reason: Entire service definition commented out
  - Impact: Git history pollution, unclear service status
  - Effort: S

- [ ] **[Refactoring]** Create configuration validator class
  - File: [src/config.py](src/config.py)
  - Reason: Configuration validation logic scattered and repetitive
  - Impact: Reusable, testable, clear validation rules
  - Effort: M

- [ ] **[Refactoring]** Implement RelaySelector strategy pattern
  - Files: [src/relay_loader.py](src/relay_loader.py)
  - Reason: Different relay selection logic scattered (database, file, needing metadata)
  - Impact: Extensible, testable, clear separation of concerns
  - Effort: M

- [ ] **[Refactoring]** Add circuit breaker pattern for relay connections
  - Files: Service files
  - Reason: No protection against cascading failures when relays are down
  - Impact: Fast-fail for known bad relays, automatic recovery attempts
  - Effort: M

- [ ] **[Refactoring]** Use dataclasses for configuration
  - File: [src/config.py](src/config.py)
  - Reason: Dict-based configuration passed around without type safety
  - Impact: Type safety, IDE autocomplete, validation at construction
  - Effort: M

- [ ] **[Refactoring]** Extract binary search to algorithm class
  - File: [src/process_relay.py](src/process_relay.py)
  - Reason: Complex algorithm embedded in service logic
  - Impact: Testable in isolation, reusable, clear responsibility
  - Effort: L

- [ ] **[Testing]** Add load testing for connection pooling
  - Reason: Connection pool sizing not validated under load
  - Impact: Unknown behavior under stress
  - Effort: M

- [ ] **[Testing]** Add property-based tests for binary search
  - File: [src/process_relay.py](src/process_relay.py)
  - Reason: Complex algorithm with many edge cases
  - Impact: Better coverage of edge cases
  - Effort: L

- [ ] **[Testing]** Add stress testing for concurrency
  - Reason: Race conditions and deadlocks may only appear under heavy load
  - Impact: Unknown behavior in production scenarios
  - Effort: L

- [ ] **[Security]** Add input sanitization for relay URLs
  - Files: Multiple relay loading functions
  - Reason: Relay URLs from database/files not sanitized before use
  - Impact: Potential SSRF attacks if URLs point to internal resources
  - Effort: M

- [ ] **[Security]** Sanitize error messages to prevent secret leakage
  - File: [src/config.py](src/config.py)
  - Reason: Validation errors might leak environment variable values
  - Impact: Potential secret leakage in logs
  - Effort: S

- [ ] **[Security]** Implement query rate limiting
  - Reason: No protection against DOS via expensive queries
  - Impact: Single misconfigured service could overwhelm database
  - Effort: M

- [ ] **[Security]** Review and harden PostgreSQL configuration
  - File: docker-compose.yml references POSTGRES_CONFIG_PATH
  - Reason: Custom PostgreSQL configuration not in repository
  - Impact: Unknown security posture of database
  - Effort: M

## 🟡 LOW Priority (Nice to have)

- [ ] **[Code Quality]** Make emoji usage in logs configurable
  - Files: All service files
  - Reason: Emojis can cause issues with log parsing tools, terminal encoding
  - Impact: Potential log processing issues in production
  - Effort: S

- [ ] **[Code Quality]** Add enums for network types
  - Files: Multiple
  - Reason: Hardcoded "tor" and "clearnet" strings
  - Impact: Type safety, prevent typos
  - Effort: S

- [ ] **[Performance]** Implement query result caching
  - Reason: Frequently accessed data like relay metadata fetched repeatedly
  - Impact: Unnecessary database load for read-heavy operations
  - Effort: L

- [ ] **[Readability]** Standardize comment styles
  - Files: Multiple
  - Reason: Mix of block comments, docstrings, inline comments
  - Impact: Visual inconsistency
  - Effort: S

- [ ] **[Readability]** Add examples to docstrings
  - Files: All
  - Reason: Docstrings explain parameters but don't show usage examples
  - Impact: Higher learning curve for API usage
  - Effort: M

- [ ] **[Readability]** Improve constant naming
  - File: [src/constants.py](src/constants.py) (lines 4-5)
  - Reason: `DB_POOL_MIN_SIZE_PER_WORKER` unclear it's for worker processes
  - Impact: Could be confused with main process pool size
  - Effort: S

- [ ] **[Readability]** Adjust logging verbosity levels
  - Files: All service files
  - Reason: Logs every step including routine operations, could flood logs
  - Impact: Log noise, harder to find important messages
  - Effort: M

- [ ] **[Readability]** Add LOG_LEVEL environment variable
  - File: [src/logging_config.py](src/logging_config.py)
  - Reason: Hard-coded log level, no environment-specific configuration
  - Impact: Can't easily adjust verbosity without code changes
  - Effort: S

- [ ] **[Architecture]** Add plugin architecture for relay discovery
  - Reason: Finder service is stub, no extensible way to add discovery methods
  - Impact: Limited to one discovery approach
  - Effort: L

- [ ] **[Architecture]** Create REST/GraphQL API for data access
  - Reason: No HTTP API for querying archived data, only raw database access
  - Impact: External integrations require direct database access
  - Effort: XL

- [ ] **[Cleanup]** Remove or implement unused SQL functions
  - File: [init.sql](init.sql) (lines 374-414)
  - Reason: `delete_orphan_nip11/nip66` functions defined but never called
  - Impact: Dead code in database
  - Effort: S

- [ ] **[Cleanup]** Verify .gitignore completeness
  - Reason: Ensure `__pycache__`, `*.pyc`, `.pytest_cache` are ignored
  - Impact: Could commit cache files accidentally
  - Effort: S

- [ ] **[Refactoring]** Add query builder pattern
  - Files: Database query code
  - Reason: Repetitive query construction logic
  - Impact: Type-safe queries, reusable filters, clearer intent
  - Effort: L

- [ ] **[Refactoring]** Create standardized HealthCheck interface
  - Files: All service files
  - Reason: Health check implementation varies slightly across services
  - Impact: Consistent health reporting, easier monitoring integration
  - Effort: S

## 📊 Statistics

- **Total tasks:** 78
- **Critical tasks:** 5
- **High priority:** 23
- **Medium priority:** 44
- **Low priority:** 11
- **Lines of code analyzed:** ~3,150
- **Files involved:** 15+ (Python, SQL, Docker)
- **Estimated total effort:** 35-40 person-weeks

### Issue Distribution by Category
- Code Quality: 14 issues (18%)
- Performance: 11 issues (14%)
- Architecture: 9 issues (12%)
- Functional Improvements: 10 issues (13%)
- Refactoring: 10 issues (13%)
- Readability: 10 issues (13%)
- Critical Bugs: 7 issues (9%)
- Cleanup: 7 issues (9%)

### Technical Debt Estimate
- **High-priority items:** ~8-10 person-weeks
- **Medium-priority items:** ~15-18 person-weeks
- **Low-priority items:** ~8-10 person-weeks

## 🎯 Quick Wins (fast tasks with high impact)

High-impact tasks that can be completed quickly (< 2 hours each):

- [ ] Remove unused pandas dependency (15 min) - saves 100MB in Docker images
- [ ] Remove unused import: setup_logging from process_relay.py (5 min)
- [ ] Fix inverted connection validation in process_relay.py (30 min)
- [ ] Extract magic numbers to constants.py (1 hour)
- [ ] Convert priority_relay_urls list to set for O(1) lookup (15 min)
- [ ] Use keyword arguments for boolean flags (1 hour)
- [ ] Optimize relay shuffling with SQL ORDER BY RANDOM() (30 min)
- [ ] Replace synchronous file I/O with aiofiles (30 min)
- [ ] Add enums for network types (30 min)
- [ ] Remove commented finder service from docker-compose.yml (5 min)
- [ ] Fix outdated comments and misleading documentation (30 min)

**Total estimated effort for quick wins:** ~6 hours
**Impact:** Reduced Docker image size, improved performance, better code clarity

## 📁 Proposed File/Folder Reorganization

### Current Structure Issues
- Flat `src/` directory with 13 modules
- No clear separation between domain, application, and infrastructure layers
- Service entry points mixed with utility functions

### Proposed Structure

```
src/
├── domain/                    # Business logic and entities
│   ├── models/
│   │   ├── event.py          # Event domain model
│   │   ├── relay.py          # Relay domain model
│   │   └── metadata.py       # Metadata models
│   └── services/
│       └── sync_algorithm.py # Binary search algorithm (pure logic)
│
├── application/               # Application services and use cases
│   ├── services/
│   │   ├── monitor_service.py
│   │   ├── sync_service.py
│   │   └── finder_service.py
│   └── config/
│       ├── base_config.py    # Shared configuration
│       ├── monitor_config.py
│       └── sync_config.py
│
├── infrastructure/            # External interfaces and implementations
│   ├── database/
│   │   ├── connection.py     # Connection management (extracted from bigbrotr.py)
│   │   ├── repositories/
│   │   │   ├── event_repository.py
│   │   │   ├── relay_repository.py
│   │   │   └── metadata_repository.py
│   │   └── queries/
│   │       └── relay_queries.py
│   ├── nostr/
│   │   └── client_wrapper.py # Nostr client abstraction
│   └── health/
│       └── health_check.py   # Health check server
│
├── workers/                   # Worker implementations
│   ├── base_worker.py        # Shared worker base class
│   ├── monitor_worker.py
│   └── sync_worker.py
│
├── entrypoints/              # Service entry points
│   ├── monitor.py           # Move from src/monitor.py
│   ├── synchronizer.py      # Move from src/synchronizer.py
│   ├── priority_synchronizer.py
│   └── initializer.py
│
└── shared/                   # Shared utilities
    ├── logging_config.py
    ├── constants.py
    └── utils.py             # Rename from functions.py
```

### Migration Steps
1. Create new directory structure
2. Move and refactor `bigbrotr.py` into repository classes
3. Extract shared synchronizer logic to `workers/base_worker.py`
4. Move service entry points to `entrypoints/`
5. Update all imports
6. Update Dockerfiles to reference new entry points

**Effort:** XL (2-3 weeks)
**Benefits:**
- Clear separation of concerns
- Easier to navigate and understand
- Better testability
- Supports future growth

## 🔄 Refactoring Suggestions

### 1. Replace Multiprocessing with Pure Asyncio
**Description:** Simplify concurrency model by using only asyncio, removing multiprocessing and threading complexity.

**Files involved:**
- [src/monitor.py](src/monitor.py) (currently uses multiprocessing.Pool)
- [src/synchronizer.py](src/synchronizer.py) (currently uses threading.Thread)
- [src/priority_synchronizer.py](src/priority_synchronizer.py) (currently uses threading.Thread)
- [src/process_relay.py](src/process_relay.py)

**Benefits:**
- Simpler mental model (single concurrency paradigm)
- No IPC (inter-process communication) overhead
- Better resource utilization
- Easier debugging with async stack traces
- Unified connection pool management

**Risks:**
- CPU-bound operations (JSON serialization) might need thread pool executor
- Requires careful review of all I/O operations
- Performance testing needed to validate throughput

**Effort:** XL (3-4 weeks)

### 2. Implement Repository Pattern
**Description:** Abstract all database access behind repository interfaces to decouple business logic from SQL.

**Files involved:**
- [src/bigbrotr.py](src/bigbrotr.py) → Split into repositories
- [src/relay_loader.py](src/relay_loader.py) → Use repositories
- [src/process_relay.py](src/process_relay.py) → Use repositories
- All service files → Inject repositories

**Benefits:**
- Business logic testable with mocks
- Centralized query optimization
- Easier to switch databases or add caching
- Better query reusability
- Type-safe data access

**Risks:**
- Over-abstraction if not done carefully
- Initial performance overhead from abstraction layer
- Need to maintain both repository and SQL

**Effort:** XL (3-4 weeks)

### 3. Extract RelayProcessor Base Class
**Description:** Eliminate 95% code duplication between synchronizer and priority_synchronizer.

**Files involved:**
- [src/synchronizer.py](src/synchronizer.py)
- [src/priority_synchronizer.py](src/priority_synchronizer.py)
- Create new: `src/workers/base_relay_processor.py`

**Benefits:**
- Eliminate ~250 lines of duplication
- Single point of maintenance for worker logic
- Easier to add new processor types
- Consistent behavior across all processors

**Risks:**
- Need to identify correct abstraction points
- Template method pattern adds slight complexity

**Effort:** L (1 week)

### 4. Implement Circuit Breaker Pattern
**Description:** Add circuit breaker for relay connections to prevent cascading failures.

**Files involved:**
- Create new: `src/shared/circuit_breaker.py`
- [src/monitor.py](src/monitor.py)
- [src/synchronizer.py](src/synchronizer.py)
- [src/priority_synchronizer.py](src/priority_synchronizer.py)

**Benefits:**
- Fast-fail for known problematic relays
- Automatic recovery attempts with exponential backoff
- Better resource utilization
- Prevents thread/connection pool exhaustion

**Risks:**
- Adds state management complexity
- Need persistence for circuit state across restarts
- Tuning thresholds requires monitoring data

**Effort:** M (1 week)

### 5. Add Comprehensive Type Hints and Enable mypy
**Description:** Complete type hint coverage and integrate mypy for static type checking.

**Files involved:**
- All Python files in `src/`
- Add `mypy.ini` configuration
- Add mypy to CI/CD pipeline

**Benefits:**
- Catch type errors at development time
- Better IDE autocomplete and refactoring support
- Self-documenting code
- Safer refactoring

**Risks:**
- Initial time investment to add hints
- May uncover existing type inconsistencies
- Generic types for asyncpg can be complex

**Effort:** L (2 weeks)

## 🚀 Recommended Implementation Timeline

### Phase 1: Critical Fixes (Week 1-2)
**Goal:** Fix critical bugs that could cause production issues

1. Fix inverted connection validation (Day 1)
2. Remove pandas dependency (Day 1)
3. Fix private attribute access in monitor.py (Day 2)
4. Add connection pool timeout handling (Day 3)
5. Fix race condition with service_ready (Day 4)
6. Decide on incomplete Finder service (Day 5)
7. Add basic test infrastructure (Week 2)

**Deliverables:**
- All critical bugs resolved
- Basic pytest setup with 5 critical tests
- CI/CD pipeline started

### Phase 2: Code Quality & Duplication (Week 3-4)
**Goal:** Eliminate technical debt and improve maintainability

1. Extract RelayProcessor base class (Week 3)
2. Remove code duplication in worker functions
3. Extract magic numbers to constants
4. Add module-level docstrings
5. Remove unused imports and dependencies
6. Add type hints to critical paths

**Deliverables:**
- 250+ lines of duplication eliminated
- Consistent code patterns established
- Improved code readability

### Phase 3: Architecture & Performance (Week 5-8)
**Goal:** Improve architecture and optimize performance

1. Fix N+1 query pattern (Week 5)
2. Implement repository pattern basics (Week 5-6)
3. Add rate limiting for relay connections (Week 6)
4. Optimize connection pool reuse (Week 7)
5. Add network partition handling (Week 7)
6. Implement circuit breaker pattern (Week 8)

**Deliverables:**
- Database round trips reduced by 60%
- Repository pattern for events and relays
- Resilient connection handling

### Phase 4: Testing & Observability (Week 9-10)
**Goal:** Increase test coverage and observability

1. Add unit tests for core logic (Week 9)
2. Add integration tests for database operations (Week 9)
3. Enhance health checks with metrics (Week 10)
4. Add comprehensive logging configuration (Week 10)
5. Load test connection pooling (Week 10)

**Deliverables:**
- 60%+ test coverage
- Enhanced monitoring and debugging capabilities
- Performance validation under load

### Phase 5: Security & Cleanup (Week 11-12)
**Goal:** Harden security and clean up codebase

1. Add input sanitization for relay URLs (Week 11)
2. Implement query rate limiting (Week 11)
3. Review and harden PostgreSQL config (Week 11)
4. Remove all commented code and TODOs (Week 12)
5. Deprecate legacy configuration keys (Week 12)
6. Documentation update and review (Week 12)

**Deliverables:**
- Security hardened system
- Clean, well-documented codebase
- Production-ready deployment

## 🎓 Learning Resources

For developers working on these tasks:

### Python Async Patterns
- [Real Python: Async IO in Python](https://realpython.com/async-io-python/)
- [asyncpg Documentation](https://magicstack.github.io/asyncpg/)
- [Connection Pooling Best Practices](https://www.postgresql.org/docs/current/runtime-config-connection.html)

### Testing
- [Pytest Documentation](https://docs.pytest.org/)
- [Testing async code](https://pytest-asyncio.readthedocs.io/)
- [Hypothesis for property-based testing](https://hypothesis.readthedocs.io/)

### Architecture Patterns
- [Repository Pattern](https://martinfowler.com/eaaCatalog/repository.html)
- [Hexagonal Architecture](https://alistair.cockburn.us/hexagonal-architecture/)
- [Circuit Breaker Pattern](https://martinfowler.com/bliki/CircuitBreaker.html)

### Database Optimization
- [PostgreSQL Performance Tuning](https://wiki.postgresql.org/wiki/Performance_Optimization)
- [Connection Pooling with PgBouncer](https://www.pgbouncer.org/)
- [Query Optimization](https://www.postgresql.org/docs/current/performance-tips.html)

---

**Last Updated:** October 29, 2025
**Next Review:** Weekly during implementation phases
