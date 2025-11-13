# Claude AI Instructions for BigBrotr Project

**Last Updated**: 2025-11-13
**Project**: BigBrotr - Nostr Data Archiving and Monitoring System
**Language**: Python 3.9+

---

## 📋 Project Overview

BigBrotr is a production-grade Nostr data archiving and monitoring system with a three-layer architecture (Core, Service, Implementation). The project is in **Core Development Phase** with ConnectionPool and Brotr components production-ready.

**Current Status**: ~20% complete (Core: 60%, Services: 0%)
**No Backward Compatibility Required**: Architecture can evolve freely during development.

---

## 🎯 Core Principles

### 1. Architecture

**Three Layers**:
1. **Core Layer** (`src/core/`): Reusable, implementation-agnostic foundation
2. **Service Layer** (`src/services/`): Modular, composable business logic
3. **Implementation Layer** (`implementations/<name>/`): Configuration-driven customization

**Design Philosophy**:
- Separation of concerns
- Dependency injection
- Composition over inheritance
- Configuration-driven behavior
- Type safety with Pydantic
- Self-documenting code

### 2. Design Patterns to Use

| Pattern | When to Apply |
|---------|---------------|
| **Dependency Injection** | Services receive dependencies (pool, brotr) via constructor |
| **Composition** | HAS-A relationships (Brotr HAS-A pool, not IS-A) |
| **Factory Method** | `from_yaml()`, `from_dict()` for config-driven construction |
| **Template Method** | Extract common algorithm, specialize in subclasses |
| **Decorator/Wrapper** | Add cross-cutting concerns (logging, monitoring) |
| **Protocol/Duck Typing** | Define interfaces without inheritance |

### 3. Code Quality Standards

**REQUIRED**:
- ✅ Type hints for ALL public methods and functions
- ✅ Docstrings for ALL classes and public methods (Google style)
- ✅ DRY principle - eliminate code duplication via helper methods
- ✅ Single Responsibility - each class/method does ONE thing
- ✅ Clear variable/function names (no abbreviations unless standard)
- ✅ Comments for complex logic (why, not what)

**FORBIDDEN**:
- ❌ Code duplication (use helper methods, template methods, wrappers)
- ❌ Hardcoded values (use config or constants)
- ❌ Generic exception catching (catch specific exceptions)
- ❌ Abbreviations in names (except standard ones like `id`, `url`, `db`)
- ❌ Magic numbers (use named constants)

---

## 🏗️ Core Components Reference

### 1. ConnectionPool (`src/core/pool.py`)

**Purpose**: Enterprise-grade PostgreSQL connection management with asyncpg.

**Status**: ✅ Production Ready (~580 lines)

**Key Features**:
- Async connection pooling
- Automatic retry with exponential backoff
- PGBouncer compatibility
- Connection recycling (max queries, max idle time)
- Environment variable password loading
- YAML/dict configuration support
- Type-safe Pydantic validation

**API Pattern**:
```python
# Construction
pool = ConnectionPool.from_yaml("config/pool.yaml")
pool = ConnectionPool.from_dict(config_dict)
pool = ConnectionPool(host="...", database="...", min_size=5, max_size=20)

# Usage
async with pool:
    result = await pool.fetch("SELECT * FROM events LIMIT 10")
    await pool.execute("INSERT INTO events ...")
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("...")
```

**Configuration Example**:
```yaml
database:
  host: localhost
  port: 5432
  database: brotr
  user: admin
  # password from DB_PASSWORD env var

limits:
  min_size: 5
  max_size: 20
  max_queries: 50000
  max_inactive_connection_lifetime: 300.0

timeouts:
  acquisition: 10.0

retry:
  max_attempts: 3
  initial_delay: 1.0
  max_delay: 10.0
  exponential_backoff: true
```

**Design Decisions**:
- Password from env var (`DB_PASSWORD`) for security
- Acquisition timeout separate from operation timeouts
- Pydantic validation for type safety
- Context manager for resource management

---

### 2. Brotr (`src/core/brotr.py`)

**Purpose**: High-level database interface with stored procedure wrappers.

**Status**: ✅ Production Ready (~775 lines)

**Key Features**:
- **Dependency Injection**: Pool as constructor parameter (not 16 pool params!)
- Stored procedure wrappers (insert_event, insert_relay, insert_relay_metadata)
- Batch operations with configurable sizes
- Cleanup operations (delete orphaned records)
- Helper methods (`_validate_batch_size()`, `_call_delete_procedure()`)
- Hex to bytea conversion
- YAML/dict configuration support

