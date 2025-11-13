# Brotr Dependency Injection Refactoring

## 🎯 Problem

`Brotr.__init__()` aveva **28 parametri totali**:
- **16 parametri ConnectionPool** (duplicati da pool.py)
- **12 parametri Brotr-specific** (batch, procedures, timeouts)

```python
# PRIMA (28 parametri!)
def __init__(
    self,
    # 16 ConnectionPool parameters
    host: Optional[str] = None,
    port: Optional[int] = None,
    database: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    min_size: Optional[int] = None,
    max_size: Optional[int] = None,
    max_queries: Optional[int] = None,
    max_inactive_connection_lifetime: Optional[float] = None,
    acquisition_timeout: Optional[float] = None,
    max_attempts: Optional[int] = None,
    initial_delay: Optional[float] = None,
    max_delay: Optional[float] = None,
    exponential_backoff: Optional[bool] = None,
    application_name: Optional[str] = None,
    timezone: Optional[str] = None,
    # 12 Brotr parameters
    default_batch_size: Optional[int] = None,
    max_batch_size: Optional[int] = None,
    # ... altri 10 parametri Brotr
):
    # Crea ConnectionPool internamente
    self.pool = ConnectionPool(
        host=host,
        port=port,
        # ... tutti i 16 parametri
    )
```

### Problemi di questo approccio:

1. ❌ **Violazione DRY**: Parametri duplicati da ConnectionPool
2. ❌ **Violazione Composition**: Brotr crea il pool invece di riceverlo
3. ❌ **Difficile Testing**: Non si può facilmente mockare il pool
4. ❌ **Scarsa Riusabilità**: Non si può condividere un pool tra servizi
5. ❌ **API Confusa**: 28 parametri! Chi ricorda cosa fa ognuno?
6. ❌ **Maintenance Nightmare**: Modificare ConnectionPool → modificare anche Brotr

---

## ✅ Solution: Dependency Injection

Invece di far creare il pool a Brotr, **lo iniettiamo come dipendenza**.

```python
# DOPO (12 parametri - 57% in meno!)
def __init__(
    self,
    pool: Optional[ConnectionPool] = None,  # DI invece di 16 parametri!
    # Solo 11 parametri Brotr-specific
    default_batch_size: Optional[int] = None,
    max_batch_size: Optional[int] = None,
    insert_event_proc: Optional[str] = None,
    insert_relay_proc: Optional[str] = None,
    insert_relay_metadata_proc: Optional[str] = None,
    delete_orphan_events_proc: Optional[str] = None,
    delete_orphan_nip11_proc: Optional[str] = None,
    delete_orphan_nip66_proc: Optional[str] = None,
    query_timeout: Optional[float] = None,
    procedure_timeout: Optional[float] = None,
    batch_timeout: Optional[float] = None,
):
    # Usa pool iniettato o crea default
    self.pool = pool or ConnectionPool()
```

---

## 📊 Comparison: Before vs After

| Aspect | Before (Composition) | After (Dependency Injection) |
|--------|---------------------|------------------------------|
| **Parameters** | 28 (16 pool + 12 brotr) | 12 (1 pool + 11 brotr) |
| **Pool Creation** | ❌ Brotr crea il pool | ✅ Iniettato o default |
| **Code Duplication** | ❌ 16 parametri duplicati | ✅ Zero duplicazione |
| **Testing** | ❌ Difficile mockare | ✅ Facile iniettare mock |
| **Pool Sharing** | ❌ Impossibile | ✅ `Brotr(pool=shared_pool)` |
| **API Clarity** | ⚠️ 28 parametri confusi | ✅ 12 parametri chiari |
| **Maintenance** | ❌ Modifiche su 2 file | ✅ Solo ConnectionPool |
| **Flexibility** | ⚠️ Solo costruzione diretta | ✅ DI + factories + defaults |

---

## 🔧 Usage Examples

### 1. Default Pool (Nessuna configurazione)

```python
# Usa ConnectionPool con tutti i defaults
brotr = Brotr(default_batch_size=200)

async with brotr.pool:
    await brotr.insert_event(...)
```

### 2. Dependency Injection (Pool Custom)

