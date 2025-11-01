# How to Create Your Own Brotr Implementation

## Overview

The Brotr architecture uses a **plugin system** that allows any developer to create custom implementations by simply adding a folder with the required files. The system automatically discovers and registers your implementation—no core code changes needed!

**Time to create**: 30 minutes  
**Difficulty**: Easy  
**Prerequisites**: Basic Python knowledge, understanding of SQL

---

## Quick Start: 3 Steps to Create Your Brotr

### Step 1: Create Implementation Folder

```bash
cd implementations/
mkdir yourbrotr
cd yourbrotr
mkdir -p sql repositories
```

### Step 2: Create Database Schema

```bash
# Create sql/init.sql with your custom schema
touch sql/init.sql
```

### Step 3: Create Event Repository

```bash
# Create repositories/event_repository.py
touch repositories/event_repository.py
```

**That's it!** The system automatically discovers and registers your implementation.

---

## Detailed Guide

### 1. Understanding the Structure

Every Brotr implementation must follow this structure:

```
implementations/
└── yourbrotr/                    # Your implementation name (lowercase)
    ├── sql/
    │   └── init.sql              # Database schema (REQUIRED)
    ├── repositories/
    │   └── event_repository.py   # Event storage strategy (REQUIRED)
    └── config.yaml               # Configuration (OPTIONAL)
```

**Required Files**:
- `sql/init.sql` - PostgreSQL database schema
- `repositories/event_repository.py` - Python class defining storage strategy

**Optional Files**:
- `config.yaml` - Implementation-specific configuration
- `README.md` - Documentation for your implementation
- `migrations/` - Database migration scripts

### 2. Create Your Database Schema

File: `implementations/yourbrotr/sql/init.sql`

Your schema must include these core tables:
- `relays` - Relay registry
- `events` - Event storage (customize as needed!)
- `events_relays` - Junction table
- `nip11`, `nip66`, `relay_metadata` - Metadata tables

**Example**: Minimal schema template

```sql
-- Create core tables (copy from implementations/_template/sql/init.sql)
-- Customize the events table to fit your needs!

CREATE TABLE events (
    id          CHAR(64)    PRIMARY KEY,
    pubkey      CHAR(64)    NOT NULL,
    created_at  BIGINT      NOT NULL,
    kind        INTEGER     NOT NULL,
    -- ADD YOUR CUSTOM FIELDS HERE
    -- tags        JSONB       NOT NULL,  -- Optional
    -- content     TEXT        NOT NULL,  -- Optional
    -- custom_field TEXT,                  -- Add anything!
    sig         CHAR(128)   NOT NULL
);

-- Create stored procedure for event insertion
CREATE OR REPLACE FUNCTION insert_event(
    p_event_id              CHAR(64),
    p_pubkey                CHAR(64),
    p_created_at            BIGINT,
    p_kind                  INTEGER,
    -- ADD PARAMETERS FOR YOUR CUSTOM FIELDS
    p_sig                   CHAR(128),
    p_relay_url             TEXT,
    p_relay_network         TEXT,
    p_relay_inserted_at     BIGINT,
    p_seen_at               BIGINT
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    -- Insert your custom event structure
    INSERT INTO events (id, pubkey, created_at, kind, sig)
    VALUES (p_event_id, p_pubkey, p_created_at, p_kind, p_sig)
    ON CONFLICT (id) DO NOTHING;
    
    -- Insert relay and association (standard)
    INSERT INTO relays (url, network, inserted_at)
    VALUES (p_relay_url, p_relay_network, p_relay_inserted_at)
    ON CONFLICT (url) DO NOTHING;
    
    INSERT INTO events_relays (event_id, relay_url, seen_at)
    VALUES (p_event_id, p_relay_url, p_seen_at)
    ON CONFLICT (event_id, relay_url) DO NOTHING;
END;
$$;
```

**Pro Tip**: Copy `implementations/_template/sql/init.sql` as a starting point!

### 3. Create Your Event Repository

File: `implementations/yourbrotr/repositories/event_repository.py`

Your repository must:
1. Be named `EventRepository` (exact name!)
2. Extend `BaseEventRepository`
3. Implement required methods

**Template**:

```python
"""YourBrotr Event Repository - Custom event storage implementation.

Describe your storage strategy here:
- What fields do you store?
- What's the use case?
- What are the performance characteristics?
"""
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import time
import logging
from typing import List, Optional

from nostr_tools import Event, Relay
from brotr_core.database.base_event_repository import BaseEventRepository


class EventRepository(BaseEventRepository):
    """Event repository for yourbrotr (custom storage strategy)."""

    async def insert_event(
        self, 
        event: Event, 
        relay: Relay, 
        seen_at: Optional[int] = None
    ) -> None:
        """Insert a single event with your custom logic.
        
        Args:
            event: Nostr Event object
            relay: Relay where event was seen
            seen_at: Timestamp when seen (defaults to now)
        """
        if not self._validate_event(event):
            raise ValueError("Invalid event")
        if not self._validate_relay(relay):
            raise ValueError("Invalid relay")

        if seen_at is None:
            seen_at = int(time.time())

        # Call your custom stored procedure
        query = "SELECT insert_event($1, $2, $3, $4, $5, $6, $7, $8, $9)"
        await self.pool.execute(
            query,
            event.id,
            event.pubkey,
            event.created_at,
            event.kind,
            # Add your custom fields here
            event.sig,
            relay.url,
            relay.network,
            relay.inserted_at,
            seen_at
        )

    async def insert_event_batch(
        self, 
        events: List[Event], 
        relay: Relay, 
        seen_at: Optional[int] = None
    ) -> None:
        """Insert a batch of events efficiently."""
        if not self._validate_relay(relay):
            raise ValueError("Invalid relay")

        if seen_at is None:
            seen_at = int(time.time())

        # Batch insert logic
        query = "SELECT insert_event($1, $2, $3, $4, $5, $6, $7, $8, $9)"
        
        for event in events:
            if not self._validate_event(event):
                logging.warning(f"⚠️ Skipping invalid event: {event}")
                continue

            try:
                await self.pool.execute(
                    query,
                    event.id,
                    event.pubkey,
                    event.created_at,
                    event.kind,
                    # Add your custom fields
                    event.sig,
                    relay.url,
                    relay.network,
                    relay.inserted_at,
                    seen_at
                )
            except Exception as e:
                logging.warning(f"⚠️ Failed to insert event {event.id}: {e}")
                continue

    async def delete_orphan_events(self) -> None:
        """Delete orphan events from the database."""
        query = "SELECT delete_orphan_events()"
        await self.pool.execute(query)
        logging.info("✅ Orphan events deleted")
```

**Key Points**:
- Class **must** be named `EventRepository`
- **Must** extend `BaseEventRepository`
- **Must** implement `insert_event()`, `insert_event_batch()`, `delete_orphan_events()`
- Use `self.pool.execute()` for database operations
- Use `self._validate_event()` and `self._validate_relay()` from base class

### 4. Test Your Implementation

```bash
# Set your implementation as active
export BROTR_MODE=yourbrotr

# Run Python to test discovery
python3 << EOF
from brotr_core.registry import list_implementations
print("Available implementations:", list_implementations())
EOF

# Should output: Available implementations: ['bigbrotr', 'lilbrotr', 'yourbrotr']
```

### 5. Deploy Your Implementation

**Update docker-compose.yml**:

```yaml
synchronizer:
  environment:
    - BROTR_MODE=yourbrotr  # Use your implementation!
    - POSTGRES_DB_INIT_PATH=../../implementations/yourbrotr/sql/init.sql
```

**Start services**:

```bash
cd deployments/yourbrotr  # Create this directory
cp ../bigbrotr/docker-compose.yml .
# Edit to set BROTR_MODE=yourbrotr
docker-compose up -d
```

---

## Example Implementations

### Example 1: MediumBrotr (Stores Tags but Not Content)

**Use case**: Tag-based queries without content storage overhead

```sql
-- implementations/mediumbrotr/sql/init.sql
CREATE TABLE events (
    id          CHAR(64)    PRIMARY KEY,
    pubkey      CHAR(64)    NOT NULL,
    created_at  BIGINT      NOT NULL,
    kind        INTEGER     NOT NULL,
    tags        JSONB       NOT NULL,  -- ✅ Include tags
    tagvalues   TEXT[]      GENERATED ALWAYS AS (tags_to_tagvalues(tags)) STORED,
    -- NO content                       -- ❌ Exclude content
    sig         CHAR(128)   NOT NULL
);
```

**Storage**: ~40% of Bigbrotr  
**Use case**: Tag-based filtering without content analysis

### Example 2: TinyBrotr (Only Event IDs and Relays)

**Use case**: Event existence tracking only

```sql
-- implementations/tinybrotr/sql/init.sql
CREATE TABLE events (
    id          CHAR(64)    PRIMARY KEY
    -- That's it! Absolute minimum
);
```

**Storage**: ~1% of Bigbrotr  
**Use case**: Ultra-lightweight existence verification

### Example 3: KindBrotr (Only Specific Event Kinds)

**Use case**: Filter by event kind at storage level

```python
# implementations/kindbrotr/repositories/event_repository.py
class EventRepository(BaseEventRepository):
    """Stores only kinds 0, 1, 3 (metadata, notes, contacts)."""
    
    ALLOWED_KINDS = [0, 1, 3]
    
    async def insert_event(self, event, relay, seen_at=None):
        if event.kind not in self.ALLOWED_KINDS:
            return  # Skip this event
        
        # Normal insertion logic for allowed kinds
        # ...
```

