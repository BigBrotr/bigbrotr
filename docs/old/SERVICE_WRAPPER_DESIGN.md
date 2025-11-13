# Service Wrapper Design - Architectural Decision

## 🎯 Problem

Dovevamo aggiungere funzionalità cross-cutting a `pool.py`:
- Logging
- Health checks
- Statistics
- Warmup
- Lifecycle management

**Domanda chiave**: Dove implementare queste feature?

## 💡 Soluzione: Generic Service Wrapper

Invece di aggiungere queste funzionalità direttamente a Pool (o Brotr, o altri servizi), abbiamo creato un **wrapper generico riusabile**.

### Perché è Meglio?

| Approccio | Pool.py con Feature | Service Wrapper |
|-----------|-------------------|-----------------|
| **Separation of Concerns** | ❌ Pool fa troppe cose | ✅ Pool = connessioni, Service = lifecycle |
| **Riusabilità** | ❌ Duplicare codice per ogni servizio | ✅ Stesso wrapper per tutti |
| **Testabilità** | ❌ Pool diventa complesso da testare | ✅ Pool e Service testabili separatamente |
| **Maintainability** | ❌ Pool cresce continuamente | ✅ Ogni componente ha responsabilità chiare |
| **Extensibility** | ❌ Modificare Pool per nuove feature | ✅ Estendere Service senza toccare Pool |

## 📐 Design Pattern: Decorator/Wrapper

```python
# Service wrappa qualsiasi servizio
pool_service = Service(pool, name="database_pool")
brotr_service = Service(brotr, name="brotr")
finder_service = Service(finder, name="finder")

# API uniforme per tutti
await pool_service.start()      # Logging, warmup, health checks
await brotr_service.start()     # Same!
await finder_service.start()    # Same!
```

## 🏗️ Architettura

### 1. Protocol: `ManagedService`

Definisce l'interfaccia minima che un servizio deve implementare:

```python
class ManagedService(Protocol):
    async def connect(self) -> None: ...  # o start()
    async def close(self) -> None: ...    # o stop()
    @property
    def is_connected(self) -> bool: ...   # o is_running
```

### 2. Service Wrapper: `Service[T]`

Wrapper generico che aggiunge funzionalità:

```python
class Service(Generic[T]):
    def __init__(self, instance: T, name: str, config: ServiceConfig):
        self._instance = instance  # Il servizio wrappato
        self._name = name
        self._config = config
        # ... logging, stats setup ...

    async def start(self):
        # 1. Log startup
        # 2. Call instance.connect()
        # 3. Warmup se abilitato
        # 4. Start health checks
        # 5. Update statistics

    async def stop(self):
        # 1. Log shutdown
        # 2. Stop health checks
        # 3. Call instance.close()
        # 4. Update statistics

    async def health_check(self) -> bool:
        # Check if instance is healthy

    def get_stats(self) -> Dict[str, Any]:
        # Return runtime statistics
```

### 3. Configurazione: `ServiceConfig`

```python
class ServiceConfig(BaseModel):
    enable_logging: bool = True
    log_level: str = "INFO"
    enable_health_checks: bool = True
    health_check_interval: float = 60.0
    enable_warmup: bool = False
    enable_stats: bool = True
```

## 🔧 Usage Examples

### Example 1: Wrap ConnectionPool

```python
from core.pool import ConnectionPool
from core.service import Service, ServiceConfig

# Create pool (not connected)
pool = ConnectionPool(host="localhost", database="mydb")

# Wrap in Service
config = ServiceConfig(
    enable_logging=True,
    enable_health_checks=True,
    health_check_interval=60.0,
)
service = Service(pool, name="database_pool", config=config)

# Use with context manager
async with service:
    # Service handles:
    # - Logging: "[database_pool] Starting service..."
    # - Connect: await pool.connect()
    # - Health checks: Every 60s
    # - Statistics: Uptime, health check success rate

    result = await service.instance.fetch("SELECT * FROM events")
    # service.instance → original pool

# Service handles graceful shutdown
```

