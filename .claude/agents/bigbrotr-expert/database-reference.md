# Database Reference

Complete PostgreSQL schema documentation for BigBrotr including tables, stored procedures, views, indexes, and sample queries.

## Schema Overview

BigBrotr uses PostgreSQL 15+ with extensions for efficient Nostr data storage:
- `pgcrypto`: SHA-256 hashing for content-addressed metadata
- `btree_gin`: GIN indexes for tag arrays

**Key Design Principles**:
- Content-addressed storage for deduplication
- Junction tables for many-to-many relationships
- Generated columns for computed indexes
- Idempotent stored procedures with `ON CONFLICT DO NOTHING`

---

## Tables

### relays

Registry of validated Nostr relays.

```sql
CREATE TABLE relays (
    url          TEXT    PRIMARY KEY,
    network      TEXT    NOT NULL,
    discovered_at BIGINT NOT NULL
);
```

**Columns**:
- `url`: WebSocket URL (e.g., "wss://relay.example.com")
- `network`: Network type ("clearnet" or "tor")
- `discovered_at`: Unix timestamp when relay was first discovered and validated

**Purpose**: Only validated relays (passed Validator service) are stored here. Candidates are stored in `service_data`.

---

### events

Stores all Nostr events with computed tag index.

```sql
CREATE TABLE events (
    id          BYTEA       PRIMARY KEY,
    pubkey      BYTEA       NOT NULL,
    created_at  BIGINT      NOT NULL,
    kind        INTEGER     NOT NULL,
    tags        JSONB       NOT NULL,
    tagvalues   TEXT[]      GENERATED ALWAYS AS (tags_to_tagvalues(tags)) STORED,
    content     TEXT        NOT NULL,
    sig         BYTEA       NOT NULL
);
```

**Columns**:
- `id`: SHA-256 hash of serialized event (32 bytes)
- `pubkey`: Author public key (32 bytes)
- `created_at`: Unix timestamp
- `kind`: Event kind (0-65535)
- `tags`: JSONB array of tag arrays
- `tagvalues`: Generated array of tag values for indexing
- `content`: Event content
- `sig`: Schnorr signature (64 bytes)

**Storage Format**: BYTEA for 50% space savings vs CHAR(64)

---

### events_relays

Junction table tracking which events are hosted on which relays.

```sql
CREATE TABLE events_relays (
    event_id    BYTEA   NOT NULL,
    relay_url   TEXT    NOT NULL,
    seen_at     BIGINT  NOT NULL,
    PRIMARY KEY (event_id, relay_url),
    FOREIGN KEY (event_id)   REFERENCES events(id)  ON DELETE CASCADE,
    FOREIGN KEY (relay_url)  REFERENCES relays(url) ON DELETE CASCADE
);
```

**Columns**:
- `event_id`: Reference to events.id
- `relay_url`: Reference to relays.url
- `seen_at`: Unix timestamp when event was first seen on relay

---

### metadata

Unified storage for NIP-11 and NIP-66 metadata documents (content-addressed).

```sql
CREATE TABLE metadata (
    id      BYTEA   PRIMARY KEY,
    data    JSONB   NOT NULL
);
```

**Columns**:
- `id`: SHA-256 hash of JSON data (computed by PostgreSQL)
- `data`: Complete JSON document (NIP-11 or NIP-66)

**Deduplication**: Multiple relays with identical metadata share the same record.

---

### relay_metadata

Time-series metadata snapshots linking relays to metadata records.

```sql
CREATE TABLE relay_metadata (
    relay_url       TEXT    NOT NULL,
    snapshot_at     BIGINT  NOT NULL,
    type            TEXT    NOT NULL,
    metadata_id     BYTEA   NOT NULL,
    PRIMARY KEY (relay_url, snapshot_at, type),
    FOREIGN KEY (relay_url)    REFERENCES relays(url)    ON DELETE CASCADE,
    FOREIGN KEY (metadata_id)  REFERENCES metadata(id)   ON DELETE CASCADE,
    CHECK (type IN ('nip11', 'nip66_rtt', 'nip66_ssl', 'nip66_geo'))
);
```

