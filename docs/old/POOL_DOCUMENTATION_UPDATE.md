# Pool.py Documentation Update

## Overview

Updated all comments, docstrings, and inline documentation in [src/core/pool.py](src/core/pool.py) to accurately reflect the new timeout refactoring structure.

## Changes Made

### 1. Pydantic Model Documentation

#### `PoolLimitsConfig`
- **Enhanced docstring** to clarify it controls pool size and connection lifecycle
- **Added note** that timeout configuration is separate (in `PoolTimeoutsConfig`)
- **Added Field descriptions** for all attributes:
  - `min_size`: "Minimum number of connections in the pool"
  - `max_size`: "Maximum number of connections in the pool"
  - `max_queries`: "Max queries per connection before recycling"
  - `max_inactive_connection_lifetime`: "Seconds before idle connection is closed"

#### `PoolTimeoutsConfig`
- **Enhanced docstring** with important note about scope:
  - Clarifies it only controls `pool.acquire()` timeout
  - Notes that operation timeouts are controlled by caller via asyncpg method parameters
- **Added Field description** for `acquisition`: "Timeout for acquiring a connection from the pool (seconds)"

#### `ConnectionPoolConfig`
- **Enhanced docstring** with structured overview:
  - `database`: Connection parameters (host, port, user, etc.)
  - `limits`: Resource limits (pool size, connection lifecycle)
  - `timeouts`: Pool-level timeouts (acquisition only)
  - `retry`: Connection retry logic
  - `server_settings`: PostgreSQL server settings

### 2. Method Documentation

Updated all query execution methods to reflect that timeout is optional and controlled by caller:

#### `fetch()`, `fetchrow()`, `fetchval()`, `execute()`, `executemany()`
- **Removed outdated reference** to `command_timeout` (which no longer exists)
- **Updated timeout description**: "Optional query timeout in seconds (if None, uses asyncpg default)"
- **Added `Raises` section**: `asyncpg.PostgresError: If query execution fails`

### 3. Inline Comments

#### `__init__()` method
- Updated section comments for clarity:
  - "Database connection parameters" (was "Database config")
  - "Pool resource limits (size, lifecycle)" (was "Pool limits config")
  - "Pool-level timeouts (acquisition only - operation timeouts controlled by caller)" (was "Pool timeouts config")

#### `connect()` method
- Added detailed comment block before `asyncpg.create_pool()`:
  ```python
  # Create asyncpg pool with configuration
  # Note: 'timeout' here is for pool.acquire() only
  # Operation timeouts are controlled by the caller via asyncpg method parameters
  ```
- Organized parameters with inline comments:
  - "Connection parameters"
  - "Pool resource limits"
  - "Pool acquisition timeout"
  - "Server settings"

## Key Documentation Principles Applied

### ✅ Clear Separation of Concerns
Documentation now explicitly states:
- **Pool manages**: Connection acquisition and resource limits
- **Caller manages**: Operation-specific timeouts (query, procedure, batch)

### ✅ Removed Ambiguity
- Eliminated all references to removed `command_timeout`
- Clarified that `timeout` parameter in asyncpg methods is optional and caller-controlled
- Made explicit that `PoolTimeoutsConfig.acquisition` is ONLY for `pool.acquire()`

### ✅ Enhanced Discoverability
- Field descriptions visible in IDE tooltips
- Docstrings explain the "why" not just the "what"
- Clear cross-references between related concepts

### ✅ Professional Structure
All Pydantic models now follow consistent documentation pattern:
1. Class docstring explaining purpose
2. Field with `description` parameter
3. Validators with clear error messages

## Configuration Example with Comments

```python
from core.pool import ConnectionPool

# Create pool with explicit configuration
pool = ConnectionPool(
    # Connection parameters
    host="localhost",
    database="brotr",
    user="admin",

    # Resource limits
    min_size=5,           # Minimum connections maintained
    max_size=20,          # Maximum connections allowed
    max_queries=50000,    # Recycle connection after N queries

    # Pool timeout (acquisition only)
    acquisition_timeout=10.0,  # Max wait time to get connection from pool

    # Note: Operation timeouts are passed to individual queries:
    # await pool.fetch(query, timeout=60.0)  # Query-specific timeout
)

# Accessing configuration
print(pool.config.limits.min_size)      # Pool size limits
print(pool.config.timeouts.acquisition)  # Pool acquisition timeout

# Using with custom timeouts
await pool.fetch("SELECT * FROM events", timeout=30.0)  # Custom query timeout
```

## YAML Configuration with Comments

```yaml
# Connection pool configuration
limits:
  min_size: 5              # Minimum number of connections in pool
  max_size: 20             # Maximum number of connections in pool
  max_queries: 50000       # Max queries per connection before recycling
  max_inactive_connection_lifetime: 300.0  # Seconds before idle connection closed

timeouts:
  acquisition: 10.0        # Timeout for acquiring connection from pool (seconds)
                          # Note: Operation timeouts controlled by caller

# Operation-specific timeouts (controlled by Brotr, not pool)
# See: src/core/brotr.py -> OperationTimeoutsConfig
```

## Benefits

1. **Self-Documenting Code**: Comments and docstrings explain design decisions
2. **Better IDE Support**: Field descriptions appear in autocomplete tooltips
3. **Clear Responsibility**: Explicit about what pool controls vs what caller controls
4. **Easier Maintenance**: Future developers understand timeout separation rationale
5. **No Ambiguity**: Removed all references to non-existent `command_timeout`

## Testing

All tests pass with updated documentation:

```bash
$ python3 test_composition.py
======================================================================
All tests passed! ✓
======================================================================
```

Documentation changes are non-breaking - only comments and docstrings were updated, no functional code changes.
