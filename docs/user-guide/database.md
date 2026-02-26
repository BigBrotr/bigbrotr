# Database Reference

Complete reference for BigBrotr's PostgreSQL schema, stored functions, materialized views, and indexes.

---

## Overview

BigBrotr uses PostgreSQL 16+ with a schema designed for high-throughput event archiving and relay monitoring. Key design principles:

- **Content-addressed storage**: Metadata documents are deduplicated by SHA-256 hash (~90% savings)
- **Bulk array parameters**: All mutations use stored functions with array parameters for batch efficiency
- **SECURITY INVOKER**: All functions execute with the caller's permissions (least privilege)
- **ON CONFLICT DO NOTHING**: All inserts are idempotent and safe to retry
- **Batched cleanup**: Cleanup functions process in configurable batch sizes to limit lock duration

Two schema variants exist:

| Variant | Event Storage | Materialized Views | Disk Usage |
|---------|--------------|-------------------|------------|
| **BigBrotr** | Full NIP-01 (id, pubkey, created_at, kind, tags, content, sig) | 11 views | 100% |
| **LilBrotr** | Metadata only (id, pubkey, created_at, kind, tagvalues) | 11 views | ~40% |

---

## Entity Relationship Diagram

```mermaid
erDiagram
    relay {
        TEXT url PK
        TEXT network
        BIGINT discovered_at
    }

    event {
        BYTEA id PK
        BYTEA pubkey
        BIGINT created_at
        INTEGER kind
        JSONB tags
        TEXT_ARRAY tagvalues
        TEXT content
        BYTEA sig
    }

    event_relay {
        BYTEA event_id PK_FK
        TEXT relay_url PK_FK
        BIGINT seen_at
    }

    metadata {
        BYTEA id PK
        TEXT type PK
        JSONB data
    }

    relay_metadata {
        TEXT relay_url PK_FK
        BIGINT generated_at PK
        TEXT metadata_type PK
        BYTEA metadata_id FK
    }

    service_state {
        TEXT service_name PK
        TEXT state_type PK
        TEXT state_key PK
        JSONB state_value
        BIGINT updated_at
    }

    relay ||--o{ event_relay : "has events"
    event ||--o{ event_relay : "seen at relays"
    relay ||--o{ relay_metadata : "has metadata"
    metadata ||--o{ relay_metadata : "referenced by"
```

---

## Extensions

| Extension | Purpose | BigBrotr | LilBrotr |
|-----------|---------|----------|----------|
| `btree_gin` | GIN index support for `TEXT[]` containment queries | Yes | Yes |
| `pg_stat_statements` | Query execution statistics tracking | Yes | No |

---

## Tables

### relay

Validated Nostr relays that have passed WebSocket connectivity testing.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `url` | TEXT | PRIMARY KEY | WebSocket URL (e.g., `wss://relay.example.com`) |
| `network` | TEXT | NOT NULL | Network type: `clearnet`, `tor`, `i2p`, `loki` |
| `discovered_at` | BIGINT | NOT NULL | Unix timestamp of discovery |

### event (BigBrotr)

Complete NIP-01 event storage with all fields preserved.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | BYTEA | PRIMARY KEY | SHA-256 event hash (32 bytes) |
| `pubkey` | BYTEA | NOT NULL | Author public key (32 bytes) |
| `created_at` | BIGINT | NOT NULL | Unix creation timestamp |
| `kind` | INTEGER | NOT NULL | NIP-01 event kind (0-65535) |
| `tags` | JSONB | NOT NULL | Tag array `[["e", "..."], ["p", "..."]]` |
| `tagvalues` | TEXT[] | GENERATED ALWAYS AS `tags_to_tagvalues(tags)` STORED | Single-char tag values for GIN indexing |
| `content` | TEXT | NOT NULL | Event content |
| `sig` | BYTEA | NOT NULL | Schnorr signature (64 bytes) |