```python
# Crea pool personalizzato
pool = ConnectionPool(
    host="localhost",
    database="brotr",
    min_size=10,
    max_size=50
)

# Inietta nel Brotr
brotr = Brotr(pool=pool, default_batch_size=200)

# Pool è condiviso - stessa istanza!
assert brotr.pool is pool  # True
```

### 3. From Dictionary (Pool creato internamente)

```python
config = {
    "pool": {
        "database": {"host": "localhost", "database": "brotr"},
        "limits": {"min_size": 5, "max_size": 20}
    },
    "batch": {"default_batch_size": 200}
}

brotr = Brotr.from_dict(config)
# Pool creato da from_dict() e iniettato
```

### 4. From YAML (Unified Config)

```yaml
# brotr.yaml
pool:
  database:
    host: localhost
    database: brotr
  limits:
    min_size: 5
    max_size: 20

batch:
  default_batch_size: 200

procedures:
  insert_event: insert_event

timeouts:
  query: 60.0
  procedure: 90.0
```

```python
brotr = Brotr.from_yaml("config/brotr.yaml")
# Pool creato dal YAML e iniettato
```

### 5. Pool Sharing (Riuso tra servizi)

```python
# Crea un pool condiviso
shared_pool = ConnectionPool(
    host="localhost",
    database="brotr",
    min_size=20,
    max_size=100
)

# Condividi tra più servizi
brotr = Brotr(pool=shared_pool)
finder = Finder(pool=shared_pool)  # Stesso pool!
monitor = Monitor(pool=shared_pool)  # Stesso pool!

# Un solo pool per tutti → risorse ottimizzate
```

---

## 🧪 Testing Benefits

### Before: Difficile Mockare

```python
# ❌ Impossibile mockare il pool
brotr = Brotr(host="localhost", database="test")
# Pool creato internamente - come si mocka?
```

### After: Facile Mockare

```python
# ✅ Facile iniettare mock
mock_pool = Mock(spec=ConnectionPool)
mock_pool.acquire.return_value = mock_connection

brotr = Brotr(pool=mock_pool)  # Inject mock!

# Test isolato senza database reale
await brotr.insert_event(...)
mock_pool.acquire.assert_called_once()
```

---

## 📈 Factory Methods Implementation

Il refactoring **mantiene backward compatibility** con `from_dict()` e `from_yaml()`.

### `from_dict()` Implementation

```python
@classmethod
def from_dict(cls, config_dict: Dict[str, Any]) -> "Brotr":
    """Create Brotr from dictionary configuration."""
    # Crea pool da config se presente
    pool = None
    if "pool" in config_dict:
        pool = ConnectionPool.from_dict(config_dict["pool"])

    # Estrai config Brotr
    batch_config = config_dict.get("batch", {})
    procedures_config = config_dict.get("procedures", {})
    timeouts_config = config_dict.get("timeouts", {})

    # Crea Brotr con pool iniettato
    return cls(
        pool=pool,  # Inject pool or None for default
        default_batch_size=batch_config.get("default_batch_size"),
        max_batch_size=batch_config.get("max_batch_size"),
        # ... altri parametri Brotr
    )
```

**Key Points**:
- ✅ `pool` opzionale nel dict
- ✅ Se presente, crea `ConnectionPool.from_dict()` e inietta
- ✅ Se assente, passa `None` → Brotr usa default pool
- ✅ YAML strutturato (pool, batch, procedures, timeouts separati)

---

## 🎯 Benefits Summary

### 1. **DRY (Don't Repeat Yourself)**
```python
# Prima: 16 parametri duplicati da ConnectionPool
# Dopo: 1 parametro pool (zero duplicazione)
```

### 2. **Separation of Concerns**
```python
# ConnectionPool: Gestisce SOLO connessioni
# Brotr: Gestisce SOLO business logic
# Nessuna confusione di responsabilità
```

### 3. **Dependency Injection**
```python
# Follower del principio:
# "Dipendi da astrazioni, non da implementazioni concrete"
brotr = Brotr(pool=my_pool)  # Inversion of Control
```

### 4. **Testability**
```python
# Facile iniettare mock/stub per test
brotr = Brotr(pool=mock_pool)
```

