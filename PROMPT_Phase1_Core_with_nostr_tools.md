# Prompt: BigBrotr Phase 1 - Core Infrastructure with nostr-tools Integration

## Context

You are implementing the core infrastructure layer for BigBrotr, a modular Nostr data archiving system. This is **Phase 1** of the project - the foundation upon which all services will be built.

**Project Status**: Initial development - no backward compatibility requirements. Architecture can evolve based on implementation experience.

**Critical**: BigBrotr uses `nostr-tools` (v1.4.0) for ALL Nostr protocol operations. You must NOT reimplement any protocol functionality - focus on database persistence, service orchestration, and configuration management.

## Project Overview

BigBrotr uses a three-layer architecture:
1. **Core Layer** (`src/core/`): Foundation components (THIS PHASE)
2. **Implementation Layer** (`implementations/<n>/`): Configuration files and schemas
3. **Service Layer** (`src/services/`): Modular services leveraging core + nostr-tools

## nostr-tools Library Reference

### Installation

```bash
pip install nostr-tools==1.4.0
```

### What nostr-tools Provides (DO NOT REIMPLEMENT)

**✅ Already in nostr-tools** - Import and use these:

```python
from nostr_tools import (
    # Key Management
    generate_keypair,      # Returns (private_key, public_key) as bytes
    to_bech32,            # Convert hex to bech32 (nsec/npub)
    to_hex,               # Convert bech32 to hex
    validate_keypair,     # Validate keypair correspondence
    
    # Event Operations
    Event,                # Event class with validation
    generate_event,       # Create and sign events (with optional PoW)
    
    # Relay & Client
    Relay,                # Relay representation
    Client,               # Async WebSocket client
    
    # Filtering & Streaming
    Filter,               # Event filtering
    fetch_events,         # Fetch stored events
    stream_events,        # Real-time event streaming (async generator)
    
    # Relay Testing (NIP-11/NIP-66)
    check_connectivity,   # Test connection (returns RTT, status)
    check_readability,    # Test read capability
    check_writability,    # Test write capability
    fetch_nip11,          # Fetch NIP-11 relay info
    fetch_relay_metadata, # Comprehensive metadata
)
```

**Event Class Methods**:
```python
event = Event.from_dict(event_dict)  # Create from dict
event_dict = event.to_dict()          # Serialize
event.is_valid                        # Signature validation
event.has_tag("t")                    # Check for tag
event.get_tag_values("t")             # Get tag values
```

**Client Usage**:
```python
relay = Relay("wss://relay.damus.io")
client = Client(relay, timeout=10, socks5_proxy_url=None)

# Context manager (recommended)
async with client:
    success = await client.publish(event)
    events = await fetch_events(client, filter_obj)
    
    # Real-time streaming
    async for event in stream_events(client, filter_obj):
        process(event)

# Check status
client.is_connected
client.active_subscriptions
```

**Relay Testing**:
```python
rtt_open, can_connect = await check_connectivity(client)
rtt_read, can_read = await check_readability(client)
rtt_write, can_write = await check_writability(client, private_key, public_key)

nip11_info = await fetch_nip11(client)
# nip11_info.name, .description, .supported_nips, .software, .version

metadata = await fetch_relay_metadata(client, private_key, public_key)
# metadata.nip11, metadata.nip66
```

## Your Task

Implement all core components in `src/core/` that integrate with nostr-tools. Each component should be production-ready, fully tested, and well-documented.

---

## Component 1: Connection Pool (`src/core/pool.py`)

### Purpose
Manage PostgreSQL database connections through PGBouncer with efficient pooling, retry logic, and async support.

### Requirements

**Class**: `ConnectionPool`

**Initialization**:
```python
def __init__(self, config: dict):
    """
    Initialize connection pool.
    
    Args:
        config: Configuration dictionary with:
            - database: {host, port, database, user, password, use_pgbouncer}
            - pool: {min_size, max_size, timeout, command_timeout}
            - retry: {max_attempts, initial_delay, max_delay, exponential_base}
    """
```

