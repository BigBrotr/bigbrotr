# Database Reference

Complete reference for BigBrotr's PostgreSQL schema, stored functions, derived tables, reporting views, and indexes.

---

## Overview

BigBrotr uses PostgreSQL 18+ with a schema designed for high-throughput event archiving and relay monitoring. Key design principles:

- **Content-addressed storage**: Metadata documents are deduplicated by SHA-256 hash (~90% savings)
- **Bulk array parameters**: All mutations use stored functions with array parameters for batch efficiency
- **SECURITY INVOKER**: All functions execute with the caller's permissions (least privilege)
- **ON CONFLICT DO NOTHING**: All inserts are idempotent and safe to retry
- **Batched cleanup**: Cleanup functions process in configurable batch sizes to limit lock duration

Two schema variants exist:

| Variant | Event Storage | Derived Tables | Regular Views | Disk Usage |
|---------|--------------|----------------|---------------|------------|
| **BigBrotr** | Full NIP-01 (id, pubkey, created_at, kind, tags, content, sig) | 5 current-state tables + 17 analytics/rank tables | 0 | 100% |
| **LilBrotr** | All 8 columns, with tags/content/sig nullable and always NULL | Same derived schema | 0 | ~40% |

---

## Schema Map

The only enforced foreign keys are in the core archive graph. Current-state, analytics, and NIP-85 tables are regular tables maintained by refresh functions and ranker exports.

| Layer | Tables | Source |
|-------|--------|--------|
| Core archive | `relay`, `event`, `event_relay`, `metadata`, `relay_metadata`, `service_state` | Services and cascade insert functions |
| Current state | `relay_metadata_current`, `events_replaceable_current`, `events_addressable_current`, `contact_lists_current`, `contact_list_edges_current` | Refresher, `08_functions_refresh_current.sql` |
| Core analytics | `pubkey_kind_stats`, `pubkey_relay_stats`, `relay_kind_stats`, `pubkey_stats`, `kind_stats`, `relay_stats`, `daily_counts`, `relay_software_counts`, `supported_nip_counts` | Refresher, `09_functions_refresh_analytics.sql` |
| NIP-85 facts | `nip85_pubkey_stats`, `nip85_event_stats`, `nip85_addressable_stats`, `nip85_identifier_stats` | Refresher, `09_functions_refresh_analytics.sql` |
| NIP-85 ranks | `nip85_pubkey_ranks`, `nip85_event_ranks`, `nip85_addressable_ranks`, `nip85_identifier_ranks` | Ranker snapshot exports |

### Core Entity Relationship Diagram

```mermaid
erDiagram
    relay {
        text url PK
        text network
        bigint discovered_at
    }

    event {
        bytea id PK
        bytea pubkey
        bigint created_at
        integer kind
        jsonb tags
        text-arr tagvalues
        text content
        bytea sig
    }

    event_relay {
        bytea event_id FK
        text relay_url FK
        bigint seen_at
    }

    metadata {
        bytea id PK
        text type PK
        jsonb data
    }

    relay_metadata {
        text relay_url FK
        bigint generated_at PK
        text metadata_type FK
        bytea metadata_id FK
    }

    service_state {
        text service_name PK
        text state_type PK
        text state_key PK
        jsonb state_value
    }

    relay ||--o{ event_relay : "has events"
    event ||--o{ event_relay : "seen at relays"
    relay ||--o{ relay_metadata : "has metadata"
    metadata ||--o{ relay_metadata : "referenced by"
```

### Derived Data Flow

```mermaid
flowchart LR
    event["event"]
    event_relay["event_relay"]
    relay["relay"]
    relay_metadata["relay_metadata"]
    metadata["metadata"]

    relay_metadata_current["relay_metadata_current"]
    replaceable["events_replaceable_current"]
    addressable["events_addressable_current"]
    contacts["contact_lists_current"]
    edges["contact_list_edges_current"]

    core_stats["core analytics stats"]
    relay_meta_stats["relay software / supported NIP counts"]
    nip85_stats["NIP-85 stats tables"]
    ranks["NIP-85 rank tables"]

    relay_metadata --> relay_metadata_current
    metadata --> relay_metadata_current
    relay --> core_stats
    event --> replaceable
    event --> addressable
    event --> core_stats
    event --> nip85_stats
    event_relay --> replaceable
    event_relay --> addressable
    event_relay --> core_stats
    event_relay --> nip85_stats
    relay_metadata_current --> relay_meta_stats
    replaceable --> contacts
    contacts --> edges
    edges --> nip85_stats
    nip85_stats --> ranks
    edges --> ranks
```

