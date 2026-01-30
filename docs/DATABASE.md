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
| `00_extensions.sql` | PostgreSQL extensions (pgcrypto, btree_gin) |
| `01_functions_utility.sql` | Utility functions (tags_to_tagvalues) |
| `02_tables.sql` | Table definitions |
| `03_functions_crud.sql` | CRUD stored procedures |
| `04_functions_cleanup.sql` | Orphan cleanup functions |
| `05_views.sql` | Regular views (placeholder) |
| `06_materialized_views.sql` | Materialized views for analytics |
| `07_functions_refresh.sql` | Materialized view refresh functions |
| `08_indexes.sql` | Performance indexes |
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

Registry of validated Nostr relay URLs.

```sql
CREATE TABLE relays (
    url TEXT PRIMARY KEY,
    network TEXT NOT NULL,
    discovered_at BIGINT NOT NULL
);
```

| Column | Type | Description |
|--------|------|-------------|
| `url` | TEXT (PK) | WebSocket URL (e.g., `wss://relay.example.com`) |
| `network` | TEXT | Network type: `clearnet`, `tor`, `i2p`, or `loki` |
| `discovered_at` | BIGINT | Unix timestamp when relay was first discovered and validated |

**Note**: Only relays that have been validated by the Validator service are stored here. Candidates are stored in `service_data`.

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

**LilBrotr Schema (Essential Metadata - Indexes All Events)**:
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
- LilBrotr indexes all events with essential metadata (id, pubkey, created_at, kind, sig) but omits tags and content, saving ~60% disk space

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

### metadata

Unified storage for NIP-11 and NIP-66 metadata documents with content-addressed deduplication.

```sql
CREATE TABLE metadata (
    id BYTEA PRIMARY KEY,
    metadata JSONB NOT NULL
);
```

| Column | Type | Description |
|--------|------|-------------|
| `id` | BYTEA (PK) | Content hash (SHA-256 computed in Python) |
| `metadata` | JSONB | Complete JSON document (NIP-11 or NIP-66 data) |

**Deduplication**: Multiple relays with identical metadata share the same record. The hash is computed from the JSONB content, ensuring automatic deduplication.

**Content Types**:
- **NIP-11 Fetch**: Relay information documents (name, description, supported NIPs, limitations, etc.)
- **NIP-66 RTT**: Round-trip time measurements (open, read, write) and probe results
- **NIP-66 SSL**: SSL/TLS certificate information
- **NIP-66 Geo**: Geolocation data (country, city, coordinates, ASN)
- **NIP-66 Net**: Network information (IP addresses, protocols)
- **NIP-66 DNS**: DNS resolution data and timing
- **NIP-66 HTTP**: HTTP/WebSocket connection metadata

### relay_metadata

Time-series metadata snapshots linking relays to metadata records by type.

```sql
CREATE TABLE relay_metadata (
    relay_url TEXT NOT NULL REFERENCES relays(url) ON DELETE CASCADE,
    generated_at BIGINT NOT NULL,
    type TEXT NOT NULL,
    metadata_id BYTEA NOT NULL REFERENCES metadata(id) ON DELETE CASCADE,
    PRIMARY KEY (relay_url, generated_at, type),
    CONSTRAINT relay_metadata_type_check CHECK (type IN ('nip11_fetch', 'nip66_rtt', 'nip66_ssl', 'nip66_geo', 'nip66_net', 'nip66_dns', 'nip66_http'))
);
```

| Column | Type | Description |
|--------|------|-------------|
| `relay_url` | TEXT (FK, PK) | Reference to relays table |
| `generated_at` | BIGINT (PK) | Unix timestamp when metadata snapshot was collected |
| `type` | TEXT (PK) | Metadata type: `nip11_fetch`, `nip66_rtt`, `nip66_ssl`, `nip66_geo`, `nip66_net`, `nip66_dns`, or `nip66_http` |
| `metadata_id` | BYTEA (FK) | Reference to metadata table |

**Note**: Each relay can have multiple metadata types per snapshot, allowing separate storage of NIP-11 info, RTT measurements, SSL data, and geolocation data.

### service_data

Per-service operational data storage for candidates, cursors, and checkpoints.

```sql
CREATE TABLE service_data (
    service_name TEXT NOT NULL,
    data_type TEXT NOT NULL,
    data_key TEXT NOT NULL,
    data JSONB NOT NULL DEFAULT '{}',
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (service_name, data_type, data_key)
);
```