**Columns**:
- `relay_url`: Reference to relays.url
- `snapshot_at`: Unix timestamp when metadata was collected
- `type`: Metadata type ('nip11', 'nip66_rtt', 'nip66_ssl', 'nip66_geo')
- `metadata_id`: Reference to metadata.id

**Purpose**: Tracks metadata changes over time. Each relay can have multiple snapshots per type.

---

### service_data

Per-service state storage for candidates, cursors, and other data.

```sql
CREATE TABLE service_data (
    service_name    TEXT    NOT NULL,
    data_type       TEXT    NOT NULL,
    data_key        TEXT    NOT NULL,
    data            JSONB   NOT NULL DEFAULT '{}',
    updated_at      BIGINT  NOT NULL,
    PRIMARY KEY (service_name, data_type, data_key)
);
```

**Columns**:
- `service_name`: Name of service ("finder", "validator", "synchronizer", "monitor")
- `data_type`: Type of data ("candidate", "cursor", "checkpoint")
- `data_key`: Unique identifier (usually relay URL)
- `data`: JSONB data specific to service
- `updated_at`: Unix timestamp of last update

**Examples**:
- Finder candidates: `("finder", "candidate", "wss://relay.com", {"failed_attempts": 0}, 1700000000)`
- Synchronizer cursor: `("synchronizer", "cursor", "relay.example.com", {"timestamp": 123456}, 1700000001)`

---

## Stored Procedures

### insert_event

Atomically inserts event + relay + junction record.

```sql
FUNCTION insert_event(
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
) RETURNS VOID
```

**Idempotency**: Uses `ON CONFLICT DO NOTHING` on all inserts.

**Usage**:
```sql
SELECT insert_event(
    decode('abc123...', 'hex'),   -- event_id
    decode('def456...', 'hex'),   -- pubkey
    1700000000,                    -- created_at
    1,                             -- kind
    '[]'::JSONB,                   -- tags
    'Hello Nostr',                 -- content
    decode('789ghi...', 'hex'),   -- sig
    'relay.example.com',           -- relay_url
    'clearnet',                    -- relay_network
    1700000000,                    -- relay_discovered_at
    1700000001                     -- seen_at
);
```

---

### insert_relay

Inserts a validated relay record.

```sql
FUNCTION insert_relay(
    p_url           TEXT,
    p_network       TEXT,
    p_discovered_at BIGINT
) RETURNS VOID
```

**Usage**:
```sql
SELECT insert_relay('relay.example.com', 'clearnet', 1700000000);
```

---

### insert_relay_metadata

Inserts relay metadata with automatic deduplication.

```sql
FUNCTION insert_relay_metadata(
    p_relay_url         TEXT,
    p_relay_network     TEXT,
    p_relay_discovered_at BIGINT,
    p_snapshot_at       BIGINT,
    p_type              TEXT,
    p_metadata_data     JSONB
) RETURNS VOID
```

**Hash Computation**: Metadata hash is computed in PostgreSQL using `sha256(convert_to(p_metadata_data::TEXT, 'UTF8'))`.

**Usage**:
```sql
SELECT insert_relay_metadata(
    'relay.example.com',
    'clearnet',
    1700000000,
    1700000001,
    'nip11',
    '{"name": "Test Relay", "supported_nips": [1, 2, 9, 11]}'::JSONB
);
```

---

### upsert_service_data

Upserts a service data record.

```sql
FUNCTION upsert_service_data(
    p_service_name  TEXT,
    p_data_type     TEXT,
    p_key           TEXT,
    p_value         JSONB,
    p_updated_at    BIGINT
) RETURNS VOID
```

**Usage**:
```sql
SELECT upsert_service_data(
    'finder',
    'candidate',
    'relay.example.com',
    '{}'::JSONB,
    1700000000
);
```

---

### delete_service_data

Deletes a service data record.

```sql
FUNCTION delete_service_data(
    p_service_name  TEXT,
    p_data_type     TEXT,
    p_key           TEXT
) RETURNS VOID
```

---

### Maintenance Procedures

**delete_orphan_metadata()**: Removes metadata records not referenced by any relay_metadata. Returns count.

**delete_orphan_events()**: Removes events not referenced by any events_relays. Returns count.