**API Pattern**:
```python
# Construction (Dependency Injection)
pool = ConnectionPool(...)
brotr = Brotr(pool=pool, default_batch_size=200)

# Or use default pool
brotr = Brotr(default_batch_size=200)

# Or from config
brotr = Brotr.from_yaml("config/brotr.yaml")

# Usage
async with brotr.pool:
    # Insert event
    await brotr.insert_event(
        event_id="...",     # 64-char hex
        pubkey="...",       # 64-char hex
        created_at=1699876543,
        kind=1,
        tags=[["e", "..."], ["p", "..."]],
        content="Hello Nostr!",
        sig="...",          # 128-char hex
        relay_url="wss://relay.example.com",
        relay_network="clearnet",
        relay_inserted_at=1699876000,
        seen_at=1699876543
    )

    # Batch operations
    await brotr.insert_events_batch(events, batch_size=100)

    # Cleanup
    deleted = await brotr.cleanup_orphans()
    # {"events": 10, "nip11": 5, "nip66": 3}

    # Direct pool access for custom queries
    result = await brotr.pool.fetch("SELECT COUNT(*) FROM events")
```

**Configuration Example**:
```yaml
pool:
  database: {host: localhost, database: brotr}
  limits: {min_size: 5, max_size: 20}

batch:
  default_batch_size: 100
  max_batch_size: 1000

procedures:
  insert_event: insert_event
  insert_relay: insert_relay
  insert_relay_metadata: insert_relay_metadata
  delete_orphan_events: delete_orphan_events
  delete_orphan_nip11: delete_orphan_nip11
  delete_orphan_nip66: delete_orphan_nip66

timeouts:
  query: 60.0
  procedure: 90.0
  batch: 120.0
```

**Design Decisions**:
- **Dependency Injection**: Reduced __init__ params from 28 to 12 (57% reduction)
- **Public Pool Property**: `brotr.pool.fetch()` vs `brotr.insert_event()` - explicit API
- **Helper Methods**: DRY principle - `_validate_batch_size()`, `_call_delete_procedure()`
- **Timeout Separation**: Pool handles acquisition, Brotr handles operation timeouts

---

### 3. Service Wrapper (`src/core/service.py`)

**Purpose**: Generic lifecycle management wrapper for any service.

**Status**: ⚠️ Design Complete, Implementation Pending

**Design Pattern**: Decorator/Wrapper

**Why Service Wrapper?**
Instead of adding logging/monitoring to each service individually, create a reusable wrapper that can wrap ANY service implementing `ManagedService` protocol.

**Protocol**:
```python
class ManagedService(Protocol):
    async def connect(self) -> None: ...
    async def close(self) -> None: ...

    @property
    def is_connected(self) -> bool: ...
```

**Planned API**:
```python
from core.service import Service, ServiceConfig

# Wrap any service
pool = ConnectionPool(...)
config = ServiceConfig(
    enable_logging=True,
    enable_health_checks=True,
    health_check_interval=60.0
)
service = Service(pool, name="database_pool", config=config)

# Use with context manager
async with service:
    # Service handles:
    # - Logging: "[database_pool] Starting service..."
    # - Health checks: Every 60s
    # - Statistics: Uptime, success rate

    result = await service.instance.fetch(...)
    is_healthy = await service.health_check()
    stats = service.get_stats()
```

**Design Decisions**:
- Generic wrapper for ANY service (DRY)
- Protocol-based (duck typing, not inheritance)
- Separation of concerns (services focus on logic, wrapper handles monitoring)
- Configurable behavior per service
- Future-proof (easy to add circuit breaker, rate limiting, tracing)

---

## 📚 When Implementing New Code

### For Core Components

1. **Use Dependency Injection**
   ```python
   # Good ✅
   class MyService:
       def __init__(self, pool: ConnectionPool, brotr: Brotr):
           self.pool = pool
           self.brotr = brotr

   # Bad ❌
   class MyService:
       def __init__(self, host: str, port: int, database: str, ...):
           self.pool = ConnectionPool(host, port, database, ...)
   ```

2. **Provide Factory Methods**
   ```python
   @classmethod
   def from_yaml(cls, yaml_path: str) -> "MyService":
       """Create from YAML configuration."""
       config = load_yaml(yaml_path)
       return cls.from_dict(config)

   @classmethod
   def from_dict(cls, config_dict: Dict[str, Any]) -> "MyService":
       """Create from dictionary configuration."""
       # Parse config, create dependencies, inject
       pool = ConnectionPool.from_dict(config_dict["pool"])
       return cls(pool=pool, ...)
   ```