!!! note
    The `tagvalues` column is a **generated stored column**, automatically computed from `tags` via the `tags_to_tagvalues()` function.

### event (LilBrotr)

Lightweight variant storing only essential metadata.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | BYTEA | PRIMARY KEY | SHA-256 event hash (32 bytes) |
| `pubkey` | BYTEA | NOT NULL | Author public key (32 bytes) |
| `created_at` | BIGINT | NOT NULL | Unix creation timestamp |
| `kind` | INTEGER | NOT NULL | NIP-01 event kind |
| `tagvalues` | TEXT[] | Regular column | Computed at insert time by `event_insert()`, not a generated column |

!!! note
    In LilBrotr, `tagvalues` is a **regular column** computed by `event_insert()` from the `tags` parameter, which is then discarded along with `content` and `sig`.

### event_relay

Junction table linking events to relays with first-seen timestamps.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `event_id` | BYTEA | PK (partial), FK -> event(id) ON DELETE CASCADE | Event hash |
| `relay_url` | TEXT | PK (partial), FK -> relay(url) ON DELETE CASCADE | Relay URL |
| `seen_at` | BIGINT | NOT NULL | Unix timestamp of first observation |

Primary key: `(event_id, relay_url)`.

### metadata

Content-addressed storage for NIP-11 and NIP-66 metadata documents.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | BYTEA | PK (partial) | SHA-256 content hash (32 bytes) |
| `type` | TEXT | PK (partial) | Check type (see MetadataType enum) |
| `data` | JSONB | NOT NULL | Complete JSON document |

Primary key: `(id, type)`. The SHA-256 hash is computed in the application layer. Multiple relays with identical metadata reference the same row, providing significant deduplication.

### relay_metadata

Time-series junction table linking relays to metadata snapshots.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `relay_url` | TEXT | PK (partial), FK -> relay(url) ON DELETE CASCADE | Relay URL |
| `generated_at` | BIGINT | PK (partial) | Unix timestamp of collection |
| `metadata_type` | TEXT | PK (partial) | Check type (see below) |
| `metadata_id` | BYTEA | NOT NULL, FK -> metadata(id, type) ON DELETE CASCADE | Content hash reference |

Primary key: `(relay_url, generated_at, metadata_type)`.

**Metadata types**: `nip11_info`, `nip66_rtt`, `nip66_ssl`, `nip66_geo`, `nip66_net`, `nip66_dns`, `nip66_http`

### service_state

Generic key-value store for per-service persistent state between restarts.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `service_name` | TEXT | PK (partial) | Service identifier |
| `state_type` | TEXT | PK (partial) | State category: `candidate`, `cursor`, `checkpoint`, `config` |
| `state_key` | TEXT | PK (partial) | Unique key within service+type |
| `state_value` | JSONB | NOT NULL, DEFAULT `{}` | Service-specific JSONB state value |
| `updated_at` | BIGINT | NOT NULL | Unix timestamp of last update |

Primary key: `(service_name, state_type, state_key)`.

---

## Foreign Keys and Cascade Deletes

All foreign keys use `ON DELETE CASCADE`:

| Child Table | Column | Parent Table | Cascade Effect |
|------------|--------|-------------|----------------|
| `event_relay` | `event_id` | `event(id)` | Deleting an event removes all relay associations |
| `event_relay` | `relay_url` | `relay(url)` | Deleting a relay removes all event associations |
| `relay_metadata` | `relay_url` | `relay(url)` | Deleting a relay removes all metadata snapshots |
| `relay_metadata` | `metadata_id` | `metadata(id)` | Deleting metadata removes all references |

!!! warning "Invariants"
    - Every event must have at least one relay in `event_relay` (enforced by `orphan_event_delete()`)
    - Orphaned metadata rows accumulate naturally; clean up with `orphan_metadata_delete()`

---

## Utility Functions

### tags_to_tagvalues(JSONB) -> TEXT[]