| Column | Type | Description |
|--------|------|-------------|
| `service_name` | TEXT (PK) | Name of the service (finder, validator, synchronizer, monitor) |
| `data_type` | TEXT (PK) | Type of data (candidate, cursor, checkpoint, config) |
| `data_key` | TEXT (PK) | Unique identifier within service/data_type (usually relay URL) |
| `data` | JSONB | Service-specific data structure |
| `updated_at` | BIGINT | Unix timestamp when record was last updated |

**Usage Examples**:
- **Seeder/Finder**: Store discovered relay candidates with `service_name='validator'`, `data_type='candidate'`
- **Validator**: Reads candidates from `service_name='validator'`, tracks validation attempts with `failed_attempts` counter in `data`
- **Finder**: Stores event scanning cursor with `service_name='finder'`, `data_type='cursor'`
- **Synchronizer**: Stores per-relay sync cursors with `data_type='cursor'`

---

## Indexes

### Primary Indexes (from table definitions)

```sql
-- Automatically created
PRIMARY KEY (id) ON events
PRIMARY KEY (url) ON relays
PRIMARY KEY (event_id, relay_url) ON events_relays
PRIMARY KEY (id) ON metadata
PRIMARY KEY (relay_url, generated_at, type) ON relay_metadata
PRIMARY KEY (service_name, data_type, data_key) ON service_data
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

-- Metadata lookups by time and type
CREATE INDEX idx_relay_metadata_generated_at ON relay_metadata (generated_at DESC);
CREATE INDEX idx_relay_metadata_type ON relay_metadata (type);
CREATE INDEX idx_relay_metadata_relay_type_time ON relay_metadata (relay_url, type, generated_at DESC);

-- Service data lookups
CREATE INDEX idx_service_data_service_name ON service_data (service_name);
CREATE INDEX idx_service_data_service_type ON service_data (service_name, data_type);

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
    p_relay_discovered_at   BIGINT,
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
    p_discovered_at BIGINT
) RETURNS VOID;
```

**Idempotency**: Duplicate URLs are silently ignored.

### insert_relay_metadata

Inserts relay metadata with automatic content-addressed deduplication.

```sql
CREATE OR REPLACE FUNCTION insert_relay_metadata(
    p_relay_url             TEXT,
    p_relay_network         TEXT,
    p_relay_discovered_at   BIGINT,
    p_generated_at           BIGINT,
    p_type                  TEXT,
    p_metadata_data         JSONB
) RETURNS VOID;
```

**Parameters**:
- `p_relay_url`: Relay WebSocket URL
- `p_relay_network`: Network type (`clearnet`, `tor`, `i2p`, or `loki`)
- `p_relay_discovered_at`: Relay discovery timestamp
- `p_generated_at`: Metadata snapshot timestamp
- `p_type`: Metadata type (`nip11_fetch`, `nip66_rtt`, `nip66_ssl`, `nip66_geo`, `nip66_net`, `nip66_dns`, `nip66_http`)
- `p_metadata_data`: Complete metadata as JSONB

**Deduplication Process**:
1. Compute SHA-256 hash of JSONB data in PostgreSQL
2. Insert into `metadata` table (ON CONFLICT DO NOTHING)
3. Insert `relay_metadata` junction record linking relay to metadata

### upsert_service_data

Upserts a service data record (for candidates, cursors, state, etc.).

```sql
CREATE OR REPLACE FUNCTION upsert_service_data(
    p_service_name  TEXT,
    p_data_type     TEXT,
    p_data_key      TEXT,
    p_data          JSONB,
    p_updated_at    BIGINT
) RETURNS VOID;
```

### get_service_data

Retrieves service data records with optional key filter.

```sql
CREATE OR REPLACE FUNCTION get_service_data(
    p_service_name  TEXT,
    p_data_type     TEXT,
    p_data_key      TEXT DEFAULT NULL
) RETURNS TABLE (data_key TEXT, data JSONB, updated_at BIGINT);
```

### delete_service_data

Deletes a service data record.

```sql
CREATE OR REPLACE FUNCTION delete_service_data(
    p_service_name  TEXT,
    p_data_type     TEXT,
    p_data_key      TEXT
) RETURNS VOID;
```

---

## Views

### relay_metadata_latest (Materialized View)

Latest metadata for each relay per type.

```sql
CREATE MATERIALIZED VIEW relay_metadata_latest AS
SELECT DISTINCT ON (relay_url, type)
    relay_url,
    type,
    generated_at,
    metadata_id
FROM relay_metadata
ORDER BY relay_url, type, generated_at DESC;
```