### Example 2: Wrap Brotr

```python
from core.brotr import Brotr
from core.service import Service

brotr = Brotr(host="localhost", database="brotr")
service = Service(brotr, name="brotr_service")

async with service:
    # Access Brotr through service.instance
    await service.instance.insert_event(
        event_id="abc...",
        pubkey="def...",
        # ...
    )

    # Check health
    is_healthy = await service.health_check()

    # Get stats
    stats = service.get_stats()
    # {
    #   "name": "brotr_service",
    #   "uptime_seconds": 123.45,
    #   "health_checks": {
    #     "total": 5,
    #     "failed": 0,
    #     "success_rate": 100.0
    #   }
    # }
```

### Example 3: Multiple Services

```python
# Create services
pool1 = Service(ConnectionPool(...), name="pool_1")
pool2 = Service(ConnectionPool(...), name="pool_2")
brotr = Service(Brotr(...), name="brotr")

services = [pool1, pool2, brotr]

# Start all in parallel
await asyncio.gather(*[s.start() for s in services])

# Health check all
health_checks = await asyncio.gather(*[s.health_check() for s in services])
print(f"All healthy: {all(health_checks)}")

# Get stats from all
stats = [s.get_stats() for s in services]

# Stop all
await asyncio.gather(*[s.stop() for s in services])
```

### Example 4: Custom Stats

```python
service = Service(pool, name="db_pool")

async with service:
    # Execute query
    result = await service.instance.fetch("SELECT COUNT(*) FROM events")

    # Update custom stats
    service.update_custom_stats("total_events", result[0][0])
    service.update_custom_stats("last_query", datetime.now().isoformat())

    stats = service.get_stats()
    # {
    #   ...
    #   "custom": {
    #     "total_events": 42,
    #     "last_query": "2025-01-13T10:30:00"
    #   }
    # }
```

## 📊 Feature Comparison

### Without Service Wrapper

```python
# In pool.py
import logging

class ConnectionPool:
    def __init__(self, ...):
        # Pool logic
        self._logger = logging.getLogger(...)  # ❌ Logging in Pool
        self._stats = {...}  # ❌ Stats in Pool
        self._health_check_task = None  # ❌ Health checks in Pool

    async def connect(self):
        self._logger.info("Connecting...")  # ❌ Logging in Pool
        # ... connection logic ...
        self._start_health_checks()  # ❌ Health checks in Pool

    async def _health_check_loop(self):  # ❌ More code in Pool
        # ...

# Problem: Pool becomes bloated
# Must duplicate for Brotr, Finder, Monitor, etc.
```

### With Service Wrapper

```python
# In pool.py
class ConnectionPool:
    def __init__(self, ...):
        # ONLY pool logic ✅

    async def connect(self):
        # ONLY connection logic ✅

# In service.py (reusable!)
class Service:
    # ALL lifecycle management ✅
    # Logging ✅
    # Health checks ✅
    # Statistics ✅

# Usage
service = Service(pool, name="db_pool")  # ✅ Wrap any service
```

## 🎯 Benefits

### 1. **Single Responsibility Principle**
- **Pool**: Gestisce SOLO connessioni database
- **Brotr**: Gestisce SOLO business logic
- **Service**: Gestisce SOLO lifecycle, logging, monitoring

### 2. **Don't Repeat Yourself (DRY)**
```python
# Without wrapper: Duplicate per ogni servizio
class ConnectionPool:
    # ... logging, health checks, stats ...

class Brotr:
    # ... logging, health checks, stats ...  ❌ DUPLICATO

class Finder:
    # ... logging, health checks, stats ...  ❌ DUPLICATO

# With wrapper: Write once, use everywhere
service1 = Service(ConnectionPool(...))  ✅
service2 = Service(Brotr(...))  ✅
service3 = Service(Finder(...))  ✅
```