3. **Use Pydantic for Configuration**
   ```python
   from pydantic import BaseModel, Field

   class MyServiceConfig(BaseModel):
       """Service configuration."""

       interval: float = Field(
           default=60.0,
           ge=1.0,
           description="Check interval in seconds"
       )
       max_retries: int = Field(
           default=3,
           ge=1,
           le=10,
           description="Maximum retry attempts"
       )
   ```

4. **Implement Context Manager (Async)**
   ```python
   async def __aenter__(self) -> "MyService":
       await self.connect()
       return self

   async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
       await self.close()
   ```

5. **Use Helper Methods to Eliminate Duplication**
   ```python
   # Extract common logic into helper methods
   def _validate_parameter(self, value: int) -> int:
       """Validate parameter (helper method)."""
       if value > self.config.max_value:
           raise ValueError(f"Value {value} exceeds max")
       return value

   # Use in multiple places
   def method_a(self, value: int):
       value = self._validate_parameter(value)
       # ...

   def method_b(self, value: int):
       value = self._validate_parameter(value)
       # ...
   ```

---

### For Service Layer

1. **Service Structure**
   ```python
   from core.brotr import Brotr
   from core.pool import ConnectionPool

   class MyService:
       """
       Service description.

       Features:
       - Feature 1
       - Feature 2
       """

       def __init__(
           self,
           pool: ConnectionPool,
           brotr: Brotr,
           check_interval: float = 60.0,
       ):
           """
           Initialize service.

           Args:
               pool: ConnectionPool instance
               brotr: Brotr instance
               check_interval: Check interval in seconds
           """
           self.pool = pool
           self.brotr = brotr
           self.check_interval = check_interval

       async def start(self) -> None:
           """Start service."""
           # Implementation

       async def stop(self) -> None:
           """Stop service."""
           # Implementation

       @property
       def is_running(self) -> bool:
           """Check if service is running."""
           return self._is_running
   ```

2. **Async Main Loop Pattern**
   ```python
   async def run(self) -> None:
       """Main service loop."""
       while self._is_running:
           try:
               await self._do_work()
           except Exception as e:
               # Log error, continue
               await asyncio.sleep(self.check_interval)
           else:
               await asyncio.sleep(self.check_interval)
   ```

---

## 🚫 Common Mistakes to Avoid

### 1. Parameter Explosion
```python
# Bad ❌ - Too many parameters
def __init__(
    self,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    min_size: int,
    max_size: int,
    # ... 20 more parameters
):
    self.pool = ConnectionPool(host, port, database, ...)

# Good ✅ - Dependency Injection
def __init__(self, pool: ConnectionPool, config: MyServiceConfig):
    self.pool = pool
    self.config = config
```

### 2. Code Duplication
```python
# Bad ❌ - Duplicated validation
def method_a(self, batch_size: int):
    if batch_size > self.config.max_batch_size:
        raise ValueError(f"Batch size {batch_size} exceeds max")
    # ...

def method_b(self, batch_size: int):
    if batch_size > self.config.max_batch_size:
        raise ValueError(f"Batch size {batch_size} exceeds max")
    # ...

# Good ✅ - Helper method (DRY)
def _validate_batch_size(self, batch_size: int) -> int:
    """Validate batch size."""
    if batch_size > self.config.max_batch_size:
        raise ValueError(f"Batch size {batch_size} exceeds max")
    return batch_size

def method_a(self, batch_size: int):
    batch_size = self._validate_batch_size(batch_size)
    # ...

def method_b(self, batch_size: int):
    batch_size = self._validate_batch_size(batch_size)
    # ...
```

### 3. Inheritance vs Composition
```python
# Bad ❌ - Inheritance
class Brotr(ConnectionPool):
    def __init__(self, ...):
        super().__init__(...)
    # Unclear API: brotr.fetch() or brotr.insert_event()?

# Good ✅ - Composition with public property
class Brotr:
    def __init__(self, pool: ConnectionPool):
        self.pool = pool  # Public property

    # Clear API:
    # brotr.pool.fetch()  - Pool operations
    # brotr.insert_event() - Brotr operations
```

### 4. Generic Exception Handling
```python
# Bad ❌
try:
    await pool.connect()
except Exception as e:
    # Catches everything, including KeyboardInterrupt!
    print(f"Error: {e}")

# Good ✅
try:
    await pool.connect()
except (asyncpg.PostgresError, OSError, ConnectionError) as e:
    # Specific exceptions only
    raise ConnectionError(f"Failed to connect: {e}") from e
```