Extracts values from single-character tag keys in a Nostr event tags array.

```sql
LANGUAGE SQL IMMUTABLE RETURNS NULL ON NULL INPUT SECURITY INVOKER
```

**Example**: `[["e", "abc"], ["p", "def"], ["relay", "wss://..."]]` -> `ARRAY['abc', 'def']`

Tags with multi-character keys (like `relay`) are excluded.

---

## CRUD Functions

All CRUD functions share these properties:

- `LANGUAGE plpgsql` with `SECURITY INVOKER`
- Accept bulk array parameters for batch efficiency
- Use `ON CONFLICT DO NOTHING` for idempotent inserts
- Return `INTEGER` (rows affected) unless noted

### relay_insert

```sql
relay_insert(p_urls TEXT[], p_networks TEXT[], p_discovered_ats BIGINT[]) -> INTEGER
```

Bulk-inserts relay records. Existing relays (by URL) are silently skipped.

### event_insert

```sql
event_insert(
    p_event_ids BYTEA[], p_pubkeys BYTEA[], p_created_ats BIGINT[],
    p_kinds INTEGER[], p_tags JSONB[], p_content_values TEXT[], p_sigs BYTEA[]
) -> INTEGER
```

Bulk-inserts Nostr events. Duplicate events (by id) are silently skipped.

- **BigBrotr**: Stores all 7 fields
- **LilBrotr**: Accepts all 7 parameters for interface compatibility but stores only `id`, `pubkey`, `created_at`, `kind`, and computed `tagvalues`

### metadata_insert

```sql
metadata_insert(p_ids BYTEA[], p_metadata_types TEXT[], p_data JSONB[]) -> INTEGER
```

Bulk-inserts content-addressed metadata documents. Duplicate hashes are silently skipped.

### event_relay_insert

```sql
event_relay_insert(p_event_ids BYTEA[], p_relay_urls TEXT[], p_seen_ats BIGINT[]) -> INTEGER
```

Bulk-inserts event-relay junction records. Both event and relay must already exist.

### relay_metadata_insert

```sql
relay_metadata_insert(
    p_relay_urls TEXT[], p_metadata_ids BYTEA[],
    p_metadata_types TEXT[], p_generated_ats BIGINT[]
) -> INTEGER
```

Bulk-inserts relay-metadata junction records. Both relay and metadata must already exist.

### service_state_upsert

```sql
service_state_upsert(
    p_service_names TEXT[], p_state_types TEXT[], p_state_keys TEXT[],
    p_state_values JSONB[], p_updated_ats BIGINT[]
) -> VOID
```

Bulk upsert service state records. Uses `DISTINCT ON` within the batch to deduplicate, then `ON CONFLICT DO UPDATE SET` for full replacement semantics.

### service_state_get

```sql
service_state_get(
    p_service_name TEXT, p_state_type TEXT, p_state_key TEXT DEFAULT NULL
) -> TABLE(state_key TEXT, state_value JSONB, updated_at BIGINT)
```

Retrieves service state records. If `p_state_key` is NULL, returns all records for the service+type ordered by `updated_at ASC`.

### service_state_delete

```sql
service_state_delete(p_service_names TEXT[], p_state_types TEXT[], p_state_keys TEXT[]) -> INTEGER
```

Bulk-deletes service state records matching composite keys.

---

## Cascade Functions

Atomic multi-table operations that call Level 1 CRUD functions within a single transaction.

### event_relay_insert_cascade

```sql
event_relay_insert_cascade(
    p_event_ids BYTEA[], p_pubkeys BYTEA[], p_created_ats BIGINT[],
    p_kinds INTEGER[], p_tags JSONB[], p_content_values TEXT[], p_sigs BYTEA[],
    p_relay_urls TEXT[], p_relay_networks TEXT[], p_relay_discovered_ats BIGINT[],
    p_seen_ats BIGINT[]
) -> INTEGER
```

Atomically inserts relays, events, and event-relay junctions:

1. `relay_insert()` -- ensures relays exist
2. `event_insert()` -- ensures events exist
3. Inserts junction records with `DISTINCT ON (event_id, relay_url)` deduplication

Returns the number of junction rows inserted.

### relay_metadata_insert_cascade

```sql
relay_metadata_insert_cascade(
    p_relay_urls TEXT[], p_relay_networks TEXT[], p_relay_discovered_ats BIGINT[],
    p_metadata_ids BYTEA[], p_metadata_types TEXT[],
    p_metadata_data JSONB[], p_generated_ats BIGINT[]
) -> INTEGER
```

Atomically inserts relays, metadata documents, and relay-metadata junctions:

1. `relay_insert()` -- ensures relays exist
2. `metadata_insert()` -- ensures metadata exists
3. Inserts junction records

Returns the number of junction rows inserted.

---

## Cleanup Functions

All cleanup functions use configurable batch sizes to limit lock duration and WAL volume. They loop until fewer than `p_batch_size` rows are deleted, returning the total count.

### orphan_metadata_delete

```sql
orphan_metadata_delete(p_batch_size INTEGER DEFAULT 10000) -> INTEGER
```

Removes metadata records with no references in `relay_metadata`. Schedule: daily or after bulk deletions.

### orphan_event_delete

```sql
orphan_event_delete(p_batch_size INTEGER DEFAULT 10000) -> INTEGER
```

Removes events with no associated relays in `event_relay`. Enforces the invariant that every event must have at least one relay. Schedule: daily or after relay deletions.

---

## Materialized Views

All deployments (BigBrotr, LilBrotr) share the same 11 materialized views. All views use `REFRESH MATERIALIZED VIEW CONCURRENTLY` which requires a unique index.

### relay_metadata_latest

Latest metadata snapshot per relay and check type.

| Column | Type | Description |
|--------|------|-------------|
| `relay_url` | TEXT | Relay WebSocket URL |
| `metadata_type` | TEXT | Check type |
| `generated_at` | BIGINT | Timestamp of latest snapshot |
| `metadata_id` | BYTEA | Content-addressed hash |
| `data` | JSONB | Complete JSON document |

Uses `DISTINCT ON (relay_url, metadata_type) ... ORDER BY generated_at DESC` to select the most recent snapshot.

### event_stats

Global event counts and time-window metrics (single-row view).

| Column | Type | Description |
|--------|------|-------------|
| `singleton_key` | INTEGER | Always `1` (required for REFRESH CONCURRENTLY) |
| `event_count` | BIGINT | Total events |
| `unique_pubkeys` | BIGINT | Unique authors |
| `unique_kinds` | BIGINT | Unique event kinds |
| `earliest_event_timestamp` | BIGINT | MIN(created_at) |
| `latest_event_timestamp` | BIGINT | MAX(created_at) |
| `regular_event_count` | BIGINT | Kind 1, 2, 4-44, 1000-9999 |
| `replaceable_event_count` | BIGINT | Kind 0, 3, 10000-19999 |
| `ephemeral_event_count` | BIGINT | Kind 20000-29999 |
| `addressable_event_count` | BIGINT | Kind 30000-39999 |
| `event_count_last_1h` | BIGINT | Events from past 1 hour (snapshot at refresh) |
| `event_count_last_24h` | BIGINT | Events from past 24 hours (snapshot at refresh) |
| `event_count_last_7d` | BIGINT | Events from past 7 days (snapshot at refresh) |
| `event_count_last_30d` | BIGINT | Events from past 30 days (snapshot at refresh) |
| `events_per_day` | NUMERIC | Average events per day (total / elapsed days) |

### relay_stats

Per-relay event counts, averaged round-trip times, and NIP-11 info.