**Core Methods**:
```python
async def connect() -> None
async def disconnect() -> None
async def get_connection() -> asyncpg.Connection
async def execute(query: str, *args) -> Any
async def fetch_one(query: str, *args) -> Optional[Record]
async def fetch_all(query: str, *args) -> List[Record]
def is_connected() -> bool
```

**Features**:
- Automatic connection retry with exponential backoff
- Connection health checks
- Graceful degradation on connection loss
- Connection pool statistics (active, idle, waiting)
- Thread-safe for async contexts
- Proper connection cleanup on shutdown

**Configuration Support**:
```yaml
database:
  host: ${DB_HOST}
  port: ${DB_PORT}
  database: ${DB_NAME}
  user: ${DB_USER}
  password: ${DB_PASSWORD}
  use_pgbouncer: true
  
pool:
  min_size: 5
  max_size: 20
  timeout: 30
  command_timeout: 60
  
retry:
  max_attempts: 3
  initial_delay: 1.0
  max_delay: 10.0
  exponential_base: 2
```

**Dependencies**: `asyncpg`

---

## Component 2: Brotr Interface (`src/core/brotr.py`)

### Purpose
Provide standardized database operations interface, extending ConnectionPool and using nostr-tools for validation.

### Requirements

**Class**: `Brotr(ConnectionPool)`

**Core Methods**:

```python
# Event operations
async def insert_event(
    self,
    event: dict,  # Use Event.to_dict() from nostr-tools
    relay_id: int
) -> bool

async def insert_event_batch(
    self,
    events: List[Tuple[dict, int]]  # List of (event_dict, relay_id)
) -> int  # Returns number of inserted events

# Relay operations
async def insert_relay(
    self,
    url: str,
    network: str = 'clearnet'
) -> int  # Returns relay_id

async def insert_relay_batch(
    self,
    relays: List[Tuple[str, str]]  # List of (url, network)
) -> List[int]  # Returns relay_ids

# Metadata operations
async def insert_relay_metadata(
    self,
    relay_id: int,
    nip11_data: Optional[dict],  # From fetch_nip11()
    nip66_data: Optional[dict],  # From fetch_relay_metadata()
    connected: bool
) -> bool

async def insert_relay_metadata_batch(
    self,
    metadata_list: List[Tuple[int, Optional[dict], Optional[dict], bool]]
) -> int

# Cleanup operations
async def delete_orphan_events() -> int
async def delete_orphan_nip11() -> int
async def delete_orphan_nip66() -> int
```

**Helper Methods** (using nostr-tools for validation):
```python
async def get_relay_by_url(self, url: str) -> Optional[dict]
async def get_event_by_id(self, event_id: str) -> Optional[dict]
async def relay_exists(self, url: str) -> bool
async def event_exists(self, event_id: str) -> bool

# Validation helpers using nostr-tools
def validate_event(self, event_dict: dict) -> bool:
    """Use Event.from_dict() and check is_valid"""
    
def validate_relay_url(self, url: str) -> bool:
    """Use Relay(url).is_valid"""
```

**Implementation Details**:
- Each method calls corresponding stored procedure
- Proper transaction handling
- Batch operations should be atomic
- Use nostr-tools for validation before database insert
- Return meaningful error messages

**Configuration** (`implementations/<n>/config/core/brotr.yaml`):
```yaml
brotr:
  batch_size: 1000
  insert_timeout: 30
  cleanup_interval: 3600
  enable_event_validation: true  # Use nostr-tools Event validation
  enable_relay_validation: true  # Use nostr-tools Relay validation
```

**Dependencies**: `nostr-tools`, inherits from `ConnectionPool`

---

## Component 3: Service Base Classes (`src/core/services.py`)

### Purpose
Provide standardized service lifecycle, configuration, logging, and error handling for all services.

### Requirements

**Base Class**: `BaseService`

**Initialization**:
```python
def __init__(
    self,
    service_name: str,
    config_path: Optional[str] = None,
    implementation: str = "bigbrotr"
):
    """
    Initialize base service.
    
    Args:
        service_name: Name of the service (e.g., "monitor")
        config_path: Optional path to config file
        implementation: Implementation name (e.g., "bigbrotr")
    """
```

