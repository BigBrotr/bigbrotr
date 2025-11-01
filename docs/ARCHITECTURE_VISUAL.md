# Brotr Plugin Architecture - Visual Guide

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         BROTR PLUGIN ECOSYSTEM                       │
└─────────────────────────────────────────────────────────────────────┘

                              ┌──────────────┐
                              │    User      │
                              │ Application  │
                              └──────┬───────┘
                                     │
                                     │ import Brotr(mode='yourbrotr')
                                     ▼
                          ┌──────────────────────┐
                          │   Brotr (Facade)     │
                          │                      │
                          │  - insert_event()    │
                          │  - insert_relay()    │
                          │  - insert_metadata() │
                          └──────────┬───────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    │                │                │
                    ▼                ▼                ▼
         ┌────────────────┐ ┌──────────────┐ ┌────────────────┐
         │ BrotrFactory   │ │ RelayRepo    │ │ MetadataRepo   │
         │                │ │              │ │                │
         │ create_repo()  │ │ (Shared)     │ │ (Shared)       │
         └────────┬───────┘ └──────────────┘ └────────────────┘
                  │
                  │ mode='yourbrotr'
                  ▼
         ┌────────────────┐
         │ BrotrRegistry  │  ◄──────────── 🔌 PLUGIN SYSTEM
         │                │
         │ Auto-discover  │
         │ implementations│
         └────────┬───────┘
                  │
                  │ Scans implementations/ directory
                  │
      ┌───────────┼───────────┬───────────┬───────────┐
      │           │           │           │           │
      ▼           ▼           ▼           ▼           ▼
┌──────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
│ bigbrotr │ │lilbrotr │ │mediumbrotr│ │tinybrotr│ │yourbrotr│
│          │ │         │ │         │ │         │ │         │
│ Full     │ │ Minimal │ │ Tags    │ │ IDs     │ │ Custom  │
│ Storage  │ │ Storage │ │ Only    │ │ Only    │ │ Logic   │
└──────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘
     │            │            │            │            │
     └────────────┴────────────┴────────────┴────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │ PostgreSQL       │
                    │ Database         │
                    └──────────────────┘
```

---

## 🔌 Plugin Discovery Flow

```
┌──────────────────────────────────────────────────────────────┐
│ 1. APPLICATION STARTUP                                        │
└──────────────────────────────────────────────────────────────┘

    Import brotr_core.registry
             │
             ▼
    ┌──────────────────┐
    │ BrotrRegistry()  │  ◄─── Singleton created
    │ __init__         │
    └────────┬─────────┘
             │
             ▼
    _discover_implementations()
             │
             ▼
    Scan implementations/ directory
             │
             ├─► implementations/bigbrotr/     ✅ Valid
             ├─► implementations/lilbrotr/     ✅ Valid
             ├─► implementations/mediumbrotr/  ✅ Valid
             ├─► implementations/_template/    ❌ Skip (no valid EventRepository)
             └─► implementations/.hidden/      ❌ Skip (starts with .)
             │
             │ For each valid implementation:
             ▼
    ┌────────────────────────────────────┐
    │ _register_implementation_from_dir()│
    └────────────────────────────────────┘
             │
             ├─► Check sql/init.sql exists          ✅
             ├─► Check repositories/event_repository.py exists ✅
             ├─► _load_event_repository()
             │        │
             │        ├─► importlib.util.spec_from_file_location()
             │        ├─► module_from_spec()
             │        ├─► spec.loader.exec_module()
             │        ├─► Get EventRepository class
             │        └─► Validate extends BaseEventRepository
             │
             └─► Add to _implementations dict
             
    Result: _implementations = {
        'bigbrotr': BigbrotrEventRepository,
        'lilbrotr': LilbrotrEventRepository,
        'mediumbrotr': MediumbrotrEventRepository
    }

┌──────────────────────────────────────────────────────────────┐
│ 2. RUNTIME: Creating Brotr Instance                          │
└──────────────────────────────────────────────────────────────┘

    Brotr(mode='lilbrotr', ...)
             │
             ▼
    BrotrFactory.create_event_repository(pool, mode='lilbrotr')
             │
             ▼
    get_implementation('lilbrotr')  ◄─── Query registry
             │
             ▼
    LilbrotrEventRepository  ◄─── Return class
             │
             ▼
    repo = LilbrotrEventRepository(pool)  ◄─── Instantiate
             │
             └─► Return to Brotr instance