### 5. **Flexibility**
```python
# Opzione A: Default pool
brotr = Brotr()

# Opzione B: Custom pool
brotr = Brotr(pool=ConnectionPool(...))

# Opzione C: From config
brotr = Brotr.from_yaml("config.yaml")

# Opzione D: Shared pool
brotr1 = Brotr(pool=shared_pool)
brotr2 = Brotr(pool=shared_pool)
```

### 6. **Maintainability**
```python
# Modifiche a ConnectionPool → zero impatto su Brotr
# Brotr non ha bisogno di sapere come funziona ConnectionPool
```

### 7. **Reduced API Surface**
```python
# Prima: 28 parametri (overwhelming!)
# Dopo: 12 parametri (manageable)
# Riduzione del 57%!
```

---

## 🔄 Migration Guide

Se hai codice esistente che usa la vecchia API:

### Before (Old API)
```python
# ❌ Non funziona più
brotr = Brotr(
    host="localhost",
    database="brotr",
    min_size=5,
    max_size=20,
    default_batch_size=200
)
```

### After (New API - Option 1: DI)
```python
# ✅ Crea pool separatamente, poi inietta
pool = ConnectionPool(
    host="localhost",
    database="brotr",
    min_size=5,
    max_size=20
)
brotr = Brotr(pool=pool, default_batch_size=200)
```

### After (New API - Option 2: from_dict)
```python
# ✅ Usa from_dict (più pulito)
config = {
    "pool": {
        "database": {"host": "localhost", "database": "brotr"},
        "limits": {"min_size": 5, "max_size": 20}
    },
    "batch": {"default_batch_size": 200}
}
brotr = Brotr.from_dict(config)
```

### After (New API - Option 3: YAML)
```python
# ✅ Usa YAML (best practice)
# brotr.yaml:
# pool:
#   database: {host: localhost, database: brotr}
#   limits: {min_size: 5, max_size: 20}
# batch: {default_batch_size: 200}

brotr = Brotr.from_yaml("config/brotr.yaml")
```

---

## 📚 Design Patterns Applied

### 1. **Dependency Injection**
```python
# Brotr non crea il pool - lo riceve come dipendenza
brotr = Brotr(pool=my_pool)
```

### 2. **Inversion of Control (IoC)**
```python
# Controllo invertito: chi crea Brotr decide quale pool usare
# Brotr non decide - riceve la decisione dall'esterno
```

### 3. **Factory Pattern**
```python
# from_dict() e from_yaml() sono factory methods
# Creano pool internamente quando necessario
brotr = Brotr.from_yaml("config.yaml")
```

### 4. **Composition over Inheritance**
```python
# Brotr HAS-A pool (composition)
# Non Brotr IS-A pool (inheritance)
brotr.pool.acquire()  # Delega al pool
```

---

## ✅ Tests

Tutti i test passano dopo il refactoring:

```bash
$ python3 test_composition.py
======================================================================
Testing Brotr with Composition Pattern (Dependency Injection)
======================================================================

1. Dependency Injection (Custom Pool):
   Pool object is same? True  ✓

2. From Dictionary (Unified Structure):
   ✓

3. Composition Pattern Verification:
   ✓

4. All Defaults:
   ✓

======================================================================
All tests passed! ✓
======================================================================
```

---

## 🎓 Key Takeaways

1. ✅ **Parametri ridotti da 28 a 12** (57% reduction)
2. ✅ **Zero duplicazione** di parametri ConnectionPool
3. ✅ **Dependency Injection** per migliore testabilità
4. ✅ **Pool condivisibile** tra servizi
5. ✅ **Backward compatible** con `from_dict()` e `from_yaml()`
6. ✅ **Più flessibile**: DI + factories + defaults
7. ✅ **Più manutenibile**: modifiche a Pool non impattano Brotr
8. ✅ **Best practices**: DI, IoC, Composition, Factory Pattern

---

## 📝 Files Modified

- **[src/core/brotr.py](src/core/brotr.py)**: Implementazione Dependency Injection
- **[test_composition.py](test_composition.py)**: Test aggiornati per nuova API

---

## 🔗 Related Documentation

- [Pool Improvements Summary](POOL_IMPROVEMENTS_SUMMARY.md)
- [Brotr Improvements Summary](BROTR_IMPROVEMENTS_SUMMARY.md)
- [Service Wrapper Design](SERVICE_WRAPPER_DESIGN.md)
