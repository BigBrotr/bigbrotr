# Refactoring Summary: Composition with Public Pool

## Evolution of Design

The architecture of Brotr went through several iterations before settling on the final design:

1. **Initial Composition**: Brotr accepted pool as private parameter
2. **Switched to Inheritance**: `class Brotr(ConnectionPool)`
3. **Final Composition**: Brotr with **public pool property** ✓

## Why Public Pool Composition?

### The Final Decision

After exploring both inheritance and private composition, the decision was made to use **composition with a public pool property**. This provides the best of both worlds:

1. **Clear Separation of Concerns**:
   - `brotr.pool.*` for ConnectionPool operations (fetch, execute, acquire, etc.)
   - `brotr.*` for stored procedure wrappers (insert_event, cleanup_orphans, etc.)

2. **Explicit API**:
   - Users explicitly choose: `brotr.pool.fetch()` vs `brotr.insert_event()`
   - No confusion about which methods come from where
   - Self-documenting code

3. **Flexible Configuration**:
   - Unified YAML with pool config under "pool" root key
   - Single source of truth for all configuration
   - Easy to override pool or brotr settings independently

4. **Better for Testing**:
   - Pool can be mocked if needed
   - Clear boundaries between concerns
   - No method name conflicts

### Why NOT Inheritance?

While `class Brotr(ConnectionPool)` seemed natural at first, it had issues:

- ❌ Blurred the line between pool operations and business logic
- ❌ `brotr.fetch()` vs `brotr.insert_event()` - which is which?
- ❌ No clear indication of what comes from pool vs what's Brotr-specific
- ❌ Made the API less discoverable

### Why NOT Private Composition?

Private composition (passing pool as parameter) was the initial approach:

- ❌ Forced users to create two objects: `pool = ConnectionPool(...); brotr = Brotr(pool=pool)`
- ❌ Unclear ownership: who manages pool lifecycle?
- ❌ More complex API for common use cases

## Implementation Details

### 1. Class Structure

```python
class Brotr:
    """
    High-level database interface with composition.
    Uses a public ConnectionPool instance for database operations.
    """

    def __init__(
        self,
        # All ConnectionPool parameters
        host: Optional[str] = None,
        database: Optional[str] = None,
        # ... all pool params ...
        # Brotr-specific parameters
        default_batch_size: Optional[int] = None,
        # ... brotr params ...
    ):
        # Create public pool
        self.pool = ConnectionPool(
            host=host,
            port=port,
            database=database,
            # ... all params ...
        )

        # Initialize Brotr config
        self._brotr_config = BrotrConfigModel(...)
```

### 2. Unified Configuration

**YAML Structure** (`implementations/bigbrotr/yaml/core/brotr.yaml`):

```yaml
# Pool configuration under "pool" root key
pool:
  database:
    host: localhost
    port: 5432
    database: brotr
    user: admin
  pool:
    min_size: 5
    max_size: 20
  retry:
    max_attempts: 3
  # ... rest of pool config ...

# Brotr-specific configuration
batch:
  default_batch_size: 100
  max_batch_size: 1000

procedures:
  insert_event: insert_event
  insert_relay: insert_relay
  # ... other procedures ...

timeouts:
  query: 60.0
  procedure: 90.0
  batch: 120.0
```

### 3. Creation Methods

**Method 1: Direct Instantiation**
```python
brotr = Brotr(
    host="localhost",
    database="brotr",
    user="admin",
    min_size=5,
    max_size=20,
    default_batch_size=200
)
```

**Method 2: From Dictionary**
```python
config = {
    "pool": {
        "database": {"host": "localhost", "database": "brotr"},
        "pool": {"min_size": 5, "max_size": 20}
    },
    "batch": {"default_batch_size": 200}
}
brotr = Brotr.from_dict(config)
```

**Method 3: From YAML**
```python
brotr = Brotr.from_yaml("implementations/bigbrotr/yaml/core/brotr.yaml")
```

### 4. Usage Pattern