---

## Extensions

| Extension | Purpose | BigBrotr | LilBrotr |
|-----------|---------|----------|----------|
| `btree_gin` | GIN index support for `TEXT[]` containment queries | Yes | Yes |
| `pg_stat_statements` | Query execution statistics tracking | Yes | Yes |

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
| `tagvalues` | TEXT[] | NOT NULL | Single-char tag values for GIN indexing, computed at insert time |
| `content` | TEXT | NOT NULL | Event content |
| `sig` | BYTEA | NOT NULL | Schnorr signature (64 bytes) |

!!! note
    The `tagvalues` column is computed at insert time by `event_insert()` via the `tags_to_tagvalues()` function.

### event (LilBrotr)

Lightweight variant with all 8 columns but tags, content, and sig are nullable and always NULL.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | BYTEA | PRIMARY KEY | SHA-256 event hash (32 bytes) |
| `pubkey` | BYTEA | NOT NULL | Author public key (32 bytes) |
| `created_at` | BIGINT | NOT NULL | Unix creation timestamp |
| `kind` | INTEGER | NOT NULL | NIP-01 event kind |
| `tags` | JSONB | Nullable, always NULL | Not stored in lightweight mode |
| `tagvalues` | TEXT[] | NOT NULL | Computed at insert time by `event_insert()` |
| `content` | TEXT | Nullable, always NULL | Not stored in lightweight mode |
| `sig` | BYTEA | Nullable, always NULL | Not stored in lightweight mode |

!!! note
    In LilBrotr, `tags`, `content`, and `sig` columns exist but are always NULL. The `tagvalues` column is computed by `event_insert()` from the incoming tags before the JSON is discarded. `tagvalues` preserves the original order of single-character tags and stores only each tag's first value (`tag[1]`), which allows most analytics logic to stay shared with BigBrotr. NULL values do not occupy storage, providing approximately 60% disk savings.

!!! note
    BigBrotr and LilBrotr intentionally share the same analytics schema and refresh logic wherever a metric can be reconstructed from `id`, `pubkey`, `created_at`, `kind`, `event_relay.seen_at`, and `tagvalues`. When a metric depends on tag fields that are not stored in LilBrotr (for example reply markers or multi-character tags such as `amount` and `bolt11`), LilBrotr uses a best-effort fallback instead of adding new persisted columns.

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
| `state_type` | TEXT | PK (partial) | State category: `checkpoint`, `cursor` |
| `state_key` | TEXT | PK (partial) | Unique key within service+type |
| `state_value` | JSONB | NOT NULL, DEFAULT `{}` | Service-specific JSONB state value |

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

Extracts key-prefixed values from single-character tag keys in a Nostr event tags array. Each value is prefixed with its tag key and a colon separator, enabling GIN queries that discriminate between tag types.

```sql
LANGUAGE SQL IMMUTABLE RETURNS NULL ON NULL INPUT SECURITY INVOKER
```