**Core Methods**:
```python
# Abstract method - must be implemented by subclasses
async def run(self) -> None

# Lifecycle methods
async def start(self) -> None
async def stop(self) -> None
async def shutdown(self) -> None

# Configuration
def load_config(self) -> dict
def get_config(self, key: str, default: Any = None) -> Any

# Database access
def get_brotr(self) -> Brotr

# Health checks
def is_healthy(self) -> bool
def get_status(self) -> dict
```

**Features**:
- Automatic config loading from `implementations/<n>/config/services/<service_name>.yaml`
- Environment variable substitution
- Signal handling (SIGTERM, SIGINT) for graceful shutdown
- Standardized logging via `logger.py`
- Database connection management
- Service status tracking

**Lifecycle Flow**:
```
[Load Config] → [Init Logger] → [Connect DB] → [Start] → [Run] → [Shutdown]
```

**Derived Class**: `LoopService(BaseService)`

**Additional Methods**:
```python
async def loop_iteration(self) -> None  # Abstract - implement loop logic
def should_continue(self) -> bool  # Check if loop should continue
async def on_error(self, error: Exception) -> None  # Error handler
```

**Configuration Support**:
```yaml
service:
  name: my_service
  enabled: true
  
loop:
  interval: 60  # seconds
  max_iterations: 0  # 0 = infinite
  error_retry_delay: 10
  max_consecutive_errors: 5

nostr_tools:
  socks5_proxy: null  # or socks5://127.0.0.1:9050
  timeout: 10
```

**Dependencies**: `brotr`, `config`, `logger`

---

## Component 4: Configuration Management (`src/core/config.py`)

### Purpose
Centralized configuration loading, validation, and environment variable handling.

### Requirements

**Functions**:

```python
def load_yaml_config(
    file_path: str,
    allow_env_vars: bool = True
) -> dict:
    """
    Load YAML file and substitute environment variables.
    Supports ${VAR_NAME} and ${VAR_NAME:default_value} syntax.
    """

def load_implementation_config(
    implementation: str,
    config_type: str,  # 'core', 'services', etc.
    config_name: str
) -> dict:
    """
    Load config from implementations/<implementation>/config/<type>/<name>.yaml
    """

def load_env_file(implementation: str) -> dict:
    """
    Load .env file from implementations/<implementation>/.env
    Returns dict of environment variables.
    """

def validate_config(
    config: dict,
    schema: dict
) -> Tuple[bool, List[str]]:
    """
    Validate config against schema.
    Returns (is_valid, error_messages).
    """

def merge_configs(*configs: dict, override_order: bool = True) -> dict:
    """Merge multiple configs. Later configs override earlier ones."""

def get_nested_config(
    config: dict,
    key_path: str,
    default: Any = None
) -> Any:
    """
    Get nested config value using dot notation.
    Example: get_nested_config(cfg, "database.pool.max_size", 10)
    """
```

**Environment Variable Substitution**:
- Support `${VAR_NAME}` syntax
- Support `${VAR_NAME:default}` with defaults
- Raise error if required variable is missing

**Error Handling**:
- `ConfigNotFoundError`: File not found
- `ConfigParseError`: YAML parsing failed
- `ConfigValidationError`: Validation failed
- `EnvironmentVariableError`: Required env var missing

**Dependencies**: `pyyaml`, `python-dotenv`

---

## Component 5: Logging System (`src/core/logger.py`)

### Purpose
Standardized, structured logging across all services.

### Requirements

**Functions**:

```python
def setup_logger(
    name: str,
    level: str = "INFO",
    format: str = "standard",  # 'standard', 'json', 'detailed'
    log_file: Optional[str] = None,
    rotation: Optional[dict] = None
) -> logging.Logger

def get_logger(name: str) -> logging.Logger

def log_exception(
    logger: logging.Logger,
    exception: Exception,
    context: Optional[dict] = None
) -> None

def log_metrics(
    logger: logging.Logger,
    metrics: dict,
    level: str = "INFO"
) -> None
```