```

---

## 📁 Directory Structure

```
bigbrotr/
│
├── brotr_core/                        ◄─── Core Framework
│   │
│   ├── registry.py                    🆕 Plugin Discovery System
│   │   └── BrotrRegistry
│   │       ├── _discover_implementations()
│   │       ├── _register_implementation_from_dir()
│   │       ├── _load_event_repository()
│   │       ├── get(name)
│   │       ├── list()
│   │       └── exists(name)
│   │
│   ├── database/
│   │   ├── brotr.py                   ✏️  Factory Pattern
│   │   │   ├── Brotr (Facade)
│   │   │   └── BrotrFactory
│   │   │       └── create_event_repository()
│   │   │
│   │   ├── base_event_repository.py   🆕 Abstract Base
│   │   │   └── BaseEventRepository (ABC)
│   │   │       ├── insert_event()
│   │   │       ├── insert_event_batch()
│   │   │       └── delete_orphan_events()
│   │   │
│   │   ├── database_pool.py           ↔️  Shared
│   │   ├── relay_repository.py        ↔️  Shared
│   │   └── metadata_repository.py     ↔️  Shared
│   │
│   └── services/                      ↔️  Shared Services
│       ├── base_synchronizer.py
│       └── rate_limiter.py
│
├── implementations/                   🆕 Plugin Directory
│   │
│   ├── bigbrotr/                      ↔️  Moved from root
│   │   ├── sql/
│   │   │   └── init.sql               Full schema (tags + content)
│   │   └── repositories/
│   │       ├── __init__.py
│   │       └── event_repository.py    Full storage logic
│   │
│   ├── lilbrotr/                      ↔️  Moved from root
│   │   ├── sql/
│   │   │   └── init.sql               Minimal schema (no tags/content)
│   │   └── repositories/
│   │       ├── __init__.py
│   │       └── event_repository.py    Minimal storage logic
│   │
│   └── _template/                     🆕 Quick-Start Template
│       ├── README.md                  Usage guide
│       ├── config.yaml                Configuration template
│       ├── sql/
│       │   └── init.sql               Annotated SQL template
│       └── repositories/
│           ├── __init__.py
│           └── event_repository.py    Annotated Python template
│
├── deployments/                       ✏️  Deployment Configs
│   ├── bigbrotr/
│   │   ├── docker-compose.yml
│   │   └── .env.example
│   └── lilbrotr/
│       ├── docker-compose.yml
│       └── .env.example
│
├── shared/                            ↔️  Shared Utilities
│   ├── config/
│   │   └── config.py
│   └── utils/
│       └── functions.py
│
└── docs/                              📚 Documentation
    ├── HOW_TO_CREATE_BROTR.md         🆕 Developer Guide
    ├── QUICK_REFERENCE.md             🆕 Quick Reference
    ├── PLUGIN_ARCHITECTURE_SUMMARY.md 🆕 Architecture Overview
    ├── IMPLEMENTATION_COMPLETE.md     🆕 Completion Summary
    └── architecture/
        ├── BROTR_ARCHITECTURE.md
        └── COMPARISON.md
```

Legend:
- 🆕 New file/directory
- ✏️  Modified existing file
- ↔️  Moved from another location
- 📚 Documentation

---

## 🔄 Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ Event Insertion Flow                                             │
└─────────────────────────────────────────────────────────────────┘

1. Synchronizer Service
         │
         │ fetch events from relay
         ▼
2. await brotr.insert_event(event, relay)
         │
         ▼
3. Brotr Facade
         │
         │ delegate to event repository
         ▼
4. EventRepository (implementation-specific)
         │
         ├─► bigbrotr:    INSERT with tags + content
         ├─► lilbrotr:    INSERT without tags/content
         ├─► mediumbrotr: INSERT with tags only
         └─► yourbrotr:   YOUR CUSTOM LOGIC
         │
         ▼
5. Call stored procedure: insert_event(...)
         │
         ▼
6. PostgreSQL Database
         │
         ├─► INSERT INTO events (...)
         ├─► INSERT INTO relays (...)
         └─► INSERT INTO events_relays (...)
         │
         ▼
7. Data Persisted ✅
```

---

## 🎯 Implementation Selection