**cleanup_failed_candidates(p_max_attempts INTEGER DEFAULT 10)**: Removes validator candidates with failed_attempts >= threshold. Returns count.

**cleanup_old_metadata_snapshots(p_keep_count INTEGER DEFAULT 30)**: Keeps only the N most recent metadata snapshots per relay+type. Returns count.

**run_maintenance(p_keep_metadata_snapshots INTEGER DEFAULT 30, p_max_candidate_attempts INTEGER DEFAULT 10)**: Runs all maintenance tasks. Returns table of (task, deleted_count).

**refresh_relay_metadata_latest()**: Refreshes the relay_metadata_latest materialized view concurrently.

---

## Views

### relay_metadata_latest (Materialized)

Latest NIP-11 and NIP-66 data per relay.

**Refresh**: Once daily via `SELECT refresh_relay_metadata_latest();`

**Columns**:
- `relay_url`, `network`, `discovered_at`
- `nip11_at`, `nip11_id`, `nip11_data`
- `nip66_rtt_at`, `nip66_rtt_id`, `nip66_rtt_data`
- `nip66_ssl_at`, `nip66_ssl_id`, `nip66_ssl_data`
- `nip66_geo_at`, `nip66_geo_id`, `nip66_geo_data`
- `rtt_open`, `rtt_read`, `rtt_write`
- `is_openable`, `is_readable`, `is_writable`
- `ssl_valid`, `ssl_issuer`, `ssl_expires`
- `geohash`, `geo_country`
- `nip11_name`, `nip11_description`, `nip11_supported_nips`, `nip11_limitation`

**Usage**:
```sql
-- Find readable relays
SELECT relay_url, rtt_read
FROM relay_metadata_latest
WHERE is_readable = TRUE
ORDER BY rtt_read ASC;

-- Find relays needing check (older than 1 hour)
SELECT relay_url
FROM relay_metadata_latest
WHERE nip66_rtt_at < EXTRACT(EPOCH FROM NOW() - INTERVAL '1 hour');
```

---

### events_statistics

Global event statistics.

**Columns**:
- `total_events`, `unique_pubkeys`, `unique_kinds`
- `earliest_event_timestamp`, `latest_event_timestamp`
- `regular_events`, `replaceable_events`, `ephemeral_events`, `addressable_events`
- `events_last_hour`, `events_last_24h`, `events_last_7d`, `events_last_30d`

---

### relays_statistics

Per-relay statistics with event counts and performance metrics.

**Columns**:
- `relay_url`, `network`, `discovered_at`
- `event_count`, `unique_pubkeys`
- `first_event_timestamp`, `last_event_timestamp`
- `avg_rtt_open`, `avg_rtt_read`, `avg_rtt_write`

---

### Other Views

- `kind_counts_total`: Event counts by kind across all relays
- `kind_counts_by_relay`: Event counts by kind for each relay
- `pubkey_counts_total`: Event counts by pubkey across all relays
- `pubkey_counts_by_relay`: Event counts by pubkey for each relay

---

## Indexes

### Events Table

```sql
-- Fast retrieval of recent events
idx_events_created_at ON events(created_at DESC)

-- Filter by kind
idx_events_kind ON events(kind)

-- Recent events of specific type
idx_events_kind_created_at ON events(kind, created_at DESC)

-- User timeline
idx_events_pubkey_created_at ON events(pubkey, created_at DESC)

-- User-specific event types
idx_events_pubkey_kind_created_at ON events(pubkey, kind, created_at DESC)

-- Tag-based queries (GIN index)
idx_events_tagvalues ON events USING gin(tagvalues)
```

### Events_Relays Junction Table

```sql
-- Find relays hosting an event
idx_events_relays_event_id ON events_relays(event_id)

-- List events from a relay
idx_events_relays_relay_url ON events_relays(relay_url)

-- Recent activity
idx_events_relays_seen_at ON events_relays(seen_at DESC)

-- Sync progress tracking (CRITICAL)
idx_events_relays_relay_seen ON events_relays(relay_url, seen_at DESC)
```

### Relay_Metadata Table

