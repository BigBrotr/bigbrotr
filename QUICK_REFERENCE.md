# Brotr Plugin System - Quick Reference

## 🚀 30-Second Overview

Brotr uses a **plugin architecture** where you can create custom storage strategies by adding a folder with 2 files. The system auto-discovers and registers your implementation.

---

## 📁 Required Structure

```
implementations/<your_name>/
├── sql/init.sql                    # Database schema
└── repositories/
    └── event_repository.py         # Storage logic (must define EventRepository class)
```

---

## ⚡ Quick Commands

```bash
# List available implementations
python3 -c "from brotr_core.registry import list_implementations; print(list_implementations())"

# Check if implementation exists
python3 -c "from brotr_core.registry import implementation_exists; print(implementation_exists('yourbrotr'))"

# Set active implementation
export BROTR_MODE=yourbrotr

# Deploy
cd deployments/yourbrotr
docker-compose up -d
```

---

## 📝 Minimal Implementation

### 1. SQL Schema (`sql/init.sql`)

```sql
-- Customize events table
CREATE TABLE events (
    id          CHAR(64)    PRIMARY KEY,
    pubkey      CHAR(64)    NOT NULL,
    created_at  BIGINT      NOT NULL,
    kind        INTEGER     NOT NULL,
    -- ADD YOUR FIELDS HERE
    sig         CHAR(128)   NOT NULL
);

-- Create insert procedure
CREATE OR REPLACE FUNCTION insert_event(
    p_event_id CHAR(64),
    p_pubkey CHAR(64),
    -- ... your parameters ...
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    -- Your insertion logic
END;
$$;
```

### 2. Event Repository (`repositories/event_repository.py`)

```python
import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from brotr_core.database.base_event_repository import BaseEventRepository
from nostr_tools import Event, Relay

class EventRepository(BaseEventRepository):
    async def insert_event(self, event: Event, relay: Relay, seen_at=None):
        if not self._validate_event(event) or not self._validate_relay(relay):
            raise ValueError("Invalid event or relay")
        
        query = "SELECT insert_event($1, $2, ...)"
        await self.pool.execute(query, event.id, event.pubkey, ...)
    
    async def insert_event_batch(self, events, relay, seen_at=None):
        # Batch logic
        pass
    
    async def delete_orphan_events(self):
        await self.pool.execute("SELECT delete_orphan_events()")
```

---

## 🎯 Implementation Patterns

### Pattern 1: Full Storage (like Bigbrotr)
```sql
CREATE TABLE events (
    id CHAR(64) PRIMARY KEY,
    pubkey CHAR(64) NOT NULL,
    created_at BIGINT NOT NULL,
    kind INTEGER NOT NULL,
    tags JSONB NOT NULL,      -- ✅ Include
    content TEXT NOT NULL,     -- ✅ Include
    sig CHAR(128) NOT NULL
);
```

### Pattern 2: Minimal Storage (like Lilbrotr)
```sql
CREATE TABLE events (
    id CHAR(64) PRIMARY KEY,
    pubkey CHAR(64) NOT NULL,
    created_at BIGINT NOT NULL,
    kind INTEGER NOT NULL,
    sig CHAR(128) NOT NULL
    -- ❌ No tags, no content
);
```

### Pattern 3: Selective Storage
```sql
CREATE TABLE events (
    id CHAR(64) PRIMARY KEY,
    pubkey CHAR(64) NOT NULL,
    created_at BIGINT NOT NULL,
    kind INTEGER NOT NULL,
    tags JSONB NOT NULL,       -- ✅ Include tags
    -- ❌ Exclude content
    sig CHAR(128) NOT NULL
);
```

### Pattern 4: Custom Fields
```sql
CREATE TABLE events (
    id CHAR(64) PRIMARY KEY,
    -- ... standard fields ...
    custom_field TEXT,         -- Your custom field
    processed BOOLEAN DEFAULT FALSE,
    priority INTEGER DEFAULT 0
);
```

---

## 🔧 Common Customizations