**Log Formats**:

1. **Standard**:
```
2024-01-15 10:30:45 INFO [service_name] Message here
```

2. **JSON**:
```json
{
  "timestamp": "2024-01-15T10:30:45.123Z",
  "level": "INFO",
  "service": "service_name",
  "message": "Message here",
  "context": {}
}
```

3. **Detailed**:
```
2024-01-15 10:30:45.123 INFO [service_name:function_name:line_42] Message here
Context: {}
```

**Features**:
- Service-specific loggers
- Automatic context injection
- Log rotation support
- Multiple output handlers
- Configurable log levels per handler

**Dependencies**: `logging` (standard library)

---

## Component 6: Utilities (`src/core/utils.py`)

### Purpose
Shared helper functions that complement (not duplicate) nostr-tools.

### Requirements

**Note**: Do NOT reimplement functionality from nostr-tools. These utilities are for BigBrotr-specific operations.

**Functions**:

```python
# Batch processing helpers
def chunk_list(items: List[Any], chunk_size: int) -> Iterator[List[Any]]:
    """Split list into chunks for batch processing."""

def deduplicate_list(items: List[Any], key: Optional[Callable] = None) -> List[Any]:
    """Remove duplicates from list."""

# Timestamp utilities
def now_timestamp() -> int:
    """Current Unix timestamp."""

def to_iso_string(timestamp: int) -> str:
    """Convert Unix timestamp to ISO 8601 string."""

def from_iso_string(iso_str: str) -> int:
    """Parse ISO 8601 string to Unix timestamp."""

# Retry decorator
def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,)
):
    """Retry decorator with exponential backoff."""

# Data helpers
def compute_hash(data: dict) -> str:
    """Compute SHA256 hash of dict (for deduplication)."""

def short_hash(text: str, length: int = 8) -> str:
    """Generate short hash for display."""

# Network helpers (complement nostr-tools, don't duplicate)
async def test_http_reachable(url: str, timeout: float = 5.0) -> bool:
    """Test if HTTP(S) URL is reachable (for NIP-11 HTTP endpoint)."""
```

**Do NOT Include** (these are in nostr-tools):
- ❌ URL validation (use `Relay(url).is_valid`)
- ❌ Event ID validation (use `Event.from_dict()`)
- ❌ Pubkey validation (use `validate_keypair()`)
- ❌ Event signing (use `generate_event()`)
- ❌ Bech32 encoding/decoding (use `to_bech32()`, `to_hex()`)

**Dependencies**: `hashlib`, `datetime`

---

## Implementation Guidelines

### Code Quality Standards

1. **Type Hints**: Use comprehensive type hints
```python
from typing import Optional, List, Dict, Any, Tuple, Union, Iterator
```

2. **Docstrings**: Every function/class must have docstrings
```python
def function_name(param: str) -> bool:
    """
    Brief description.
    
    Args:
        param: Parameter description
        
    Returns:
        Return value description
        
    Raises:
        ExceptionType: When this exception is raised
    """
```

3. **Error Handling**: Use specific exception types
```python
class BigBrotrError(Exception):
    """Base exception for BigBrotr."""

class ConnectionPoolError(BigBrotrError):
    """Connection pool related errors."""
```

4. **Logging**: Log at appropriate levels
- DEBUG: Detailed diagnostic information
- INFO: General informational messages
- WARNING: Warning messages
- ERROR: Error messages for failures
- CRITICAL: Critical failures

5. **nostr-tools Integration**: Import and use, never reimplement
```python
# ✅ CORRECT
from nostr_tools import Event, generate_event
event_dict = generate_event(...)
event = Event.from_dict(event_dict)

# ❌ WRONG - Don't reimplement
def my_generate_event(...):  # NO! Use nostr-tools
    pass
```

### Project Structure

