# Database Schema

This document provides comprehensive documentation for BigBrotr's PostgreSQL database schema.

## Table of Contents

- [Overview](#overview)
- [Extensions](#extensions)
- [Tables](#tables)
- [Indexes](#indexes)
- [Stored Procedures](#stored-procedures)
- [Views](#views)
- [Utility Functions](#utility-functions)
- [Data Types](#data-types)
- [Schema Initialization](#schema-initialization)
- [Maintenance](#maintenance)

---

## Overview

BigBrotr uses PostgreSQL 16+ as its primary data store with the following design principles:

- **Space Efficiency**: BYTEA types for binary data (50% savings vs hex strings)
- **Data Integrity**: Foreign keys and constraints for referential integrity
- **Deduplication**: Content-addressed storage for NIP-11/NIP-66 documents
- **Performance**: Strategic indexes for common query patterns
- **Idempotency**: All insert operations use ON CONFLICT DO NOTHING

### Schema Files

SQL files are located in `implementations/bigbrotr/postgres/init/` and applied in numerical order:

| File | Purpose |
|------|---------|
| `00_extensions.sql` | PostgreSQL extensions |
| `01_utility_functions.sql` | Hash functions and utilities |
| `02_tables.sql` | Table definitions |
| `03_indexes.sql` | Performance indexes |
| `04_integrity_functions.sql` | Orphan cleanup functions |
| `05_procedures.sql` | Insert procedures |
| `06_views.sql` | Analytics views |
| `99_verify.sql` | Schema verification |

---

## Extensions

BigBrotr requires two PostgreSQL extensions:

### pgcrypto

Used for cryptographic hash functions:

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

**Usage**: Computing content hashes for NIP-11/NIP-66 deduplication via `digest()` function.

### btree_gin

Enables GIN indexes on scalar types:

```sql
CREATE EXTENSION IF NOT EXISTS btree_gin;
```

**Usage**: GIN indexes on `tagvalues` arrays for efficient tag filtering.

---

## Tables

### relays

Registry of known Nostr relay URLs.

```sql
CREATE TABLE relays (
    url TEXT PRIMARY KEY,
    network TEXT NOT NULL DEFAULT 'clearnet' CHECK (network IN ('clearnet', 'tor')),
    inserted_at BIGINT NOT NULL
);
```

| Column | Type | Description |
|--------|------|-------------|
| `url` | TEXT (PK) | WebSocket URL (e.g., `wss://relay.example.com`) |
| `network` | TEXT | Network type: `clearnet` or `tor` |
| `inserted_at` | BIGINT | Unix timestamp when relay was discovered |

### events

Nostr events with binary storage for efficiency.

**BigBrotr Schema (Full Storage)**:
```sql
CREATE TABLE events (
    id BYTEA PRIMARY KEY,
    pubkey BYTEA NOT NULL,
    created_at BIGINT NOT NULL,
    kind INTEGER NOT NULL,
    tags JSONB NOT NULL,
    content TEXT NOT NULL,
    sig BYTEA NOT NULL,
    tagvalues TEXT[] GENERATED ALWAYS AS (tags_to_tagvalues(tags)) STORED
);
```

**LilBrotr Schema (Lightweight - No Tags/Content)**:
```sql
CREATE TABLE events (
    id BYTEA PRIMARY KEY,
    pubkey BYTEA NOT NULL,
    created_at BIGINT NOT NULL,
    kind INTEGER NOT NULL,
    -- tags and content NOT stored
    sig BYTEA NOT NULL
);
```

| Column | Type | BigBrotr | LilBrotr | Description |
|--------|------|----------|----------|-------------|
| `id` | BYTEA (PK) | Yes | Yes | Event ID (32 bytes, hex decoded) |
| `pubkey` | BYTEA | Yes | Yes | Author's public key (32 bytes) |
| `created_at` | BIGINT | Yes | Yes | Unix timestamp of event creation |
| `kind` | INTEGER | Yes | Yes | Event kind number per NIP-01 |
| `tags` | JSONB | Yes | **No** | Event tags array |
| `content` | TEXT | Yes | **No** | Event content |
| `sig` | BYTEA | Yes | Yes | Schnorr signature (64 bytes) |
| `tagvalues` | TEXT[] | Yes | **No** | Generated: extracted tag values for indexing |

**Notes**:
- BYTEA storage saves 50% compared to hex strings
- `tagvalues` is auto-generated from `tags` for efficient querying (BigBrotr only)
- LilBrotr saves ~60% disk space by not storing tags and content

### events_relays

Junction table tracking which relays have seen each event.

```sql
CREATE TABLE events_relays (
    event_id BYTEA NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    relay_url TEXT NOT NULL REFERENCES relays(url) ON DELETE CASCADE,
    seen_at BIGINT NOT NULL,
    PRIMARY KEY (event_id, relay_url)
);
```

| Column | Type | Description |
|--------|------|-------------|
| `event_id` | BYTEA (FK) | Reference to events table |
| `relay_url` | TEXT (FK) | Reference to relays table |
| `seen_at` | BIGINT | Unix timestamp when event was seen on this relay |

### nip11

Deduplicated NIP-11 relay information documents.

```sql
CREATE TABLE nip11 (
    id BYTEA PRIMARY KEY,
    name TEXT,
    description TEXT,
    banner TEXT,
    icon TEXT,
    pubkey TEXT,
    contact TEXT,
    supported_nips JSONB,
    software TEXT,
    version TEXT,
    privacy_policy TEXT,
    terms_of_service TEXT,
    limitation JSONB,
    extra_fields JSONB
);
```

| Column | Type | Description |
|--------|------|-------------|
| `id` | BYTEA (PK) | Content hash (SHA-256 of all fields) |
| `name` | TEXT | Human-readable relay name |
| `description` | TEXT | Relay description |
| `banner` | TEXT | URL to banner image |
| `icon` | TEXT | URL to icon |
| `pubkey` | TEXT | Operator's public key (hex) |
| `contact` | TEXT | Operator contact info |
| `supported_nips` | JSONB | Array of supported NIP numbers |
| `software` | TEXT | Software name/URL |
| `version` | TEXT | Software version |
| `privacy_policy` | TEXT | Privacy policy URL |
| `terms_of_service` | TEXT | ToS URL |
| `limitation` | JSONB | Relay limitations object |
| `extra_fields` | JSONB | Non-standard fields |

**Deduplication**: Multiple relays with identical NIP-11 data share the same record.

### nip66

Deduplicated NIP-66 relay test results.

```sql
CREATE TABLE nip66 (
    id BYTEA PRIMARY KEY,
    openable BOOLEAN NOT NULL DEFAULT FALSE,
    readable BOOLEAN NOT NULL DEFAULT FALSE,
    writable BOOLEAN NOT NULL DEFAULT FALSE,
    rtt_open INTEGER,
    rtt_read INTEGER,
    rtt_write INTEGER
);
```

| Column | Type | Description |
|--------|------|-------------|
| `id` | BYTEA (PK) | Content hash of test results |
| `openable` | BOOLEAN | Can establish WebSocket connection |
| `readable` | BOOLEAN | Responds to REQ messages |
| `writable` | BOOLEAN | Accepts EVENT messages |
| `rtt_open` | INTEGER | Round-trip time for connection (ms) |
| `rtt_read` | INTEGER | Round-trip time for read (ms) |
| `rtt_write` | INTEGER | Round-trip time for write (ms) |

### relay_metadata

Time-series metadata snapshots linking relays to NIP-11/NIP-66 data.

```sql
CREATE TABLE relay_metadata (
    relay_url TEXT NOT NULL REFERENCES relays(url) ON DELETE CASCADE,
    generated_at BIGINT NOT NULL,
    nip11_id BYTEA REFERENCES nip11(id) ON DELETE SET NULL,
    nip66_id BYTEA REFERENCES nip66(id) ON DELETE SET NULL,
    PRIMARY KEY (relay_url, generated_at)
);
```

| Column | Type | Description |
|--------|------|-------------|
| `relay_url` | TEXT (FK, PK) | Reference to relays table |
| `generated_at` | BIGINT (PK) | Unix timestamp of this snapshot |
| `nip11_id` | BYTEA (FK) | Reference to nip11 table (nullable) |
| `nip66_id` | BYTEA (FK) | Reference to nip66 table (nullable) |

### service_state

Service state persistence for incremental processing.

```sql
CREATE TABLE service_state (
    service_name TEXT PRIMARY KEY,
    state JSONB NOT NULL DEFAULT '{}',
    updated_at BIGINT NOT NULL
);
```

| Column | Type | Description |
|--------|------|-------------|
| `service_name` | TEXT (PK) | Service identifier |
| `state` | JSONB | Arbitrary state data |
| `updated_at` | BIGINT | Last update timestamp |

---

## Indexes

### Primary Indexes (from table definitions)

```sql
-- Automatically created
PRIMARY KEY (id) ON events
PRIMARY KEY (url) ON relays
PRIMARY KEY (event_id, relay_url) ON events_relays
PRIMARY KEY (id) ON nip11
PRIMARY KEY (id) ON nip66
PRIMARY KEY (relay_url, generated_at) ON relay_metadata
PRIMARY KEY (service_name) ON service_state
```

### Performance Indexes

```sql
-- Event queries by time range
CREATE INDEX idx_events_created_at ON events (created_at DESC);

-- Event queries by author
CREATE INDEX idx_events_pubkey ON events (pubkey);

-- Event queries by kind
CREATE INDEX idx_events_kind ON events (kind);

-- Combined author + time queries
CREATE INDEX idx_events_pubkey_created_at ON events (pubkey, created_at DESC);

-- Junction table lookups
CREATE INDEX idx_events_relays_relay_url ON events_relays (relay_url);
CREATE INDEX idx_events_relays_seen_at ON events_relays (seen_at DESC);

-- Metadata lookups by time
CREATE INDEX idx_relay_metadata_generated_at ON relay_metadata (generated_at DESC);

-- Tag value searches (GIN for array containment)
CREATE INDEX idx_events_tagvalues ON events USING GIN (tagvalues);
```

### Index Usage Notes

- **Time-based queries**: Most queries filter by `created_at`, so DESC ordering is used
- **Tag queries**: Use `@>` operator with GIN index: `WHERE tagvalues @> ARRAY['e:abc123']`
- **Author queries**: Combined index with time for efficient "recent events by author"

---

## Stored Procedures

### insert_event

Atomically inserts an event with its relay association.

```sql
CREATE OR REPLACE FUNCTION insert_event(
    p_event_id              BYTEA,
    p_pubkey                BYTEA,
    p_created_at            BIGINT,
    p_kind                  INTEGER,
    p_tags                  JSONB,
    p_content               TEXT,
    p_sig                   BYTEA,
    p_relay_url             TEXT,
    p_relay_network         TEXT,
    p_relay_inserted_at     BIGINT,
    p_seen_at               BIGINT
) RETURNS VOID;
```

**Behavior**:
1. Inserts event (ON CONFLICT DO NOTHING)
2. Inserts relay (ON CONFLICT DO NOTHING)
3. Inserts event-relay association (ON CONFLICT DO NOTHING)

**Idempotency**: Safe to call multiple times with same data.

### insert_relay

Inserts a relay record.

```sql
CREATE OR REPLACE FUNCTION insert_relay(
    p_url           TEXT,
    p_network       TEXT,
    p_inserted_at   BIGINT
) RETURNS VOID;
```

**Idempotency**: Duplicate URLs are silently ignored.

### insert_relay_metadata

Inserts relay metadata with automatic NIP-11/NIP-66 deduplication.

```sql
CREATE OR REPLACE FUNCTION insert_relay_metadata(
    -- Relay identification
    p_relay_url                 TEXT,
    p_relay_network             TEXT,
    p_relay_inserted_at         BIGINT,
    p_generated_at              BIGINT,

    -- NIP-66 presence flag and data
    p_nip66_present             BOOLEAN,
    p_nip66_openable            BOOLEAN,
    p_nip66_readable            BOOLEAN,
    p_nip66_writable            BOOLEAN,
    p_nip66_rtt_open            INTEGER,
    p_nip66_rtt_read            INTEGER,
    p_nip66_rtt_write           INTEGER,

    -- NIP-11 presence flag and data
    p_nip11_present             BOOLEAN,
    p_nip11_name                TEXT,
    p_nip11_description         TEXT,
    -- ... (all NIP-11 fields)
) RETURNS VOID;
```

**Deduplication Process**:
1. Compute hash of NIP-11 data -> check/insert into `nip11`
2. Compute hash of NIP-66 data -> check/insert into `nip66`
3. Insert metadata snapshot linking to existing or new records

---

## Views

### relay_metadata_latest

Latest metadata for each relay with NIP-11/NIP-66 data.

```sql
CREATE OR REPLACE VIEW relay_metadata_latest AS
WITH latest_metadata AS (
    SELECT DISTINCT ON (relay_url)
        relay_url, generated_at, nip11_id, nip66_id
    FROM relay_metadata
    ORDER BY relay_url, generated_at DESC
)
SELECT
    r.url AS relay_url,
    r.network,
    r.inserted_at,
    lm.generated_at,
    -- NIP-66 columns
    n66.openable AS nip66_openable,
    n66.readable AS nip66_readable,
    n66.writable AS nip66_writable,
    n66.rtt_open AS nip66_rtt_open,
    n66.rtt_read AS nip66_rtt_read,
    n66.rtt_write AS nip66_rtt_write,
    -- NIP-11 columns
    n11.name AS nip11_name,
    n11.description AS nip11_description,
    -- ... (all fields)
FROM relays r
LEFT JOIN latest_metadata lm ON r.url = lm.relay_url
LEFT JOIN nip66 n66 ON lm.nip66_id = n66.id
LEFT JOIN nip11 n11 ON lm.nip11_id = n11.id;
```

**Usage**:
```sql
-- Get all readable relays
SELECT relay_url, nip11_name
FROM relay_metadata_latest
WHERE nip66_readable = TRUE;
```

### events_statistics

Global event statistics with NIP-01 category breakdown.

```sql
CREATE OR REPLACE VIEW events_statistics AS
SELECT
    COUNT(*) AS total_events,
    COUNT(DISTINCT pubkey) AS unique_pubkeys,
    COUNT(DISTINCT kind) AS unique_kinds,
    MIN(created_at) AS earliest_event_timestamp,
    MAX(created_at) AS latest_event_timestamp,

    -- Event categories per NIP-01
    COUNT(*) FILTER (WHERE kind >= 1000 AND kind < 10000 OR ...) AS regular_events,
    COUNT(*) FILTER (WHERE kind >= 10000 AND kind < 20000 OR ...) AS replaceable_events,
    COUNT(*) FILTER (WHERE kind >= 20000 AND kind < 30000) AS ephemeral_events,
    COUNT(*) FILTER (WHERE kind >= 30000 AND kind < 40000) AS addressable_events,

    -- Time-based metrics
    COUNT(*) FILTER (WHERE created_at >= EXTRACT(EPOCH FROM NOW() - INTERVAL '1 hour')) AS events_last_hour,
    COUNT(*) FILTER (WHERE created_at >= EXTRACT(EPOCH FROM NOW() - INTERVAL '24 hours')) AS events_last_24h,
    COUNT(*) FILTER (WHERE created_at >= EXTRACT(EPOCH FROM NOW() - INTERVAL '7 days')) AS events_last_7d,
    COUNT(*) FILTER (WHERE created_at >= EXTRACT(EPOCH FROM NOW() - INTERVAL '30 days')) AS events_last_30d
FROM events;
```

### relays_statistics

Per-relay statistics including event counts and RTT metrics.

```sql
CREATE OR REPLACE VIEW relays_statistics AS
WITH relay_event_stats AS (
    SELECT
        er.relay_url,
        COUNT(DISTINCT er.event_id) AS event_count,
        COUNT(DISTINCT e.pubkey) AS unique_pubkeys,
        MIN(e.created_at) AS first_event_timestamp,
        MAX(e.created_at) AS last_event_timestamp
    FROM events_relays er
    LEFT JOIN events e ON er.event_id = e.id
    GROUP BY er.relay_url
),
relay_performance AS (
    -- Average RTT from last 10 measurements
    SELECT relay_url, AVG(rtt_open), AVG(rtt_read), AVG(rtt_write)
    FROM (
        SELECT rm.relay_url, n66.rtt_open, n66.rtt_read, n66.rtt_write,
               ROW_NUMBER() OVER (PARTITION BY rm.relay_url ORDER BY rm.generated_at DESC) AS rn
        FROM relay_metadata rm
        LEFT JOIN nip66 n66 ON rm.nip66_id = n66.id
        WHERE n66.id IS NOT NULL
    ) recent
    WHERE rn <= 10
    GROUP BY relay_url
)
SELECT ...
```

### kind_counts_total / kind_counts_by_relay

Event counts aggregated by kind.

```sql
-- Total by kind
SELECT kind, COUNT(*) AS event_count, COUNT(DISTINCT pubkey) AS unique_pubkeys
FROM events GROUP BY kind ORDER BY event_count DESC;

-- By kind per relay
SELECT e.kind, er.relay_url, COUNT(*) AS event_count
FROM events e JOIN events_relays er ON e.id = er.event_id
GROUP BY e.kind, er.relay_url;
```

### pubkey_counts_total / pubkey_counts_by_relay

Event counts aggregated by public key.

```sql
-- Total by pubkey
SELECT encode(pubkey, 'hex') AS pubkey_hex, COUNT(*) AS event_count
FROM events GROUP BY pubkey ORDER BY event_count DESC;
```

---

## Utility Functions

### tags_to_tagvalues

Extracts searchable values from tags array.

```sql
CREATE OR REPLACE FUNCTION tags_to_tagvalues(tags JSONB)
RETURNS TEXT[] AS $$
    SELECT ARRAY(
        SELECT tag->>0 || ':' || tag->>1
        FROM jsonb_array_elements(tags) AS tag
        WHERE jsonb_array_length(tag) >= 2
    );
$$ LANGUAGE SQL IMMUTABLE;
```

**Purpose**: Enables GIN index searches on tag content.

**Example**:
```sql
-- Find events referencing a specific event
SELECT * FROM events
WHERE tagvalues @> ARRAY['e:abc123def456...'];

-- Find events mentioning a pubkey
SELECT * FROM events
WHERE tagvalues @> ARRAY['p:fedcba987654...'];
```

### compute_nip11_hash / compute_nip66_hash

Compute content hashes for deduplication.

```sql
CREATE OR REPLACE FUNCTION compute_nip11_hash(
    p_name TEXT, p_description TEXT, ...
) RETURNS BYTEA AS $$
    SELECT digest(
        COALESCE(p_name, '') || '|' ||
        COALESCE(p_description, '') || '|' ||
        -- ... all fields
        'SHA256'
    );
$$ LANGUAGE SQL IMMUTABLE;
```

### delete_orphan_* Functions

Cleanup functions for orphaned records.

```sql
-- Delete events without relay associations
CREATE OR REPLACE FUNCTION delete_orphan_events() RETURNS INTEGER;

-- Delete unreferenced NIP-11 records
CREATE OR REPLACE FUNCTION delete_orphan_nip11() RETURNS INTEGER;

-- Delete unreferenced NIP-66 records
CREATE OR REPLACE FUNCTION delete_orphan_nip66() RETURNS INTEGER;
```

**Usage**:
```sql
SELECT delete_orphan_events();  -- Returns count of deleted rows
SELECT delete_orphan_nip11();
SELECT delete_orphan_nip66();
```

---

## Data Types

### Binary Fields (BYTEA)

The following fields use BYTEA for 50% space savings:

| Field | Size | Notes |
|-------|------|-------|
| `events.id` | 32 bytes | Event ID (SHA-256) |
| `events.pubkey` | 32 bytes | Public key |
| `events.sig` | 64 bytes | Schnorr signature |
| `nip11.id` | 32 bytes | Content hash |
| `nip66.id` | 32 bytes | Content hash |

**Conversion**:
```sql
-- Hex to BYTEA (in application)
decode('abc123...', 'hex')

-- BYTEA to Hex (in queries)
encode(id, 'hex')
```

### Timestamps

All timestamps are Unix epoch (BIGINT):

```sql
-- Current timestamp
SELECT EXTRACT(EPOCH FROM NOW())::BIGINT;

-- Convert to timestamp
SELECT to_timestamp(created_at);
```

---

## Schema Initialization

### Docker Initialization

SQL files in `postgres/init/` are automatically executed by the PostgreSQL Docker image:

```yaml
# docker-compose.yaml
volumes:
  - ./postgres/init:/docker-entrypoint-initdb.d:ro
```

Files are executed in alphabetical order (00_, 01_, etc.).

### Manual Initialization

```bash
# Connect to database
psql -U admin -d bigbrotr

# Execute files in order
\i postgres/init/00_extensions.sql
\i postgres/init/01_utility_functions.sql
\i postgres/init/02_tables.sql
\i postgres/init/03_indexes.sql
\i postgres/init/04_integrity_functions.sql
\i postgres/init/05_procedures.sql
\i postgres/init/06_views.sql
\i postgres/init/99_verify.sql
```

---

## Maintenance

### Vacuum and Analyze

Regular maintenance improves performance:

```sql
-- Analyze table statistics
ANALYZE events;
ANALYZE events_relays;
ANALYZE relay_metadata;

-- Vacuum to reclaim space
VACUUM events;
VACUUM events_relays;
```

### Index Maintenance

```sql
-- Reindex if needed
REINDEX INDEX idx_events_created_at;

-- Check index usage
SELECT schemaname, relname, indexrelname, idx_scan
FROM pg_stat_user_indexes
ORDER BY idx_scan;
```

### Cleanup Orphans

Run periodically via application:

```python
await brotr.cleanup_orphans()
```

Or manually:

```sql
SELECT delete_orphan_events();
SELECT delete_orphan_nip11();
SELECT delete_orphan_nip66();
```

### Monitoring Queries

```sql
-- Table sizes
SELECT relname, pg_size_pretty(pg_total_relation_size(relid))
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC;

-- Index sizes
SELECT indexrelname, pg_size_pretty(pg_relation_size(indexrelid))
FROM pg_stat_user_indexes
ORDER BY pg_relation_size(indexrelid) DESC;

-- Event counts by day
SELECT DATE(to_timestamp(created_at)), COUNT(*)
FROM events
GROUP BY 1
ORDER BY 1 DESC
LIMIT 30;

-- Relay status summary
SELECT
    COUNT(*) AS total_relays,
    COUNT(*) FILTER (WHERE nip66_openable) AS openable,
    COUNT(*) FILTER (WHERE nip66_readable) AS readable,
    COUNT(*) FILTER (WHERE nip66_writable) AS writable
FROM relay_metadata_latest;
```

---

## Performance Considerations

### Query Optimization

1. **Use indexes**: Always filter on indexed columns
2. **Limit results**: Use `LIMIT` for large result sets
3. **Avoid SELECT ***: Select only needed columns
4. **Use EXPLAIN**: Analyze query plans

```sql
EXPLAIN ANALYZE
SELECT id, created_at FROM events
WHERE created_at > 1700000000
ORDER BY created_at DESC
LIMIT 100;
```

### Scaling Considerations

- **Partitioning**: Consider partitioning `events` by `created_at` for large datasets
- **Read replicas**: Use PostgreSQL streaming replication for read scaling
- **Connection pooling**: PGBouncer is configured for high connection counts
- **Archival**: Consider moving old data to archive tables

---

## Related Documentation

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture overview |
| [CONFIGURATION.md](CONFIGURATION.md) | Complete configuration reference |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Development setup and guidelines |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Deployment instructions |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | Contribution guidelines |
| [CHANGELOG.md](../CHANGELOG.md) | Version history |