### 5. Missing Type Hints
```python
# Bad ❌
def acquire(self):
    return self._pool.acquire()

# Good ✅
from typing import AsyncContextManager
import asyncpg

def acquire(self) -> AsyncContextManager[asyncpg.Connection]:
    """
    Acquire connection from pool.

    Returns:
        Connection context manager
    """
    return self._pool.acquire()
```

---

## 📝 Documentation Requirements

### Class Docstring
```python
class MyService:
    """
    Short one-line description.

    Longer description explaining what this class does,
    its responsibilities, and how it fits into the system.

    Features:
    - Feature 1 description
    - Feature 2 description

    Example usage:
        service = MyService(pool=pool, brotr=brotr)
        async with service:
            await service.do_something()

    Args:
        pool: ConnectionPool instance
        brotr: Brotr instance
    """
```

### Method Docstring
```python
async def insert_event(
    self,
    event_id: str,
    pubkey: str,
    created_at: int,
    kind: int,
    tags: List[List[str]],
    content: str,
    sig: str,
    relay_url: str,
    relay_network: str,
    relay_inserted_at: int,
    seen_at: int,
) -> None:
    """
    Insert event into database using stored procedure.

    Args:
        event_id: Event ID (64-char hex)
        pubkey: Public key (64-char hex)
        created_at: Event creation timestamp (Unix seconds)
        kind: Event kind number (0-65535)
        tags: Event tags as list of lists
        content: Event content
        sig: Event signature (128-char hex)
        relay_url: Relay WebSocket URL
        relay_network: Network type (clearnet or tor)
        relay_inserted_at: Relay insertion timestamp
        seen_at: When event was seen on relay

    Raises:
        asyncpg.PostgresError: If database operation fails
        ValueError: If hex conversion fails

    Example:
        await brotr.insert_event(
            event_id="abc123...",
            pubkey="def456...",
            created_at=1699876543,
            kind=1,
            tags=[["e", "..."]],
            content="Hello Nostr!",
            sig="789ghi...",
            relay_url="wss://relay.example.com",
            relay_network="clearnet",
            relay_inserted_at=1699876000,
            seen_at=1699876543
        )
    """
```

---

## 🗂️ File Organization

```
src/
├── core/
│   ├── pool.py              # ConnectionPool (production-ready)
│   ├── brotr.py             # Brotr (production-ready)
│   ├── service.py           # Service wrapper (design complete)
│   ├── config.py            # Global config management (pending)
│   ├── logger.py            # Structured logging (pending)
│   └── utils.py             # Shared utilities (pending)
│
└── services/
    ├── initializer.py       # Database bootstrap (pending)
    ├── finder.py            # Relay discovery (pending)
    ├── monitor.py           # Health checks (pending)
    ├── synchronizer.py      # Event collection (pending)
    ├── priority_synchronizer.py  # Priority sync (pending)
    ├── api.py               # REST API (Phase 3)
    └── dvm.py               # Data Vending Machine (Phase 3)
```

**Rules**:
- Core = reusable, no business logic
- Services = business logic, leverage core
- Each service in separate file
- Shared utilities in `utils.py`

---

## 🧪 Testing Approach

### Manual Testing (Current)
```python
# tests/test_composition.py
def test_brotr_composition():
    # Test dependency injection
    pool = ConnectionPool(...)
    brotr = Brotr(pool=pool)
    assert brotr.pool is pool  # Pool sharing works

    # Test from_dict
    brotr = Brotr.from_dict(config)
    assert brotr.config.batch.default_batch_size == 200
```

### Future: Pytest
```python
import pytest
from core.pool import ConnectionPool

@pytest.fixture
async def pool():
    pool = ConnectionPool(host="localhost", database="test")
    async with pool:
        yield pool

async def test_pool_connection(pool):
    assert pool.is_connected
    result = await pool.fetch("SELECT 1")
    assert result[0][0] == 1
```

---

## 📖 Additional Resources

### Documentation
- **[PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md)** - Complete technical spec
- **[PROJECT_STATUS.md](PROJECT_STATUS.md)** - Current status and progress
- **[docs/old/](docs/old/)** - Historical refactoring documents

### Key Refactoring Documents (Archived)
- **Dependency Injection Refactoring**: 28 → 12 parameters
- **Service Wrapper Design**: Generic lifecycle wrapper
- **Composition Pattern Evolution**: Why public pool property
- **Timeout Separation**: Pool vs Brotr timeout responsibilities

---

## ⚙️ Configuration Management