| Column | Type | Description |
|--------|------|-------------|
| `relay_url` | TEXT | Relay WebSocket URL |
| `network` | TEXT | Network type |
| `discovered_at` | BIGINT | Unix discovery timestamp |
| `first_event_timestamp` | BIGINT | Earliest event on relay |
| `last_event_timestamp` | BIGINT | Latest event on relay |
| `avg_rtt_open` | NUMERIC | Average RTT open phase (last 10 measurements) |
| `avg_rtt_read` | NUMERIC | Average RTT read phase (last 10 measurements) |
| `avg_rtt_write` | NUMERIC | Average RTT write phase (last 10 measurements) |
| `event_count` | BIGINT | Total events on relay |
| `unique_pubkeys` | BIGINT | Unique authors on relay |
| `unique_kinds` | BIGINT | Unique event kinds on relay |
| `nip11_name` | TEXT | Relay name from NIP-11 info (NULL if not available) |
| `nip11_software` | TEXT | Relay software from NIP-11 info (NULL if not available) |
| `nip11_version` | TEXT | Relay software version from NIP-11 info (NULL if not available) |

Uses `LATERAL` joins to fetch the last 10 NIP-66 RTT measurements and latest NIP-11 info per relay.

### kind_counts

Global event count distribution by NIP-01 kind with category labels.

| Column | Type | Description |
|--------|------|-------------|
| `kind` | INTEGER | Event kind |
| `event_count` | BIGINT | Total events of this kind |
| `unique_pubkeys` | BIGINT | Authors publishing this kind |
| `category` | TEXT | NIP-01 category: regular, replaceable, ephemeral, addressable, other |

### kind_counts_by_relay

Per-relay event kind distribution.

| Column | Type | Description |
|--------|------|-------------|
| `kind` | INTEGER | Event kind |
| `relay_url` | TEXT | Relay WebSocket URL |
| `event_count` | BIGINT | Events of this kind on this relay |
| `unique_pubkeys` | BIGINT | Authors publishing this kind to this relay |

### pubkey_counts

Global author activity metrics.

| Column | Type | Description |
|--------|------|-------------|
| `pubkey` | TEXT | Author public key (hex-encoded) |
| `event_count` | BIGINT | Total events by this author |
| `unique_kinds` | BIGINT | Event kinds authored |
| `first_event_timestamp` | BIGINT | Earliest event |
| `last_event_timestamp` | BIGINT | Latest event |

### pubkey_counts_by_relay

Per-relay author activity metrics. Only includes pubkeys with 2+ events per relay to avoid cartesian explosion at scale.

| Column | Type | Description |
|--------|------|-------------|
| `relay_url` | TEXT | Relay WebSocket URL |
| `pubkey` | TEXT | Author public key (hex-encoded) |
| `event_count` | BIGINT | Events by this author on this relay (min 2) |
| `unique_kinds` | BIGINT | Kinds published to this relay |
| `first_event_timestamp` | BIGINT | Earliest event on relay |
| `last_event_timestamp` | BIGINT | Latest event on relay |

### network_stats

Aggregate statistics per network type (clearnet, tor, i2p, loki).

| Column | Type | Description |
|--------|------|-------------|
| `network` | TEXT | Network type |
| `relay_count` | BIGINT | Relays on this network |
| `event_count` | BIGINT | Total events across relays |
| `unique_pubkeys` | BIGINT | Unique authors across relays |
| `unique_kinds` | BIGINT | Unique event kinds across relays |

### relay_software_counts

NIP-11 software distribution across relays. Only includes relays that report a software field.

| Column | Type | Description |
|--------|------|-------------|
| `software` | TEXT | Software name from NIP-11 |
| `version` | TEXT | Software version (or "unknown" if not reported) |
| `relay_count` | BIGINT | Relays running this software |

Depends on `relay_metadata_latest` -- refresh that view first.

### supported_nip_counts

NIP support distribution from NIP-11 info. Counts how many relays support each NIP number.

| Column | Type | Description |
|--------|------|-------------|
| `nip` | INTEGER | NIP number |
| `relay_count` | BIGINT | Relays supporting this NIP |

