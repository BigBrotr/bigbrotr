# Timeout Refactoring Summary: Eliminating Ambiguity and Improving Clarity

## Problem Identified

**Critical Issue:** Overlapping and conflicting timeout configuration between Pool and Brotr

### Before Refactoring

```python
# pool.py
class PoolSizingConfig(BaseModel):
    timeout: float = 10.0           # Pool acquisition timeout
    command_timeout: float = 60.0   # ❌ Global asyncpg command timeout

# brotr.py
class OperationTimeoutsConfig(BaseModel):
    query: float = 60.0       # Brotr query timeout
    procedure: float = 90.0   # Brotr procedure timeout
    batch: float = 120.0      # Brotr batch timeout
```

**Problems:**
1. ❌ `command_timeout` in pool could conflict with Brotr's specific timeouts
2. ❌ `PoolSizingConfig` mixed sizing parameters with timeouts (wrong abstraction)
3. ❌ Unclear which timeout takes precedence
4. ❌ Less flexible - can't have different timeouts for different operations

## Solution Implemented

### Separated Concerns: Limits vs Timeouts

**New Structure in pool.py:**

```python
class PoolLimitsConfig(BaseModel):
    """Connection pool size and resource limits."""
    min_size: int = 5
    max_size: int = 20
    max_queries: int = 50000
    max_inactive_connection_lifetime: float = 300.0
    # ✓ No timeouts here - pure limits

class PoolTimeoutsConfig(BaseModel):
    """Pool-level timeout configuration."""
    acquisition: float = 10.0  # Only for pool.acquire()
    # ✓ No command_timeout - Brotr controls operation timeouts

class ConnectionPoolConfig(BaseModel):
    database: DatabaseConfig
    limits: PoolLimitsConfig      # ✓ Clear separation
    timeouts: PoolTimeoutsConfig  # ✓ Dedicated timeout config
    retry: RetryConfig
    server_settings: ServerSettingsConfig
```

## Changes Made

### 1. pool.py

#### Classes Renamed/Split

| Before | After | Reason |
|--------|-------|--------|
| `PoolSizingConfig` | Split into `PoolLimitsConfig` + `PoolTimeoutsConfig` | Separate concerns |
| `timeout` | `acquisition` | More specific name |
| `command_timeout` | ❌ Removed | Moved to Brotr control |

#### ConnectionPool.__init__ Signature

```python
# Before:
def __init__(
    timeout: Optional[float] = None,
    command_timeout: Optional[float] = None,
    ...
)

# After:
def __init__(
    acquisition_timeout: Optional[float] = None,  # ✓ Clear name
    # command_timeout removed
    ...
)
```

#### Config Structure

```python
# Before:
self._config.sizing.timeout
self._config.sizing.command_timeout

# After:
self._config.limits.min_size
self._config.timeouts.acquisition
```

### 2. brotr.py

#### Removed command_timeout Parameter

```python
# Before:
def __init__(
    command_timeout: Optional[float] = None,
    ...
)
    self.pool = ConnectionPool(
        command_timeout=command_timeout,
        ...
    )

# After:
def __init__(
    acquisition_timeout: Optional[float] = None,  # Renamed
    ...
)
    self.pool = ConnectionPool(
        acquisition_timeout=acquisition_timeout,  # No command_timeout
        ...
    )
```

#### Brotr Controls All Operation Timeouts

```python
# Brotr operations use their own timeouts
async with self.pool.acquire() as conn:
    await conn.execute(
        query,
        ...,
        timeout=self._config.timeouts.procedure  # ✓ Brotr's timeout
    )
```

### 3. YAML Structure

**brotr.yaml:**

```yaml
# Before:
pool:
  sizing:
    min_size: 5
    max_size: 20
    timeout: 10.0            # ❌ Mixed with sizing
    command_timeout: 60.0    # ❌ Global timeout

# After:
pool:
  limits:                    # ✓ Pure resource limits
    min_size: 5
    max_size: 20
    max_queries: 50000
    max_inactive_connection_lifetime: 300.0

  timeouts:                  # ✓ Separated timeout config
    acquisition: 10.0        # ✓ Only for pool.acquire()

# Brotr timeouts (unchanged - already correct)
timeouts:
  query: 60.0
  procedure: 90.0
  batch: 120.0
```