```
┌───────────────────────────────────────────────────────────────┐
│ How Implementation is Selected                                 │
└───────────────────────────────────────────────────────────────┘

Option 1: Environment Variable (Recommended)
────────────────────────────────────────────
    export BROTR_MODE=yourbrotr
         │
         ▼
    Brotr()  ◄─── Reads from os.environ['BROTR_MODE']
         │
         └─► Uses 'yourbrotr' implementation


Option 2: Explicit Parameter
────────────────────────────
    Brotr(mode='lilbrotr', ...)
         │
         └─► Uses 'lilbrotr' implementation


Option 3: Default (Fallback)
────────────────────────────
    Brotr()  ◄─── No mode specified, no env var
         │
         └─► Uses 'bigbrotr' (default)
```

---

## 🔍 Registry Lookup

```
get_implementation('yourbrotr')
         │
         ▼
┌────────────────────┐
│ BrotrRegistry      │
│                    │
│ _implementations = │
│ {                  │
│   'bigbrotr': ..., │
│   'lilbrotr': ..., │
│   'yourbrotr': ... │ ◄─── Found!
│ }                  │
└────────┬───────────┘
         │
         └─► Return EventRepository class
```

---

## 📊 Comparison Matrix

```
┌─────────────┬──────────┬──────────┬───────────┬──────────┐
│ Feature     │ Bigbrotr │ Lilbrotr │Mediumbrotr│Yourbrotr │
├─────────────┼──────────┼──────────┼───────────┼──────────┤
│ Event ID    │    ✅     │    ✅     │    ✅      │    ?     │
│ Pubkey      │    ✅     │    ✅     │    ✅      │    ?     │
│ Kind        │    ✅     │    ✅     │    ✅      │    ?     │
│ Tags        │    ✅     │    ❌     │    ✅      │    ?     │
│ Content     │    ✅     │    ❌     │    ❌      │    ?     │
│ Signature   │    ✅     │    ✅     │    ✅      │    ?     │
├─────────────┼──────────┼──────────┼───────────┼──────────┤
│ Size/Event  │  ~500B   │  ~100B   │   ~200B   │    ?     │
│ Use Case    │ Archival │ Indexing │ Tag Query │ Custom   │
│ RAM/1M evt  │   ~4GB   │  ~0.8GB  │   ~1.6GB  │    ?     │
└─────────────┴──────────┴──────────┴───────────┴──────────┘

Legend: ✅ Included  ❌ Excluded  ? Your choice!
```

---

## 🚀 Quick Start Visual

```
┌──────────────────────────────────────────────────────────────┐
│ Create Your Own Brotr in 3 Steps                             │
└──────────────────────────────────────────────────────────────┘

Step 1: Create Folder
──────────────────────
    mkdir -p implementations/yourbrotr/sql
    mkdir -p implementations/yourbrotr/repositories


Step 2: Add SQL Schema
───────────────────────
    nano implementations/yourbrotr/sql/init.sql
    
    CREATE TABLE events (
        id CHAR(64) PRIMARY KEY,
        -- YOUR CUSTOM FIELDS HERE
    );


Step 3: Add Repository
───────────────────────
    nano implementations/yourbrotr/repositories/event_repository.py
    
    class EventRepository(BaseEventRepository):
        async def insert_event(self, ...):
            # YOUR CUSTOM LOGIC HERE
            pass


✅ DONE! System automatically discovers your implementation!
═════════════════════════════════════════════════════════════

Test it:
    export BROTR_MODE=yourbrotr
    docker-compose up -d
```

---

## 🎨 Visual Summary

```
╔═══════════════════════════════════════════════════════════════╗
║                 BROTR PLUGIN ARCHITECTURE                      ║
╠═══════════════════════════════════════════════════════════════╣
║                                                               ║
║  🔌 AUTO-DISCOVERY    →  Scan implementations/ directory      ║
║  🏭 FACTORY PATTERN   →  Runtime implementation selection     ║
║  📦 CONVENTION-BASED  →  Standard folder structure            ║
║  ♾️  UNLIMITED IMPLS   →  Add folder = add implementation     ║
║  🚫 ZERO CORE CHANGES →  No modifications to core code        ║
║  ⚡ 30-MIN SETUP      →  From zero to deployed                ║
║                                                               ║
╠═══════════════════════════════════════════════════════════════╣
║                      CURRENT IMPLEMENTATIONS                  ║
╠═══════════════════════════════════════════════════════════════╣
║                                                               ║
║  📚 bigbrotr   →  Full archival (tags + content)              ║
║  🪶 lilbrotr   →  Minimal indexing (no tags/content)          ║
║  📋 _template  →  Quick-start template for new impls          ║
║  ✨ yourbrotr  →  Create your own!                            ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
```

---

**Visual guide created for Brotr Plugin Architecture**  
**See documentation for detailed information**