Depends on `relay_metadata_latest` -- refresh that view first.

### event_daily_counts

Daily event aggregation for time-series analysis (UTC).

| Column | Type | Description |
|--------|------|-------------|
| `day` | DATE | UTC date |
| `event_count` | BIGINT | Events on this day |
| `unique_pubkeys` | BIGINT | Unique authors on this day |
| `unique_kinds` | BIGINT | Unique event kinds on this day |

---

## Refresh Functions

All return `VOID` with `SECURITY INVOKER`. Each uses `REFRESH MATERIALIZED VIEW CONCURRENTLY`. The **Refresher** service (`python -m bigbrotr refresher`) orchestrates these functions automatically, refreshing each view individually in dependency order with per-view logging and error isolation.

| Function | Target View | Recommended Schedule |
|----------|-------------|---------------------|
| `relay_metadata_latest_refresh()` | relay_metadata_latest | Daily |
| `event_stats_refresh()` | event_stats | Hourly |
| `relay_stats_refresh()` | relay_stats | Daily |
| `kind_counts_refresh()` | kind_counts | Daily |
| `kind_counts_by_relay_refresh()` | kind_counts_by_relay | Daily |
| `pubkey_counts_refresh()` | pubkey_counts | Daily |
| `pubkey_counts_by_relay_refresh()` | pubkey_counts_by_relay | Daily |
| `network_stats_refresh()` | network_stats | Daily |
| `relay_software_counts_refresh()` | relay_software_counts | Daily |
| `supported_nip_counts_refresh()` | supported_nip_counts | Daily |
| `event_daily_counts_refresh()` | event_daily_counts | Daily |

### all_statistics_refresh()

Refreshes all materialized views in dependency order:

1. `relay_metadata_latest_refresh()` (first: relay_software_counts and supported_nip_counts depend on it)
2. `event_stats_refresh()`
3. `relay_stats_refresh()`
4. `kind_counts_refresh()`
5. `kind_counts_by_relay_refresh()`
6. `pubkey_counts_refresh()`
7. `pubkey_counts_by_relay_refresh()`
8. `network_stats_refresh()`
9. `event_daily_counts_refresh()`
10. `relay_software_counts_refresh()`
11. `supported_nip_counts_refresh()`

!!! warning
    Schedule during a daily maintenance window -- this operation has high I/O cost.

---

## Indexes

### BigBrotr Table Indexes

#### event

| Index | Columns | Type | Purpose |
|-------|---------|------|---------|
| PK | `id` | BTREE | Primary key |
| `idx_event_created_at` | `created_at DESC` | BTREE | Global timeline queries |
| `idx_event_kind` | `kind` | BTREE | Kind filtering |
| `idx_event_kind_created_at` | `kind, created_at DESC` | BTREE | Kind + timeline |
| `idx_event_pubkey_created_at` | `pubkey, created_at DESC` | BTREE | Author timeline |
| `idx_event_pubkey_kind_created_at` | `pubkey, kind, created_at DESC` | BTREE | Author + kind + timeline |
| `idx_event_tagvalues` | `tagvalues` | GIN | Tag containment (`@>`) |
| `idx_event_created_at_id` | `created_at ASC, id ASC` | BTREE | Cursor-based pagination |

#### event_relay Indexes

| Index | Columns | Type | Purpose |
|-------|---------|------|---------|
| PK | `event_id, relay_url` | BTREE | Composite primary key |
| `idx_event_relay_relay_url` | `relay_url` | BTREE | All events from a relay |
| `idx_event_relay_seen_at` | `seen_at DESC` | BTREE | Recently discovered events |
| `idx_event_relay_relay_url_seen_at` | `relay_url, seen_at DESC` | BTREE | Synchronizer cursor progress |

#### relay_metadata Indexes