### 3. **Open/Closed Principle**
- Service è **aperto per estensione** (nuove feature nel wrapper)
- Pool/Brotr sono **chiusi per modifica** (non serve modificarli)

### 4. **Testability**
```python
# Test Pool in isolation
def test_pool_connection():
    pool = ConnectionPool(...)
    await pool.connect()
    assert pool.is_connected

# Test Service in isolation (con mock)
def test_service_logging():
    mock_pool = Mock(spec=ConnectionPool)
    service = Service(mock_pool, name="test")
    await service.start()
    mock_pool.connect.assert_called_once()
```

### 5. **Production Ready**
```python
# Development: No logging
service = Service(pool, config=ServiceConfig(enable_logging=False))

# Production: Full monitoring
service = Service(
    pool,
    config=ServiceConfig(
        enable_logging=True,
        enable_health_checks=True,
        enable_warmup=True,
        health_check_interval=30.0,
    )
)
```

## 🔄 Integration with Existing Code

### Pool.py - No Changes Needed ✅

```python
# pool.py stays clean
class ConnectionPool:
    async def connect(self): ...
    async def close(self): ...
    @property
    def is_connected(self) -> bool: ...
```

### Brotr.py - No Changes Needed ✅

```python
# brotr.py stays clean
class Brotr:
    def __init__(self):
        self.pool = ConnectionPool(...)  # Composition
    # ... business logic methods ...
```

### Usage - Just Wrap ✅

```python
# Before
pool = ConnectionPool(...)
await pool.connect()

# After (with Service)
pool = ConnectionPool(...)
service = Service(pool, name="db_pool")
await service.start()  # Adds logging, health checks, etc.
```

## 📈 Future Extensions

Service wrapper è facilmente estendibile:

### 1. Metrics Export
```python
class Service:
    def export_metrics(self) -> Dict[str, float]:
        """Export metrics in Prometheus format."""
        return {
            f"{self._name}_uptime_seconds": self._stats.uptime_seconds,
            f"{self._name}_health_check_success_rate": ...,
        }
```

### 2. Circuit Breaker
```python
class ServiceConfig:
    enable_circuit_breaker: bool = False
    failure_threshold: int = 5
    recovery_timeout: float = 60.0

class Service:
    async def start(self):
        if self._config.enable_circuit_breaker:
            self._circuit_breaker = CircuitBreaker(...)
```

### 3. Rate Limiting
```python
class ServiceConfig:
    enable_rate_limiting: bool = False
    max_requests_per_second: int = 100
```

### 4. Tracing/Observability
```python
class Service:
    def __init__(self, ..., tracer=None):
        self._tracer = tracer  # OpenTelemetry tracer

    async def start(self):
        with self._tracer.start_span(f"{self._name}.start"):
            # ...
```

## 🏆 Conclusion

Il **Service Wrapper** è la soluzione giusta perché:

1. ✅ **Mantiene Pool.py pulito** - Solo connection management
2. ✅ **Riusabile** - Stesso wrapper per tutti i servizi
3. ✅ **Testabile** - Componenti separati, facili da testare
4. ✅ **Estendibile** - Nuove feature nel wrapper, non nei servizi
5. ✅ **Professional** - Pattern usato in produzione (vedi Kubernetes, .NET Core)
6. ✅ **No Breaking Changes** - Pool e Brotr non cambiano

**Risultato**: Codice più pulito, più mantenibile, più professionale.

## 📚 Related Patterns

- **Decorator Pattern**: Service decora il servizio con funzionalità extra
- **Facade Pattern**: Service fornisce API semplificata per lifecycle management
- **Proxy Pattern**: Service fa da proxy aggiungendo logging/monitoring

## 🔗 Files

- Implementation: [src/core/service.py](src/core/service.py)
- Tests: [test_service_wrapper.py](test_service_wrapper.py)
- Usage with Pool: See examples above
- Usage with Brotr: See examples above