**Storage**: ~20% of Bigbrotr (depending on filter)  
**Use case**: Focus on specific event types

---

## Best Practices

### 1. Documentation
Always include a README.md in your implementation:

```markdown
# YourBrotr

## Description
Brief description of your storage strategy.

## Use Cases
- When to use this implementation
- What problems it solves

## Storage Characteristics
- Storage per event: ~X bytes
- Performance: X events/second
- Resource requirements: Y GB RAM, Z cores

## Custom Features
- Feature 1
- Feature 2
```

### 2. Testing
Create tests for your implementation:

```python
# implementations/yourbrotr/tests/test_event_repository.py
import pytest
from implementations.yourbrotr.repositories.event_repository import EventRepository

async def test_insert_event():
    # Test your implementation
    pass
```

### 3. Configuration
Add optional config.yaml for implementation-specific settings:

```yaml
# implementations/yourbrotr/config.yaml
name: yourbrotr
version: 1.0.0
description: Custom event storage strategy
author: Your Name

# Custom settings
settings:
  max_event_size: 1000000
  enable_compression: true
  custom_field: value
```

---

## Advanced: Custom Indexes

Add custom indexes for your use case:

```sql
-- Optimize for your access patterns
CREATE INDEX idx_events_custom ON events USING btree (custom_field);
CREATE INDEX idx_events_custom_gin ON events USING gin (custom_jsonb_field);
```

---

## Advanced: Multiple Storage Strategies

You can even create implementations with multiple storage strategies:

```
implementations/
└── hybridbrotr/
    ├── sql/
    │   ├── init.sql                    # Creates both tables
    ├── repositories/
    │   ├── event_repository.py         # Routes to appropriate strategy
    │   ├── full_storage.py             # For important events
    │   └── minimal_storage.py          # For less important events
```

---

## Troubleshooting

### Implementation Not Discovered

**Problem**: Your implementation doesn't appear in `list_implementations()`

**Solutions**:
1. Check folder name is lowercase: `yourbrotr` not `YourBrotr`
2. Verify `sql/init.sql` exists
3. Verify `repositories/event_repository.py` exists
4. Check Python path: `echo $PYTHONPATH`

### Import Errors

**Problem**: `ImportError: cannot import name 'BaseEventRepository'`

**Solution**: Add path setup to your repository file:

```python
import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
```

### Class Not Found

**Problem**: `AttributeError: module has no attribute 'EventRepository'`

**Solution**: Ensure your class is named **exactly** `EventRepository`:

```python
class EventRepository(BaseEventRepository):  # ✅ Correct
class YourBrotrRepository(BaseEventRepository):  # ❌ Wrong
class EventRepo(BaseEventRepository):  # ❌ Wrong
```

---

## Reference: Complete File Checklist

```
implementations/yourbrotr/
├── sql/
│   └── init.sql                          ✅ REQUIRED
├── repositories/
│   └── event_repository.py               ✅ REQUIRED
│       - Must define: class EventRepository(BaseEventRepository)
│       - Must implement: insert_event()
│       - Must implement: insert_event_batch()
│       - Must implement: delete_orphan_events()
├── config.yaml                           ⭕ OPTIONAL
├── README.md                             ⭕ RECOMMENDED
├── tests/                                ⭕ RECOMMENDED
│   └── test_event_repository.py
└── migrations/                           ⭕ OPTIONAL
    └── 001_initial.sql
```

---

## Template Files

Copy from `implementations/_template/` to get started quickly:

```bash
cp -r implementations/_template implementations/yourbrotr
cd implementations/yourbrotr
# Edit sql/init.sql and repositories/event_repository.py
```

---

## Community Implementations

Share your implementation with the community!

1. Create your implementation
2. Add documentation
3. Test thoroughly
4. Submit a Pull Request
5. Your implementation will be available to everyone!

**Example Community Implementations**:
- `torbrotr` - Tor-only relay storage
- `kindbrotr` - Filter by event kind
- `compressedbrotr` - Compressed content storage
- `encryptedbrotr` - Encrypted event storage

---

## Support

- **Documentation**: `docs/architecture/BROTR_ARCHITECTURE.md`
- **Examples**: Browse `implementations/` directory
- **Issues**: GitHub Issues for questions
- **Template**: `implementations/_template/` for quick start

---

## Summary

Creating a new Brotr implementation is **easy**:

1. ✅ Create folder: `implementations/yourbrotr/`
2. ✅ Add SQL schema: `sql/init.sql`
3. ✅ Add event repository: `repositories/event_repository.py`
4. ✅ Test: `export BROTR_MODE=yourbrotr`
5. ✅ Deploy: Update docker-compose.yml

**The system automatically discovers and registers your implementation!**

No core code changes needed. No registration forms. Just add files and go!

---

**Happy creating! 🚀**