| Index | Columns | Type | Purpose |
|-------|---------|------|---------|
| PK | `relay_url, generated_at, metadata_type` | BTREE | Composite primary key |
| `idx_relay_metadata_generated_at` | `generated_at DESC` | BTREE | Recent health checks |
| `idx_relay_metadata_metadata_id` | `metadata_id` | BTREE | Content-addressed lookups |
| `idx_relay_metadata_relay_url_metadata_type_generated_at` | `relay_url, metadata_type, generated_at DESC` | BTREE | Latest metadata per relay+type |

#### service_state Indexes

| Index | Columns | Type | Purpose |
|-------|---------|------|---------|
| PK | `service_name, state_type, state_key` | BTREE | Covers single and double-prefix queries |
| `idx_service_state_candidate_network` | `state_value ->> 'network'` (partial) | BTREE | Validator: filter candidates by network |

!!! note
    The partial index on `service_state` has a WHERE clause: `WHERE service_name = 'validator' AND state_type = 'candidate'`.

### Materialized View Indexes

All materialized views require at least one unique index for `REFRESH CONCURRENTLY`. These indexes are shared across all deployments.

| Index | View | Columns | Unique |
|-------|------|---------|--------|
| `idx_relay_metadata_latest_pk` | relay_metadata_latest | `relay_url, metadata_type` | Yes |
| `idx_relay_metadata_latest_type` | relay_metadata_latest | `metadata_type` | No |
| `idx_event_stats_singleton_key` | event_stats | `singleton_key` | Yes |
| `idx_relay_stats_relay_url` | relay_stats | `relay_url` | Yes |
| `idx_relay_stats_network` | relay_stats | `network` | No |
| `idx_kind_counts_kind` | kind_counts | `kind` | Yes |
| `idx_kind_counts_by_relay_composite` | kind_counts_by_relay | `kind, relay_url` | Yes |
| `idx_kind_counts_by_relay_relay` | kind_counts_by_relay | `relay_url` | No |
| `idx_pubkey_counts_pubkey` | pubkey_counts | `pubkey` | Yes |
| `idx_pubkey_counts_by_relay_composite` | pubkey_counts_by_relay | `pubkey, relay_url` | Yes |
| `idx_pubkey_counts_by_relay_relay` | pubkey_counts_by_relay | `relay_url` | No |
| `idx_network_stats_network` | network_stats | `network` | Yes |
| `idx_relay_software_counts_composite` | relay_software_counts | `software, version` | Yes |
| `idx_supported_nip_counts_nip` | supported_nip_counts | `nip` | Yes |
| `idx_event_daily_counts_day` | event_daily_counts | `day` | Yes |

### LilBrotr Table Indexes

LilBrotr has a simpler table index set optimized for its lightweight event schema. Materialized view indexes are identical to BigBrotr (see above).

| Index | Table | Columns | Type |
|-------|-------|---------|------|
| `idx_event_created_at` | event | `created_at DESC` | BTREE |
| `idx_event_kind` | event | `kind` | BTREE |
| `idx_event_kind_created_at` | event | `kind, created_at DESC` | BTREE |
| `idx_event_pubkey` | event | `pubkey` | BTREE |
| `idx_event_tagvalues` | event | `tagvalues` | GIN |
| `idx_event_relay_relay_url` | event_relay | `relay_url` | BTREE |
| `idx_event_relay_event_id` | event_relay | `event_id` | BTREE |
| `idx_relay_metadata_generated_at` | relay_metadata | `generated_at DESC` | BTREE |
| `idx_relay_metadata_metadata_id` | relay_metadata | `metadata_id` | BTREE |
| `idx_relay_metadata_relay_url_metadata_type_generated_at` | relay_metadata | `relay_url, metadata_type, generated_at DESC` | BTREE |
| `idx_service_state_candidate_network` | service_state | `state_value ->> 'network'` (partial) | BTREE |

---

## Schema Initialization

SQL files execute in alphabetical order via Docker's `/docker-entrypoint-initdb.d/`:

### BigBrotr

| File | Content |
|------|---------|
| `00_extensions.sql` | `btree_gin`, `pg_stat_statements` |
| `01_functions_utility.sql` | `tags_to_tagvalues()` |
| `02_tables.sql` | 6 tables with full event schema |
| `03_functions_crud.sql` | 10 CRUD + 2 cascade functions |
| `04_functions_cleanup.sql` | 3 cleanup functions |
| `05_views.sql` | Regular views (reserved) |
| `06_materialized_views.sql` | 11 materialized views |
| `07_functions_refresh.sql` | 12 refresh functions |
| `08_indexes.sql` | Table and materialized view indexes |
| `99_verify.sql` | Verification queries |

### LilBrotr

| File | Content |
|------|---------|
| `00_extensions.sql` | `btree_gin`, `pg_stat_statements` |
| `01_functions_utility.sql` | `tags_to_tagvalues()` |
| `02_tables.sql` | 6 tables with lightweight event schema |
| `03_functions_crud.sql` | 10 CRUD + 2 cascade functions |
| `04_functions_cleanup.sql` | 2 cleanup functions |
| `05_views.sql` | Regular views (reserved) |
| `06_materialized_views.sql` | 11 materialized views |
| `07_functions_refresh.sql` | 12 refresh functions |
| `08_indexes.sql` | Table and materialized view indexes |
| `99_verify.sql` | Verification queries |

---

## Deployment-Specific Schemas

**BigBrotr** (full archive): stores tags JSONB, generated tagvalues, content TEXT.

```sql
CREATE TABLE event (
    id BYTEA PRIMARY KEY,
    pubkey BYTEA NOT NULL,
    created_at BIGINT NOT NULL,
    kind INTEGER NOT NULL,
    tags JSONB NOT NULL,
    tagvalues TEXT[] GENERATED ALWAYS AS (tags_to_tagvalues(tags)) STORED,
    content TEXT NOT NULL,
    sig BYTEA NOT NULL
);
```

**LilBrotr** (lightweight): omits tags, content, sig for ~60% disk savings. Tagvalues is a regular column computed at insert time.

```sql
CREATE TABLE event (
    id BYTEA PRIMARY KEY,
    pubkey BYTEA NOT NULL,
    created_at BIGINT NOT NULL,
    kind INTEGER NOT NULL,
    tagvalues TEXT[]
);
```

---

## Function Summary

| Category | Count | Functions |
|----------|-------|-----------|
| Utility | 1 | `tags_to_tagvalues` |
| CRUD (Level 1) | 8 | `relay_insert`, `event_insert`, `metadata_insert`, `event_relay_insert`, `relay_metadata_insert`, `service_state_upsert`, `service_state_get`, `service_state_delete` |
| CRUD (Level 2) | 2 | `event_relay_insert_cascade`, `relay_metadata_insert_cascade` |
| Cleanup | 2 | `orphan_metadata_delete`, `orphan_event_delete` |
| Refresh | 12 | 11 individual + `all_statistics_refresh` |
| **Total** | **25** | |

---

## Maintenance Schedule

| Task | Frequency | Command |
|------|-----------|---------|
| Refresh all views | Daily | `SELECT all_statistics_refresh()` |
| Refresh event_stats | Hourly | `SELECT event_stats_refresh()` |
| Delete orphan events | Daily | `SELECT orphan_event_delete()` |
| Delete orphan metadata | Daily | `SELECT orphan_metadata_delete()` |
| VACUUM ANALYZE | Weekly | `VACUUM ANALYZE event; VACUUM ANALYZE event_relay;` |

---

## Related Documentation

- [Architecture](architecture.md) -- System architecture and module reference
- [Services](services.md) -- Deep dive into the six independent services
- [Configuration](configuration.md) -- YAML configuration reference
- [Monitoring](monitoring.md) -- Prometheus metrics, alerting, and Grafana dashboards