**Example**: `[["e", "abc"], ["p", "def"], ["relay", "wss://..."]]` -> `ARRAY['e:abc', 'p:def']`

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
    p_state_values JSONB[]
) -> INTEGER
```

Bulk upsert service state records. Uses `DISTINCT ON` within the batch to deduplicate, then `ON CONFLICT DO UPDATE SET` for full replacement semantics. Returns the number of rows affected.

### service_state_get

```sql
service_state_get(
    p_service_name TEXT, p_state_type TEXT, p_state_key TEXT DEFAULT NULL
) -> TABLE(state_key TEXT, state_value JSONB)
```

Retrieves service state records. If `p_state_key` is NULL, returns all records for the service+type ordered by `state_key ASC`.

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

## Core Analytics Summary Tables

All deployments (BigBrotr, LilBrotr) share these core analytics tables. They are regular tables refreshed incrementally via range-based refresh functions that receive `(after, until)` parameters and return the number of rows affected.

### pubkey_kind_stats

Per-author, per-kind event statistics.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `pubkey` | TEXT | PRIMARY KEY (partial) | Author public key as hex |
| `kind` | INTEGER | PRIMARY KEY (partial) | Event kind |
| `event_count` | BIGINT | NOT NULL DEFAULT 0 | Total events by this author of this kind |
| `first_event_at` | BIGINT | Nullable | Earliest event timestamp |
| `last_event_at` | BIGINT | Nullable | Latest event timestamp |

Primary key: `(pubkey, kind)`.

### pubkey_relay_stats

Per-author, per-relay activity metrics.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `pubkey` | TEXT | PRIMARY KEY (partial) | Author public key as hex |
| `relay_url` | TEXT | PRIMARY KEY (partial) | Relay WebSocket URL |
| `event_count` | BIGINT | NOT NULL DEFAULT 0 | Events by this author on this relay |
| `first_event_at` | BIGINT | Nullable | Earliest event timestamp |
| `last_event_at` | BIGINT | Nullable | Latest event timestamp |

Primary key: `(pubkey, relay_url)`.

### relay_kind_stats

Per-relay, per-kind event distribution.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `relay_url` | TEXT | PRIMARY KEY (partial) | Relay WebSocket URL |
| `kind` | INTEGER | PRIMARY KEY (partial) | Event kind |
| `event_count` | BIGINT | NOT NULL DEFAULT 0 | Events of this kind on this relay |
| `first_event_at` | BIGINT | Nullable | Earliest event timestamp |
| `last_event_at` | BIGINT | Nullable | Latest event timestamp |

Primary key: `(relay_url, kind)`.

### pubkey_stats

Global author activity metrics.

| Column | Type | Description |
|--------|------|-------------|
| `pubkey` | TEXT PRIMARY KEY | Author public key as hex |
| `event_count` | BIGINT | Total events by this author |
| `unique_kinds` | INTEGER | Event kinds authored |
| `unique_relays` | INTEGER | Relays where this author was observed |
| `first_event_at` | BIGINT | Earliest event timestamp |
| `last_event_at` | BIGINT | Latest event timestamp |
| `events_last_24h`, `events_last_7d`, `events_last_30d` | BIGINT | Rolling activity windows |
| `regular_count`, `replaceable_count`, `ephemeral_count`, `addressable_count` | BIGINT | Event counts by NIP-01 category |

### kind_stats

Global event count distribution by NIP-01 kind with category labels.

| Column | Type | Description |
|--------|------|-------------|
| `kind` | INTEGER PRIMARY KEY | Event kind |
| `event_count` | BIGINT | Total events of this kind |
| `unique_pubkeys` | INTEGER | Authors publishing this kind |
| `unique_relays` | INTEGER | Relays that carried this kind |
| `category` | TEXT | NIP-01 category: regular, replaceable, ephemeral, addressable, other |
| `first_event_at`, `last_event_at` | BIGINT | Earliest and latest event timestamps |
| `events_last_24h`, `events_last_7d`, `events_last_30d` | BIGINT | Rolling activity windows |

### relay_stats

Per-relay event counts, averaged round-trip times, and NIP-11 info.

| Column | Type | Description |
|--------|------|-------------|
| `relay_url` | TEXT PRIMARY KEY | Relay WebSocket URL |
| `network` | TEXT | Network type |
| `discovered_at` | BIGINT | Unix discovery timestamp |
| `event_count` | BIGINT | Total events on relay |
| `unique_pubkeys` | INTEGER | Unique authors on relay |
| `unique_kinds` | INTEGER | Unique event kinds on relay |
| `first_event_at`, `last_event_at` | BIGINT | Earliest and latest event timestamps |
| `events_last_24h`, `events_last_7d`, `events_last_30d` | BIGINT | Rolling activity windows |
| `regular_count`, `replaceable_count`, `ephemeral_count`, `addressable_count` | BIGINT | Event counts by NIP-01 category |
| `avg_rtt_open`, `avg_rtt_read`, `avg_rtt_write` | NUMERIC(10,2) | NIP-66 RTT averages |
| `nip11_name`, `nip11_software`, `nip11_version` | TEXT | Current NIP-11 metadata fields |

---

## Derived Current-State Tables

All deployments (BigBrotr, LilBrotr) share the same current-state tables. The Refresher maintains them incrementally through checkpointed refresh functions rather than `REFRESH MATERIALIZED VIEW CONCURRENTLY`.

### relay_metadata_current

Latest metadata snapshot per relay and check type.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `relay_url` | TEXT | PRIMARY KEY (partial) | Relay WebSocket URL |
| `metadata_type` | TEXT | PRIMARY KEY (partial) | Check type |
| `generated_at` | BIGINT | NOT NULL | Timestamp of latest snapshot |
| `metadata_id` | BYTEA | NOT NULL | Content-addressed hash |
| `data` | JSONB | NOT NULL | Complete JSON document |

Primary key: `(relay_url, metadata_type)`.

### events_replaceable_current

Latest replaceable event per author and kind.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `pubkey` | BYTEA | PRIMARY KEY (partial) | Author public key |
| `kind` | INTEGER | PRIMARY KEY (partial) | Event kind (replaceable range) |
| `id` | BYTEA | NOT NULL | Current winning event hash |
| `created_at` | BIGINT | NOT NULL | Event timestamp |
| `first_seen_at` | BIGINT | NOT NULL | First observation timestamp for the winning event |
| `tags`, `content`, `sig` | JSONB/TEXT/BYTEA | Nullable | Event payload fields, nullable for LilBrotr compatibility |
| `tagvalues` | TEXT[] | NOT NULL | Computed single-char tag values |

Primary key: `(pubkey, kind)`.

### events_addressable_current

Latest addressable event per author, kind, and d-tag identifier.

BigBrotr extracts `d_tag` from the first `d` tag in the stored JSON tags. LilBrotr uses the same table definition but falls back to the ordered `tagvalues` entry `d:*` when full tags are not persisted.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `pubkey` | BYTEA | PRIMARY KEY (partial) | Author public key |
| `kind` | INTEGER | PRIMARY KEY (partial) | Event kind (addressable range) |
| `d_tag` | TEXT | PRIMARY KEY (partial) | Addressable identifier |
| `id` | BYTEA | NOT NULL | Current winning event hash |
| `created_at` | BIGINT | NOT NULL | Event timestamp |
| `first_seen_at` | BIGINT | NOT NULL | First observation timestamp for the winning event |
| `tags`, `content`, `sig` | JSONB/TEXT/BYTEA | Nullable | Event payload fields, nullable for LilBrotr compatibility |
| `tagvalues` | TEXT[] | NOT NULL | Computed single-char tag values |

Primary key: `(pubkey, kind, d_tag)`.

### contact_lists_current

Current latest kind=3 contact list per author.

| Column | Type | Description |
|--------|------|-------------|
| `follower_pubkey` | TEXT PRIMARY KEY | Pubkey that published the current contact list |
| `source_event_id` | TEXT | Current kind=3 event id |
| `source_created_at` | BIGINT | Event creation timestamp |
| `source_seen_at` | BIGINT | First observation timestamp for the source event |
| `follow_count` | BIGINT | Deduplicated number of followed pubkeys |

### contact_list_edges_current

Current deduplicated follow graph edges.

| Column | Type | Description |
|--------|------|-------------|
| `follower_pubkey` | TEXT PRIMARY KEY (partial) | Following pubkey |
| `followed_pubkey` | TEXT PRIMARY KEY (partial) | Followed pubkey |
| `source_event_id` | TEXT | Current kind=3 event id that produced the edge |
| `source_created_at` | BIGINT | Event creation timestamp |
| `source_seen_at` | BIGINT | First observation timestamp for the source event |

Primary key: `(follower_pubkey, followed_pubkey)`.

---

## Metadata And Time-Series Analytics Tables

### relay_software_counts

NIP-11 software distribution across relays. Depends on `relay_metadata_current`.

| Column | Type | Description |
|--------|------|-------------|
| `software` | TEXT PRIMARY KEY (partial) | Software name from NIP-11 |
| `version` | TEXT PRIMARY KEY (partial) | Software version |
| `relay_count` | BIGINT | Relays running this software/version pair |

Primary key: `(software, version)`.

### supported_nip_counts

NIP support distribution from NIP-11 info. Depends on `relay_metadata_current`.

| Column | Type | Description |
|--------|------|-------------|
| `nip` | INTEGER PRIMARY KEY | NIP number |
| `relay_count` | BIGINT | Relays supporting this NIP |

### daily_counts

Daily event aggregation for time-series analysis (UTC).

| Column | Type | Description |
|--------|------|-------------|
| `day` | DATE PRIMARY KEY | UTC date |
| `event_count` | BIGINT | Events on this day |
| `unique_pubkeys` | BIGINT | Unique authors on this day |
| `unique_kinds` | BIGINT | Unique event kinds on this day |

---

## NIP-85 Stats And Rank Tables

NIP-85 stats tables store facts used to publish trusted assertions. Rank tables store score snapshots exported by the ranker. These tables are not foreign-key constrained to the core archive; they use text identifiers for API/publication compatibility.

### nip85_pubkey_stats

Per-pubkey social metrics for NIP-85 kind 30382.

| Column | Type | Description |
|--------|------|-------------|
| `pubkey` | TEXT PRIMARY KEY | Asserted pubkey |
| `post_count`, `reply_count` | BIGINT | Authored post and reply counts |
| `reaction_count_sent`, `reaction_count_recd` | BIGINT | Reactions sent and received |
| `repost_count_sent`, `repost_count_recd` | BIGINT | Reposts sent and received |
| `report_count_sent`, `report_count_recd` | BIGINT | Reports sent and received |
| `zap_count_sent`, `zap_count_recd` | BIGINT | Zaps sent and received |
| `zap_amount_sent`, `zap_amount_recd` | BIGINT | Bolt11-verified zap amounts |
| `first_created_at` | BIGINT | First known authored event timestamp |
| `activity_hours` | INTEGER[24] | UTC hour activity heatmap |
| `topic_counts` | JSONB | Topic counters by tag/topic |
| `follower_count`, `following_count` | BIGINT | Counts reconciled from current contact-list facts |

### nip85_event_stats

Per-event engagement metrics for NIP-85 kind 30383.

| Column | Type | Description |
|--------|------|-------------|
| `event_id` | TEXT PRIMARY KEY | Asserted event id |
| `author_pubkey` | TEXT | Event author pubkey |
| `comment_count`, `quote_count`, `repost_count`, `reaction_count` | BIGINT | Engagement counters |
| `zap_count`, `zap_amount` | BIGINT | Bolt11-verified zap counters |

### nip85_addressable_stats

Per-addressable-event engagement metrics for NIP-85 kind 30384.

| Column | Type | Description |
|--------|------|-------------|
| `event_address` | TEXT PRIMARY KEY | Canonical `kind:pubkey:d_tag` coordinate |
| `author_pubkey` | TEXT | Addressable event author pubkey |
| `comment_count`, `quote_count`, `repost_count`, `reaction_count` | BIGINT | Engagement counters |
| `zap_count`, `zap_amount` | BIGINT | Bolt11-verified zap counters |

### nip85_identifier_stats

Per-identifier engagement metrics for NIP-85 kind 30385.

| Column | Type | Description |
|--------|------|-------------|
| `identifier` | TEXT PRIMARY KEY | NIP-73 identifier string |
| `comment_count`, `reaction_count` | BIGINT | Engagement counters |
| `k_tags` | TEXT[] | Deduplicated sorted NIP-73 `k` tags observed with the identifier |

### Rank tables

The rank tables share the same shape:

| Table | Subject |
|-------|---------|
| `nip85_pubkey_ranks` | Pubkey, for kind 30382 |
| `nip85_event_ranks` | Event id, for kind 30383 |
| `nip85_addressable_ranks` | Addressable coordinate, for kind 30384 |
| `nip85_identifier_ranks` | NIP-73 identifier, for kind 30385 |

| Column | Type | Description |
|--------|------|-------------|
| `algorithm_id` | TEXT PRIMARY KEY (partial) | Ranking algorithm identifier |
| `subject_id` | TEXT PRIMARY KEY (partial) | Pubkey/event/address/identifier being scored |
| `raw_score` | DOUBLE PRECISION | Raw ranker score |
| `rank` | INTEGER | Final 0-100 publication score |
| `computed_at` | BIGINT | Rank snapshot timestamp |

Primary key: `(algorithm_id, subject_id)`.

---

## Refresh Functions

The **Refresher** service (`python -m bigbrotr refresher`) orchestrates all refresh functions automatically, executing each configured target in dependency order with per-target logging, checkpoints, metrics, and error isolation.

### Current-State Refresh Functions

Current-state refresh functions accept `(p_after BIGINT, p_until BIGINT)` range parameters and return `INTEGER` (rows affected). The Refresher computes the range from each target checkpoint to the next source watermark.

| Function | Target Table | Recommended Schedule |
|----------|-------------|---------------------|
| `relay_metadata_current_refresh(after, until)` | relay_metadata_current | Daily |
| `events_replaceable_current_refresh(after, until)` | events_replaceable_current | Hourly |
| `events_addressable_current_refresh(after, until)` | events_addressable_current | Hourly |
| `contact_lists_current_refresh(after, until)` | contact_lists_current | Hourly |
| `contact_list_edges_current_refresh(after, until)` | contact_list_edges_current | Hourly |

### Analytics Refresh Functions

Analytics refresh functions also accept `(p_after BIGINT, p_until BIGINT)` range parameters and return `INTEGER` (rows affected).

| Function | Target Table | Recommended Schedule |
|----------|-------------|---------------------|
| `daily_counts_refresh(after, until)` | daily_counts | Daily |
| `relay_software_counts_refresh(after, until)` | relay_software_counts | Daily |
| `supported_nip_counts_refresh(after, until)` | supported_nip_counts | Daily |
| `pubkey_kind_stats_refresh(after, until)` | pubkey_kind_stats | Hourly |
| `pubkey_relay_stats_refresh(after, until)` | pubkey_relay_stats | Hourly |
| `relay_kind_stats_refresh(after, until)` | relay_kind_stats | Hourly |
| `pubkey_stats_refresh(after, until)` | pubkey_stats | Hourly |
| `kind_stats_refresh(after, until)` | kind_stats | Hourly |
| `relay_stats_refresh(after, until)` | relay_stats | Hourly |
| `nip85_pubkey_stats_refresh(after, until)` | nip85_pubkey_stats | Hourly |
| `nip85_event_stats_refresh(after, until)` | nip85_event_stats | Hourly |
| `nip85_addressable_stats_refresh(after, until)` | nip85_addressable_stats | Hourly |
| `nip85_identifier_stats_refresh(after, until)` | nip85_identifier_stats | Hourly |

### Periodic Functions

| Function | Purpose | Recommended Schedule |
|----------|---------|---------------------|
| `rolling_windows_refresh()` | Refresh rolling time-window columns in summary tables | Hourly |
| `relay_stats_metadata_refresh()` | Refresh metadata-derived columns in relay_stats (RTT, NIP-11) | Daily |
| `nip85_follower_count_refresh()` | Recompute NIP-85 follower/following counts | Hourly |

!!! note
    `relay_software_counts` and `supported_nip_counts` depend on `relay_metadata_current`; the Refresher config validates that `relay_metadata_current` is included when those analytics targets are enabled.

---

## Indexes

### BigBrotr Table Indexes

#### event

| Index | Columns | Type | Purpose |
|-------|---------|------|---------|
| PK | `id` | BTREE | Primary key |
| `idx_event_created_at_id` | `created_at DESC, id DESC` | BTREE | Global timeline with cursor pagination (covers created_at-only via prefix) |
| `idx_event_kind_created_at` | `kind, created_at DESC` | BTREE | Kind + timeline (covers kind-only via leftmost prefix) |
| `idx_event_pubkey_created_at` | `pubkey, created_at DESC` | BTREE | Author timeline |
| `idx_event_pubkey_kind_created_at` | `pubkey, kind, created_at DESC` | BTREE | Author + kind + timeline |
| `idx_event_tagvalues` | `tagvalues` | GIN | Tag containment (`@>`) |

#### event_relay Indexes

| Index | Columns | Type | Purpose |
|-------|---------|------|---------|
| PK | `event_id, relay_url` | BTREE | Composite primary key |
| `idx_event_relay_seen_at` | `seen_at DESC` | BTREE | Global seen_at ordering for API |
| `idx_event_relay_relay_url_seen_at_event_id` | `relay_url, seen_at ASC, event_id ASC` | BTREE | Finder cursor pagination (covers relay_url-only via prefix) |

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
    The partial index on `service_state` has a WHERE clause: `WHERE service_name = 'validator' AND state_type = 'checkpoint'`. Only validator checkpoint rows contain the `network` key in their `state_value` JSONB.

### Summary Table Indexes

Summary tables use their primary keys for uniqueness. Additional secondary indexes support common query patterns.

| Index | Table | Columns | Type |
|-------|-------|---------|------|
| PK | relay_stats | `relay_url` | Primary key |
| Secondary | relay_stats | `network` | BTREE |
| PK | kind_stats | `kind` | Primary key |
| PK | pubkey_stats | `pubkey` | Primary key |
| PK | relay_kind_stats | `relay_url, kind` | Composite primary key |
| Secondary | relay_kind_stats | `relay_url` | BTREE |
| PK | pubkey_kind_stats | `pubkey, kind` | Composite primary key |
| PK | pubkey_relay_stats | `pubkey, relay_url` | Composite primary key |
| Secondary | pubkey_relay_stats | `relay_url` | BTREE |

### Current And Analytics Indexes

Current-state and analytics tables use primary keys for deterministic upserts. Additional secondary indexes support common access paths.

| Index | Table | Columns | Unique |
|-------|-------|---------|--------|
| `idx_relay_metadata_current_type_generated_at` | relay_metadata_current | `metadata_type, generated_at DESC` | No |
| `idx_events_replaceable_current_id` | events_replaceable_current | `id` | Yes |
| `idx_events_addressable_current_id` | events_addressable_current | `id` | Yes |
| `idx_contact_lists_current_source_seen_at_follower` | contact_lists_current | `source_seen_at DESC, follower_pubkey` | No |
| `idx_contact_list_edges_current_followed` | contact_list_edges_current | `followed_pubkey` | No |
| `idx_nip85_event_stats_author` | nip85_event_stats | `author_pubkey` | No |
| `idx_nip85_addressable_stats_author` | nip85_addressable_stats | `author_pubkey` | No |

### LilBrotr Table Indexes

LilBrotr uses the same table, current-state, analytics, and rank indexes as BigBrotr (see above). The only schema difference is the event table column nullability.

---

## Schema Initialization

SQL files execute in alphabetical order via Docker's `/docker-entrypoint-initdb.d/`:

### BigBrotr

| File | Content |
|------|---------|
| `00_extensions.sql` | `btree_gin`, `pg_stat_statements` |
| `01_functions_utility.sql` | Tag and event-address utility functions |
| `02_tables_core.sql` | Core relay, event, metadata, junction, and service-state tables |
| `03_tables_current.sql` | Current-state tables |
| `04_tables_analytics.sql` | Analytics and NIP-85 rank tables |
| `05_functions_crud.sql` | CRUD, cascade, and service-state functions |
| `06_functions_cleanup.sql` | 2 cleanup functions |
| `07_views_reporting.sql` | Reporting views |
| `08_functions_refresh_current.sql` | Current-state refresh functions |
| `09_functions_refresh_analytics.sql` | Analytics, contact-graph, and periodic refresh functions |
| `10_indexes_core.sql` | Core table indexes |
| `11_indexes_current.sql` | Current-state indexes |
| `12_indexes_analytics.sql` | Analytics and rank indexes |
| `98_grants.sh` | Role grants |
| `99_verify.sql` | Verification queries |

### LilBrotr

| File | Content |
|------|---------|
| `00_extensions.sql` | `btree_gin`, `pg_stat_statements` |
| `01_functions_utility.sql` | Tag and event-address utility functions |
| `02_tables_core.sql` | Core relay, event, metadata, junction, and service-state tables |
| `03_tables_current.sql` | Current-state tables |
| `04_tables_analytics.sql` | Analytics and NIP-85 rank tables |
| `05_functions_crud.sql` | CRUD, cascade, and service-state functions |
| `06_functions_cleanup.sql` | 2 cleanup functions |
| `07_views_reporting.sql` | Reporting views |
| `08_functions_refresh_current.sql` | Current-state refresh functions |
| `09_functions_refresh_analytics.sql` | Analytics, contact-graph, and periodic refresh functions |
| `10_indexes_core.sql` | Core table indexes |
| `11_indexes_current.sql` | Current-state indexes |
| `12_indexes_analytics.sql` | Analytics and rank indexes |
| `98_grants.sh` | Role grants |
| `99_verify.sql` | Verification queries |

---

## Deployment-Specific Schemas

**BigBrotr** (full archive): stores all 8 columns. Tagvalues computed at insert time by `event_insert()`.

```sql
CREATE TABLE event (
    id BYTEA PRIMARY KEY,
    pubkey BYTEA NOT NULL,
    created_at BIGINT NOT NULL,
    kind INTEGER NOT NULL,
    tags JSONB NOT NULL,
    tagvalues TEXT[] NOT NULL,
    content TEXT NOT NULL,
    sig BYTEA NOT NULL
);
```

**LilBrotr** (lightweight): all 8 columns present but tags, content, sig are nullable and always NULL for ~60% disk savings. `tagvalues` is still computed at insert time by `event_insert()` and remains the compatibility layer that keeps most analytics behavior aligned with BigBrotr.

```sql
CREATE TABLE event (
    id BYTEA PRIMARY KEY,
    pubkey BYTEA NOT NULL,
    created_at BIGINT NOT NULL,
    kind INTEGER NOT NULL,
    tags JSONB,
    tagvalues TEXT[] NOT NULL,
    content TEXT,
    sig BYTEA
);
```

---

## Function Summary

| Category | Count | Functions |
|----------|-------|-----------|
| Utility | 5 | `tags_to_tagvalues`, event address helpers, and `bolt11_amount_msats` |
| CRUD (Level 1) | 8 | `relay_insert`, `event_insert`, `metadata_insert`, `event_relay_insert`, `relay_metadata_insert`, `service_state_upsert`, `service_state_get`, `service_state_delete` |
| CRUD (Level 2) | 2 | `event_relay_insert_cascade`, `relay_metadata_insert_cascade` |
| Cleanup | 2 | `orphan_metadata_delete`, `orphan_event_delete` |
| Current refresh | 5 | `relay_metadata_current_refresh`, `events_replaceable_current_refresh`, `events_addressable_current_refresh`, `contact_lists_current_refresh`, `contact_list_edges_current_refresh` |
| Analytics refresh | 13 | `daily_counts_refresh`, metadata analytics, entity stats, and NIP-85 stats refresh functions |
| Periodic refresh | 3 | `rolling_windows_refresh`, `relay_stats_metadata_refresh`, `nip85_follower_count_refresh` |
| **Total** | **38** | |

---

## Maintenance Schedule

| Task | Frequency | Command |
|------|-----------|---------|
| Refresh current-state and analytics tables | Hourly/Daily | Run via Refresher service (orchestrates configured targets individually) |
| Refresh periodic reconciliation targets | Hourly/Daily | Run via Refresher service (orchestrates configured targets individually) |
| Delete orphan events | Daily | `SELECT orphan_event_delete()` |
| Delete orphan metadata | Daily | `SELECT orphan_metadata_delete()` |
| VACUUM ANALYZE | Weekly | `VACUUM ANALYZE event; VACUUM ANALYZE event_relay;` |

---

## Related Documentation

- [Architecture](architecture.md) -- System architecture and module reference
- [Services](services.md) -- Deep dive into the ten independent services
- [Configuration](configuration.md) -- YAML configuration reference
- [Monitoring](monitoring.md) -- Prometheus metrics, alerting, and Grafana dashboards