**Purpose**: Provides fast access to the most recent metadata for each relay without scanning the full time-series table.

**Usage**:
```sql
-- Get latest NIP-11 data for all relays
SELECT rm.relay_url, m.data
FROM relay_metadata_latest rm
JOIN metadata m ON rm.metadata_id = m.id
WHERE rm.type = 'nip11_fetch';

-- Get relays with recent RTT data
SELECT rm.relay_url, m.data->>'rtt_open' AS rtt_open
FROM relay_metadata_latest rm
JOIN metadata m ON rm.metadata_id = m.id
WHERE rm.type = 'nip66_rtt';
```

**Refresh**: This materialized view should be refreshed periodically:
```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY relay_metadata_latest;
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
    SELECT relay_url, AVG((data->>'rtt_open')::int), AVG((data->>'rtt_read')::int), AVG((data->>'rtt_write')::int)
    FROM (
        SELECT rm.relay_url, m.data,
               ROW_NUMBER() OVER (PARTITION BY rm.relay_url ORDER BY rm.generated_at DESC) AS rn
        FROM relay_metadata rm
        JOIN metadata m ON rm.metadata_id = m.id
        WHERE rm.type = 'nip66_rtt'
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

Extracts tag values from tags array for single-character tag keys.

```sql
CREATE OR REPLACE FUNCTION tags_to_tagvalues(p_tags JSONB)
RETURNS TEXT[]
LANGUAGE plpgsql
IMMUTABLE
RETURNS NULL ON NULL INPUT
AS $$
BEGIN
    RETURN (
        SELECT array_agg(tag_element->>1)
        FROM jsonb_array_elements(p_tags) AS tag_element
        WHERE length(tag_element->>0) = 1
    );
END;
$$;
```

**Purpose**: Extracts the second element (value) from tags where the first element (key) is a single character. This enables GIN index searches on standard Nostr tag values (e, p, r, d, t, etc.).

**Example**:
```sql
-- Find events referencing a specific event ID
-- (where tags contains ["e", "abc123def456..."])
SELECT * FROM events
WHERE tagvalues @> ARRAY['abc123def456...'];

-- Find events mentioning a specific pubkey
-- (where tags contains ["p", "fedcba987654..."])
SELECT * FROM events
WHERE tagvalues @> ARRAY['fedcba987654...'];
```

**Note**: Only single-character tag keys (standard Nostr tags) are indexed. Multi-character keys are ignored to keep the index focused on common query patterns.

### Cleanup Functions

Cleanup functions for orphaned records and failed candidates.

```sql
-- Delete events without relay associations
CREATE OR REPLACE FUNCTION delete_orphan_events() RETURNS BIGINT;

-- Delete unreferenced metadata records
CREATE OR REPLACE FUNCTION delete_orphan_metadata() RETURNS BIGINT;

-- Delete validator candidates that exceeded max failed attempts
CREATE OR REPLACE FUNCTION delete_failed_candidates(
    p_max_attempts INTEGER DEFAULT 10
) RETURNS BIGINT;
```

**Usage**:
```sql
SELECT delete_orphan_events();     -- Returns count of deleted rows
SELECT delete_orphan_metadata();   -- Returns count of deleted rows
SELECT delete_failed_candidates(); -- Uses default threshold (10)
SELECT delete_failed_candidates(5); -- Custom threshold
```

**Note**: The `delete_failed_candidates` function looks for `service_data` records where `service_name='validator'`, `data_type='candidate'`, and `data->>'failed_attempts'` exceeds the threshold.

---

## Data Types

### Binary Fields (BYTEA)

The following fields use BYTEA for 50% space savings:

| Field | Size | Notes |
|-------|------|-------|
| `events.id` | 32 bytes | Event ID (SHA-256) |
| `events.pubkey` | 32 bytes | Public key |
| `events.sig` | 64 bytes | Schnorr signature |
| `metadata.id` | 32 bytes | Content hash (SHA-256 of JSONB data) |
| `relay_metadata.metadata_id` | 32 bytes | Reference to metadata.id |

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
\i postgres/init/01_functions_utility.sql
\i postgres/init/02_tables.sql
\i postgres/init/03_functions_crud.sql
\i postgres/init/04_functions_cleanup.sql
\i postgres/init/05_views.sql
\i postgres/init/06_materialized_views.sql
\i postgres/init/07_functions_refresh.sql
\i postgres/init/08_indexes.sql
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
SELECT delete_orphan_metadata();
SELECT delete_failed_candidates();
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