### Environment Variables
```bash
# Required
DB_PASSWORD=your_secure_password

# Optional
SOCKS5_PROXY_URL=socks5://127.0.0.1:9050
IMPLEMENTATION=bigbrotr
CONFIG_DIR=implementations/bigbrotr/config
```

### YAML Configuration Hierarchy
```
implementations/bigbrotr/config/
├── core/
│   ├── pool.yaml      # ConnectionPool config
│   └── brotr.yaml     # Brotr config (includes pool section)
├── services/
│   ├── finder.yaml    # Finder service config
│   ├── monitor.yaml   # Monitor service config
│   └── ...
└── postgres/
    └── postgresql.conf
```

---

## 🎓 Learning from Past Decisions

### 1. Why Dependency Injection?

**Problem**: Brotr had 28 parameters (16 from ConnectionPool + 12 Brotr-specific)

**Solution**: Inject ConnectionPool instead of its 16 parameters

**Result**:
- 57% parameter reduction (28 → 12)
- Pool sharing enabled
- Better testability (inject mocks)
- Cleaner API

**Lesson**: When a class has many parameters from another class, inject that class instead.

---

### 2. Why Public Pool Property?

**Alternatives Considered**:
1. Inheritance: `class Brotr(ConnectionPool)` ❌
2. Private composition: `self._pool` ❌
3. Public composition: `self.pool` ✅

**Decision**: Public pool property

**Rationale**:
- Clear API: `brotr.pool.fetch()` vs `brotr.insert_event()`
- Explicit source of methods
- No method name conflicts
- Easy to understand

**Lesson**: Favor composition with explicit access over inheritance for clarity.

---

### 3. Why Service Wrapper?

**Problem**: Should we add logging/health checks to Pool? Brotr? Every service?

**Solution**: Generic Service wrapper that can wrap ANY service

**Benefits**:
- Write once, use everywhere (DRY)
- Services stay focused on business logic
- Uniform interface for all services
- Easy to extend (circuit breaker, rate limiting, tracing)

**Lesson**: Extract cross-cutting concerns into reusable wrappers.

---

## 🚀 Next Steps for Development

### Immediate Tasks

1. **Implement Service Wrapper** (`src/core/service.py`)
   - Status: Design complete
   - Priority: High
   - Validates: Wrapper pattern, protocol usage

2. **Implement Logger Module** (`src/core/logger.py`)
   - Status: Not started
   - Priority: Medium
   - Needed for: Service wrapper, all services

3. **Implement Config Module** (`src/core/config.py`)
   - Status: Not started
   - Priority: Medium
   - Purpose: Global configuration management

### Service Implementation Order

1. **Initializer** - Bootstrap database, seed data
2. **Finder** - Discover relays
3. **Monitor** - Health checks (NIP-11, NIP-66)
4. **Synchronizer** - Event collection
5. **Priority Synchronizer** - Priority relay sync

---

## 📞 Questions to Ask User

When implementing new features, consider asking:

1. **Configuration**: Where should this config live? Core or service-specific?
2. **Dependencies**: Should this be injected or created internally?
3. **Error Handling**: What should happen on failure? Retry? Log and continue?
4. **Timeouts**: What's reasonable timeout for this operation?
5. **Testing**: How can we test this without a real database/relay?

---

## ✅ Checklist for New Code

Before considering code complete:

- [ ] Type hints on all public methods
- [ ] Docstrings for all classes and public methods
- [ ] Helper methods to eliminate duplication
- [ ] Specific exception handling (not generic `except Exception`)
- [ ] Pydantic config classes with Field descriptions
- [ ] Factory methods (`from_yaml()`, `from_dict()`) if configurable
- [ ] Context manager support if managing resources
- [ ] Tests (even if manual for now)
- [ ] Examples in docstrings
- [ ] Clear variable names (no abbreviations)

---

## 🎯 Summary: Key Takeaways

1. **Dependency Injection**: Inject dependencies, don't create them
2. **Composition**: HAS-A with public property for clarity
3. **DRY**: Helper methods, template methods, wrappers
4. **Type Safety**: Full type hints, Pydantic validation
5. **Configuration**: YAML-based, environment variables for secrets
6. **Separation of Concerns**: Core (reusable) vs Services (business logic)
7. **Design Patterns**: Use established patterns (DI, Factory, Template, Wrapper)
8. **Documentation**: Complete docstrings, examples, rationale

---

**Remember**: This project prioritizes clean architecture and maintainability over quick implementation. Take time to design properly, eliminate duplication, and document thoroughly.

**When in doubt**: Check existing code (Pool, Brotr) for patterns and consistency.