### 4. Access Patterns

```python
# Before:
pool.config.sizing.min_size         # ✓ OK
pool.config.sizing.timeout          # ⚠️ Timeout in sizing?
pool.config.sizing.command_timeout  # ❌ Conflicts with Brotr

# After:
pool.config.limits.min_size         # ✓ Clear!
pool.config.timeouts.acquisition    # ✓ Obvious purpose
# No command_timeout - Brotr controls it
```

## Benefits Achieved

### ✅ Eliminated Timeout Conflicts

**Before:** Pool's `command_timeout` could interfere with Brotr's operation-specific timeouts
**After:** Pool only handles acquisition timeout, Brotr controls all operation timeouts

### ✅ Better Abstraction

**Before:** `PoolSizingConfig` mixed sizing AND timeouts
**After:** `PoolLimitsConfig` for limits, `PoolTimeoutsConfig` for timeouts

### ✅ More Flexible

**Before:** Global `command_timeout` applied to all operations
**After:** Brotr can set different timeouts for queries, procedures, and batch operations

### ✅ Clearer Naming

| Before | After | Improvement |
|--------|-------|-------------|
| `timeout` | `acquisition` | Specifies it's for pool.acquire() |
| `sizing.timeout` | `timeouts.acquisition` | Clear categorization |
| `command_timeout` | Removed | No ambiguity |

### ✅ Professional Structure

```
ConnectionPoolConfig
├── database       # Connection parameters
├── limits         # ✓ Resource limits (size, lifecycle)
├── timeouts       # ✓ Pool timeouts (acquisition)
├── retry          # Retry logic
└── server_settings # Server config

BrotrConfig
├── batch          # Batch configuration
├── procedures     # Stored procedures
└── timeouts       # ✓ Operation timeouts (query, procedure, batch)
```

## Migration Guide

### Code Changes

```python
# Before:
pool = ConnectionPool(
    timeout=10.0,
    command_timeout=60.0,
)
min_size = pool.config.sizing.min_size
timeout = pool.config.sizing.timeout

# After:
pool = ConnectionPool(
    acquisition_timeout=10.0,  # Renamed
    # command_timeout removed
)
min_size = pool.config.limits.min_size      # limits, not sizing
timeout = pool.config.timeouts.acquisition   # timeouts.acquisition
```

### YAML Changes

```yaml
# Before:
pool:
  sizing:
    min_size: 5
    timeout: 10.0
    command_timeout: 60.0

# After:
pool:
  limits:
    min_size: 5
  timeouts:
    acquisition: 10.0
```

### Brotr Changes

```python
# Before:
brotr = Brotr(
    timeout=10.0,
    command_timeout=60.0,
    ...
)

# After:
brotr = Brotr(
    acquisition_timeout=10.0,  # Renamed
    # command_timeout removed - Brotr controls operation timeouts
    ...
)
```

## Testing

All tests pass successfully:

```bash
$ python3 test_composition.py
======================================================================
Testing Brotr with Composition Pattern (Public Pool)
======================================================================
...
======================================================================
All tests passed! ✓
======================================================================
```

## Summary

This refactoring achieved:

1. ✅ **Eliminated timeout conflicts** - Clear separation between pool and operation timeouts
2. ✅ **Improved abstraction** - Limits vs Timeouts properly separated
3. ✅ **Better naming** - `acquisition` instead of generic `timeout`
4. ✅ **More flexible** - Brotr has full control over operation-specific timeouts
5. ✅ **Clearer structure** - Professional categorization of configuration
6. ✅ **No functionality loss** - All features preserved, just better organized

**Result:** A more maintainable, professional, and clear codebase with proper separation of concerns between pool management and business logic timeouts.