```
src/core/
├── __init__.py          # Export public API
├── pool.py              # ConnectionPool class
├── brotr.py             # Brotr interface
├── services.py          # BaseService, LoopService
├── config.py            # Configuration utilities
├── logger.py            # Logging utilities
├── utils.py             # Helper functions
└── exceptions.py        # Custom exceptions
```

### Dependencies

Create `src/core/requirements.txt`:
```
nostr-tools==1.4.0
asyncpg>=0.29.0
pyyaml>=6.0.1
python-dotenv>=1.0.0
```

### Testing Structure

```
tests/
├── core/
│   ├── test_pool.py
│   ├── test_brotr.py
│   ├── test_services.py
│   ├── test_config.py
│   ├── test_logger.py
│   └── test_utils.py
├── integration/
│   ├── test_nostr_tools_integration.py
│   └── test_database_integration.py
└── fixtures/
    └── test_config.yaml
```

---

## Testing Requirements

### Unit Tests

For each component:

1. **Happy Path**: Normal operation
2. **Error Cases**: All exception paths
3. **Edge Cases**: Boundary conditions
4. **Configuration**: Various config combinations
5. **Async Operations**: Proper async/await handling
6. **nostr-tools Integration**: Mocked external calls, real validation

### Example Test with nostr-tools

```python
import pytest
from nostr_tools import Event, generate_keypair, generate_event
from src.core.brotr import Brotr

class TestBrotr:
    
    @pytest.fixture
    async def brotr(self):
        config = {...}
        brotr = Brotr(config)
        await brotr.connect()
        yield brotr
        await brotr.disconnect()
    
    @pytest.mark.asyncio
    async def test_insert_event_with_validation(self, brotr):
        """Test event insertion with nostr-tools validation."""
        # Generate valid event using nostr-tools
        private_key, public_key = generate_keypair()
        event_dict = generate_event(
            private_key=private_key,
            public_key=public_key,
            kind=1,
            tags=[],
            content="Test event"
        )
        
        # Create Event object for validation
        event = Event.from_dict(event_dict)
        assert event.is_valid
        
        # Insert should succeed
        result = await brotr.insert_event(event_dict, relay_id=1)
        assert result is True
```

---

## Documentation Requirements

### README for Core

Create `src/core/README.md`:

```markdown
# BigBrotr Core Infrastructure

Foundation components for the BigBrotr system.

## Components

- **ConnectionPool**: Database connection management
- **Brotr**: BigBrotr-specific database operations
- **BaseService/LoopService**: Service base classes
- **Config**: Configuration loading and validation
- **Logger**: Structured logging
- **Utils**: Helper functions

## nostr-tools Integration

All Nostr protocol operations use `nostr-tools` library.
Never reimplement protocol functionality.

[Usage examples]
```

---

## Deliverables

Please provide:

1. **Complete implementation** of all 6 core components
2. **Comprehensive tests** for each component (>80% coverage)
3. **README.md** in `src/core/`
4. **requirements.txt** with pinned versions
5. **examples/** directory showing nostr-tools integration
6. **Configuration examples** for each component

## Success Criteria

✅ All components implemented and working
✅ Proper integration with nostr-tools (no protocol reimplementation)
✅ Test coverage >80% on all components
✅ All tests passing
✅ Comprehensive documentation
✅ Type hints throughout
✅ Proper error handling
✅ Clean code structure
✅ Ready for Phase 2 (services using nostr-tools)

---

## Critical Reminders

1. **Use nostr-tools for ALL Nostr protocol operations**
2. **Never reimplement**: Event creation, signing, validation, relay connections, filtering, etc.
3. **Focus on**: Database persistence, service orchestration, configuration, logging
4. **Test integration**: Mock external network calls, but test real nostr-tools validation
5. **Document clearly**: Show how to use nostr-tools with BigBrotr components

## Next Steps

After Phase 1 completion:
- Phase 2 will implement services using core components + nostr-tools
- Services will use nostr-tools Client for relay connections
- Services will use nostr-tools Event for validation
- Services will use nostr-tools filtering and streaming

Good luck! Build a solid foundation that properly leverages nostr-tools.