```python
async with brotr.pool:
    # Pool operations via brotr.pool
    result = await brotr.pool.fetch("SELECT * FROM events LIMIT 10")
    row = await brotr.pool.fetchrow("SELECT * FROM relays WHERE url = $1", url)

    # Acquire connection explicitly
    async with brotr.pool.acquire() as conn:
        await conn.execute("...")

    # Stored procedures via brotr
    await brotr.insert_event(
        event_id="abc123...",
        pubkey="def456...",
        # ... other params ...
    )

    # Cleanup operations
    deleted = await brotr.cleanup_orphans()
    # {"events": 10, "nip11": 5, "nip66": 3}
```

## Key Changes Made

### Updated Methods

**`from_yaml(yaml_path)`**: Now loads from single YAML file
- Before: Accepted two paths: `pool_yaml` and optional `brotr_yaml`
- After: Single `yaml_path` parameter, expects unified structure with "pool" key

**`from_dict(config_dict)`**: Expects unified structure
- Before: Pool config at root level alongside brotr config
- After: Pool config under "pool" key

**All stored procedure methods**: Use `self.pool.acquire()`
- Before: `async with self.acquire()`
- After: `async with self.pool.acquire()`

**`__repr__()`**: Access pool properties
- Before: `self.config.database.host`, `self.is_connected`
- After: `self.pool.config.database.host`, `self.pool.is_connected`

### Files Modified

1. **[src/core/brotr.py](src/core/brotr.py)**: Complete refactoring to composition with public pool
2. **[implementations/bigbrotr/yaml/core/brotr.yaml](implementations/bigbrotr/yaml/core/brotr.yaml)**: Added pool config under "pool" key
3. **[test_inheritance.py](test_inheritance.py)**: Updated to test composition pattern
4. **[REFACTORING_SUMMARY.md](REFACTORING_SUMMARY.md)**: This document

## Advantages of Final Design

### ✅ Clear API Boundaries
- `brotr.pool.*` → ConnectionPool operations
- `brotr.*` → Brotr business logic
- No ambiguity, no confusion

### ✅ Single Object Creation
- Users create one `Brotr` instance
- Pool is automatically created and managed
- No need to juggle multiple objects

### ✅ Explicit and Discoverable
- IDE autocomplete shows pool methods under `brotr.pool.`
- Clear separation in code reviews
- Self-documenting code

### ✅ Unified Configuration
- One YAML file with all settings
- Pool config clearly organized under "pool" key
- Easy to understand and maintain

### ✅ Flexible and Testable
- Pool property is public, can be mocked
- Clear boundaries for unit testing
- No method name conflicts

### ✅ Extensible
- Easy to add new Brotr methods without conflicts
- Pool methods remain separate
- Override possible if needed (though not recommended)

## Testing

Run the test script to verify the composition pattern:

```bash
$ python3 test_inheritance.py
======================================================================
Testing Brotr with Composition Pattern (Public Pool)
======================================================================

1. Direct Instantiation:
----------------------------------------------------------------------
   Brotr(host=localhost, database=brotr, connected=False)
   Host: localhost
   Database: brotr
   Pool min size: 5
   Pool max size: 20
   Batch size: 200
   Connected: False

2. From Dictionary (Unified Structure):
----------------------------------------------------------------------
   Brotr(host=dict.example.com, database=dict_db, connected=False)
   Host: dict.example.com
   Database: dict_db
   Batch size: 300

3. Composition Pattern Verification:
----------------------------------------------------------------------
   Has pool property? True
   Pool type: ConnectionPool
   Pool has acquire method? True
   Pool has connect method? True
   Brotr has insert_event method? True
   Brotr has cleanup_orphans method? True

4. All Defaults:
----------------------------------------------------------------------
   Brotr(host=localhost, database=database, connected=False)
   Host (default): localhost
   Database (default): database
   Batch size (default): 100

======================================================================
All tests passed! ✓
======================================================================
```

## Conclusion

The final design demonstrates an important principle:

> **"Choose the pattern that best serves your API's clarity and usability."**

After exploring multiple approaches, **composition with a public pool property** emerged as the winner because it provides:

1. **Clarity**: Explicit separation between pool and business logic
2. **Simplicity**: Single object creation, unified configuration
3. **Discoverability**: Self-documenting API with clear boundaries
4. **Flexibility**: Easy to test, extend, and maintain

This is the sweet spot between composition and inheritance - leveraging composition's flexibility while maintaining API simplicity through thoughtful design.