### Filter by Event Kind
```python
class EventRepository(BaseEventRepository):
    ALLOWED_KINDS = [0, 1, 3]  # Only metadata, notes, contacts
    
    async def insert_event(self, event, relay, seen_at=None):
        if event.kind not in self.ALLOWED_KINDS:
            return  # Skip
        # Normal insertion
```

### Add Custom Processing
```python
async def insert_event(self, event, relay, seen_at=None):
    # Pre-processing
    if event.kind == 1:  # Note
        await self._process_note(event)
    
    # Normal insertion
    await self.pool.execute(...)
    
    # Post-processing
    await self._update_statistics(event)
```

### Compression
```python
import zlib

async def insert_event(self, event, relay, seen_at=None):
    compressed_content = zlib.compress(event.content.encode())
    await self.pool.execute(query, ..., compressed_content, ...)
```

---

## 📊 Storage Estimates

| Implementation | Bytes/Event | 1M Events | 100M Events |
|---------------|-------------|-----------|-------------|
| Full (Bigbrotr) | ~500 | ~500 MB | ~50 GB |
| Minimal (Lilbrotr) | ~100 | ~100 MB | ~10 GB |
| Tags Only | ~200 | ~200 MB | ~20 GB |
| IDs Only | ~10 | ~10 MB | ~1 GB |

---

## 🔍 Validation

### Check Implementation is Valid
```python
from brotr_core.registry import get_implementation

repo_class = get_implementation('yourbrotr')
if repo_class is None:
    print("❌ Not found or invalid")
else:
    print(f"✅ Found: {repo_class}")
```

### Test Repository Methods
```python
from brotr_core.database.database_pool import DatabasePool

pool = DatabasePool(host, port, user, password, dbname)
await pool.connect()

repo = get_implementation('yourbrotr')(pool)

# Test validation
event = ...  # Nostr event
relay = ...  # Nostr relay

if repo._validate_event(event):
    print("✅ Event valid")
if repo._validate_relay(relay):
    print("✅ Relay valid")

await pool.close()
```

---

## 🐛 Troubleshooting

### Implementation Not Discovered
```bash
# Check directory structure
ls -la implementations/yourbrotr/
# Should have: sql/init.sql, repositories/event_repository.py

# Check class name
grep "class EventRepository" implementations/yourbrotr/repositories/event_repository.py
# Must be exactly "EventRepository"

# Check Python path
python3 -c "import sys; print(sys.path)"
```

### Import Errors
```python
# Add this to top of event_repository.py
import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
```

### SQL Errors
```sql
-- Check stored procedure signature matches repository calls
-- In init.sql:
CREATE OR REPLACE FUNCTION insert_event(p_event_id CHAR(64), ...

-- In event_repository.py:
await self.pool.execute("SELECT insert_event($1, $2, ...", event.id, ...)
```

---

## 📚 Full Documentation

- **Complete Guide**: `docs/HOW_TO_CREATE_BROTR.md`
- **Architecture**: `docs/architecture/BROTR_ARCHITECTURE.md`
- **Template**: `implementations/_template/`
- **Examples**: `implementations/bigbrotr/`, `implementations/lilbrotr/`

---

## 💡 Pro Tips

1. **Start from template**: `cp -r implementations/_template implementations/yourbrotr`
2. **Test incrementally**: Verify discovery before deploying
3. **Use type hints**: Helps catch errors early
4. **Document your schema**: Future you will thank you
5. **Add indexes**: For your specific access patterns

---

## ✅ Checklist

Creating a new implementation:

- [ ] Create directory: `implementations/<name>/`
- [ ] Copy template or create from scratch
- [ ] Define SQL schema: `sql/init.sql`
- [ ] Implement repository: `repositories/event_repository.py`
  - [ ] Class named `EventRepository`
  - [ ] Extends `BaseEventRepository`
  - [ ] Implements `insert_event()`
  - [ ] Implements `insert_event_batch()`
  - [ ] Implements `delete_orphan_events()`
- [ ] Add `__init__.py` (can be empty)
- [ ] Test discovery: `list_implementations()`
- [ ] Test loading: `get_implementation('<name>')`
- [ ] Configure deployment
- [ ] Deploy and test

---

**Need help?** See `docs/HOW_TO_CREATE_BROTR.md` for detailed guide!