```sql
-- Recent metadata snapshots
idx_relay_metadata_snapshot_at ON relay_metadata(snapshot_at DESC)

-- Deduplication verification
idx_relay_metadata_metadata_id ON relay_metadata(metadata_id)

-- Latest metadata per relay (CRITICAL FOR VIEWS)
idx_relay_metadata_latest ON relay_metadata(relay_url, type, snapshot_at DESC)
```

---

## Sample Queries

### Find Events by Tag

```sql
-- Events mentioning a specific pubkey
SELECT e.*
FROM events e
WHERE e.tagvalues @> ARRAY['p', '<pubkey_hex>']
ORDER BY e.created_at DESC
LIMIT 100;

-- Events with specific hashtag
SELECT e.*
FROM events e
WHERE e.tagvalues @> ARRAY['t', 'bitcoin']
ORDER BY e.created_at DESC;
```

### Relay Discovery

```sql
-- Find all relays mentioned in events (NIP-65)
SELECT DISTINCT jsonb_array_elements(tags)->1 AS relay_url
FROM events
WHERE kind = 10002  -- NIP-65 relay list
  AND jsonb_array_elements(tags)->0 = '"r"';
```

### Metadata History

```sql
-- Get NIP-11 history for a relay
SELECT
    rm.snapshot_at,
    m.data->>'name' AS relay_name,
    m.data->'supported_nips' AS nips
FROM relay_metadata rm
JOIN metadata m ON rm.metadata_id = m.id
WHERE rm.relay_url = 'relay.example.com'
  AND rm.type = 'nip11'
ORDER BY rm.snapshot_at DESC;
```

### Performance Analysis

```sql
-- Top 10 fastest relays (by read RTT)
SELECT
    relay_url,
    rtt_read,
    geo_country,
    nip11_name
FROM relay_metadata_latest
WHERE is_readable = TRUE
ORDER BY rtt_read ASC
LIMIT 10;

-- Relays by network type
SELECT
    network,
    COUNT(*) AS relay_count,
    COUNT(*) FILTER (WHERE is_readable = TRUE) AS readable_count
FROM relay_metadata_latest
GROUP BY network;
```

### Event Statistics

```sql
-- Most active authors
SELECT
    encode(pubkey, 'hex') AS pubkey_hex,
    COUNT(*) AS event_count,
    COUNT(DISTINCT kind) AS kinds_used
FROM events
GROUP BY pubkey
ORDER BY event_count DESC
LIMIT 100;

-- Event distribution by kind
SELECT
    kind,
    COUNT(*) AS event_count,
    COUNT(DISTINCT pubkey) AS unique_authors
FROM events
GROUP BY kind
ORDER BY event_count DESC;
```

### Synchronizer Queries

```sql
-- Get latest event timestamp for a relay (for cursor)
SELECT MAX(e.created_at) AS max_created_at
FROM events e
JOIN events_relays er ON e.id = er.event_id
WHERE er.relay_url = 'relay.example.com';

-- Find relays to sync (recent metadata, readable)
SELECT relay_url
FROM relay_metadata_latest
WHERE nip66_rtt_at > EXTRACT(EPOCH FROM NOW() - INTERVAL '12 hours')
  AND is_readable = TRUE;
```

---

## Utility Functions

### tags_to_tagvalues

Converts JSONB tags array to TEXT array for GIN indexing.

```sql
FUNCTION tags_to_tagvalues(tags JSONB) RETURNS TEXT[]
```

**Example**:
```sql
-- Input: [["e", "abc123"], ["p", "def456"]]
-- Output: {"e", "abc123", "p", "def456"}
```

---

## Schema Verification

The Initializer service verifies schema on startup:

```sql
-- Check extensions
SELECT extname FROM pg_extension
WHERE extname IN ('pgcrypto', 'btree_gin');

-- Check tables
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE';

-- Check procedures
SELECT routine_name FROM information_schema.routines
WHERE routine_schema = 'public';

-- Check views
SELECT table_name FROM information_schema.views
WHERE table_schema = 'public';
```

---

## Maintenance Schedule

**Daily**:
- Refresh materialized view: `SELECT refresh_relay_metadata_latest();`

**Weekly**:
- Run maintenance: `SELECT * FROM run_maintenance();`

**Monthly**:
- Vacuum analyze: `VACUUM ANALYZE;`
- Reindex: `REINDEX DATABASE bigbrotr;`
