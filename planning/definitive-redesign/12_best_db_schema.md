# Best DB Schema Proposal

## Purpose

This file is the **consolidated target shared-DB schema** for the definitive
redesign.

It reflects the current final planning direction after comparing:

- the current schema;
- the earlier redesign drafts;
- the clarified storage philosophy;
- the clarified efficiency philosophy;
- the clarified service-boundary decisions.

This is not a migration script.
It is the answer to:

> What should the shared canonical PostgreSQL schema look like if we optimize
> for correctness, extensibility, and large-scale operational discipline?

---

## 1. What Is Fixed

The following are now treated as closed design decisions.

### 1.1 Shared DB philosophy

The shared database should contain:

- canonical storage tables;
- one shared operational-state subsystem;
- shared derived tables that genuinely earn their storage;
- views or projections for convenience shapes that do not.

It should not be shaped around the convenience of today’s services.

### 1.2 Core canonical concepts

The conceptual core is:

- `relay`
- `event`
- `event_observation`
- `document`
- `relay_document`
- `service_state`

These are the stable future concepts the rest of the shared schema builds on.

### 1.3 Minimal stored columns

Only semantically essential columns should exist in the shared schema.

This means:

- no `ingest_id`;
- no generic `updated_at` in `service_state`;
- no `stored_at` added everywhere out of habit;
- no payload duplication in narrow current tables.

### 1.4 Large-DB assumption

The schema must assume very large storage tables.

So the target design is:

- page-first;
- cursor-first where appropriate;
- chunk-friendly;
- partition-friendly on large archive relations;
- hostile to full-fetch runtime patterns.

### 1.5 Incremental maintenance model

Derived tables are maintained:

- incrementally by default;
- from canonical upstream storage sources;
- with full rebuild after storage delete or rewrite that breaks incremental
  correctness.

### 1.6 Heavy work policy

Some derivations are naturally heavier than others.

That is acceptable if they are:

- bounded;
- chunked;
- resumable;
- kept out of the hot path;
- not forced into monolithic recomputation as the normal runtime path.

---

## 2. Naming Decisions

These naming decisions are part of the future target shape.

### 2.1 `document`, not `metadata`

The core concept is deduplicated JSONB, not only “relay metadata”.

So the future canonical name is:

- `document`

not:

- `metadata`

### 2.2 `event_observation`, not `event_observation`

The relation means:

- this event was observed on this relay at this time

So the future conceptual name is:

- `event_observation`

even if current code and SQL still use `event_observation`.

### 2.3 `associated_at` for relay-document history

The relay-document relation should express when the document became associated
to that relay record.

So the correct timestamp name on the relation is:

- `associated_at`

### 2.4 `d_value` for addressable identity

For addressable events, the third key component is the value of the `d` tag.

The preferred explicit future name is:

- `d_value`

This is clearer than `d_tag` while still staying faithful to NIP-01 semantics.

### 2.5 `score`, not `raw_score`, and not `rank`

If the shared DB stores public ranking outputs, the essential persisted value
is:

- `score`

The ordinal rank position is derivable and should not be stored by default.

---

## 3. Design Rules

### 3.1 Storage is the source of truth

The canonical source of truth is the storage layer.

Everything else must be derivable from it.

### 3.2 Derived tables are DB-shaped, not service-shaped

A derived table exists because it is good shared database design, not because:

- the `Ranker` likes it;
- the `Monitor` likes it;
- the `Api` likes it.

### 3.3 Shared operational state remains shared

Services get one shared operational persistence substrate.

They do not get bespoke schema ownership unless a concept becomes a true
canonical shared concept.

### 3.4 Private compute remains private

If a service needs algorithm-specific structures, it builds them privately from
the shared canonical DB rather than distorting the shared schema.

### 3.5 Convenience belongs in views or the read core

If a shape exists mainly to simplify reads, the default target is:

- a view;
- a materialized view;
- or a read-core resource backed by a relation/query handler.

---

## 4. Schema Inventory

The target shared schema is divided into:

1. canonical storage tables;
2. shared operational state;
3. narrow current tables;
4. shared analytics tables;
5. shared interaction tables;
6. public score output tables;
7. views.

---

## 5. Canonical Storage Tables

These are the durable archive tables.

## 5.1 `relay`

```sql
relay (
  url             text        primary key,
  network         text        not null,
  stored_at       bigint      not null
)
```

### Why this shape

- minimal relay identity;
- stable routing/storage dimension;
- one canonical archive-entry timestamp where it is semantically justified.

### Notes

- `stored_at` is kept only here because the relay row meaning is archive entry
  into the shared canonical relay pool;
- no parsed URL fragment columns are stored by default.

## 5.2 `event`

```sql
event (
  id              bytea       primary key,
  pubkey          bytea       not null,
  created_at      bigint      not null,
  kind            integer     not null,
  tags            jsonb,
  tagvalues       text[]      not null,
  content         text,
  sig             bytea
)
```

### Why this shape

- keeps the strong existing ideas:
  - binary IDs and pubkeys;
  - stored `tagvalues`;
  - storage-profile flexibility;
- avoids adding helper columns that are not semantically part of the event
  archive.

### Notes

- `created_at` is the protocol/domain timestamp;
- no `stored_at`;
- no `ingest_id`.

## 5.3 `event_observation`

```sql
event_observation (
  event_id         bytea       not null references event(id) on delete cascade,
  relay_url        text        not null references relay(url) on delete cascade,
  observed_at      bigint      not null,
  primary key (event_id, relay_url)
)
```

### Why this shape

- preserves provenance without pretending it defines event existence;
- allows events to exist in the archive even without relay provenance;
- stores only the timestamp that semantically belongs to the observation
  relation.

### Notes

- this is the future conceptual meaning of today’s `event_observation`;
- no observation counters or last-seen helpers are stored by default.

## 5.4 `document`

```sql
document (
  id              bytea       primary key,
  body            jsonb       not null
)
```

### Why this shape

- the core concept is content-addressed deduplicated JSONB;
- the document itself should stay small and role-agnostic;
- relation-specific meaning belongs on the relation that uses the document.

### Notes

- no `type` column in the primary key;
- no `stored_at`;
- no extra helper columns by default.

## 5.5 `relay_document`

```sql
relay_document (
  relay_url        text        not null references relay(url) on delete cascade,
  role             text        not null,
  associated_at    bigint      not null,
  document_id      bytea       not null references document(id) on delete cascade,
  primary key (relay_url, role, associated_at, document_id)
)
```

### Why this shape

- keeps the strong append-only historical relation from the current design;
- generalizes it away from relay-only “metadata” language;
- makes current winner derivation straightforward by ordering on
  `associated_at`.

### Notes

- this is the canonical history table for relay-associated JSON documents;
- `role` is where semantic role attachment belongs.

---

## 6. Shared Operational State

## 6.1 `service_state`

```sql
service_state (
  owner            text        not null,
  state_type       text        not null,
  state_key        text        not null,
  state_value      jsonb       not null default '{}'::jsonb,
  primary key (owner, state_type, state_key)
)
```

### Why this shape

- preserves one shared operational persistence substrate;
- stays generic enough for future unknown services;
- avoids forcing today’s services into future schema ownership.

### Notes

- no `updated_at`;
- any per-state timestamp belongs inside `state_value` if the state itself
  needs it;
- this table is operational persistence, not canonical domain archive.

---

## 7. Narrow Current Tables

These are current winner maps, not wide denormalized payload caches.

## 7.1 `replaceable_event_current`

```sql
replaceable_event_current (
  pubkey           bytea       not null,
  kind             integer     not null,
  event_id         bytea       not null references event(id) on delete cascade,
  primary key (pubkey, kind),
  unique (event_id)
)
```

## 7.2 `addressable_event_current`

```sql
addressable_event_current (
  pubkey           bytea       not null,
  kind             integer     not null,
  d_value          text        not null,
  event_id         bytea       not null references event(id) on delete cascade,
  primary key (pubkey, kind, d_value),
  unique (event_id)
)
```

## 7.3 `relay_document_current`

```sql
relay_document_current (
  relay_url        text        not null references relay(url) on delete cascade,
  role             text        not null,
  associated_at    bigint      not null,
  document_id      bytea       not null references document(id) on delete cascade,
  primary key (relay_url, role)
)
```

### Why current tables are this narrow

- current tables should identify the current winner;
- richer payload is reconstructed via joins, views, or read-core resources;
- this keeps storage smaller and refresh cheaper.

### What is intentionally missing

- duplicated `tags`;
- duplicated `tagvalues`;
- duplicated `content`;
- duplicated `sig`;
- duplicated JSON documents.

### Contact graph note

The current contact graph is **not** materialized by default as a stored table
set.

The future default is:

- keep current kind-`3` winners through `replaceable_event_current`;
- derive current social edges through a view or promote later only if proven
  necessary.

---

## 8. Shared Analytics Tables

These tables are justified because they are:

- shared;
- incrementally maintainable;
- expensive enough or useful enough to earn storage.

## 8.1 `pubkey_kind_stats`

```sql
pubkey_kind_stats (
  pubkey                  bytea       not null,
  kind                    integer     not null,
  event_count             bigint      not null default 0,
  first_event_created_at  bigint,
  last_event_created_at   bigint,
  primary key (pubkey, kind)
)
```

## 8.2 `pubkey_relay_stats`

```sql
pubkey_relay_stats (
  pubkey                  bytea       not null,
  relay_url               text        not null references relay(url) on delete cascade,
  event_count             bigint      not null default 0,
  first_event_created_at  bigint,
  last_event_created_at   bigint,
  primary key (pubkey, relay_url)
)
```

## 8.3 `relay_kind_stats`

```sql
relay_kind_stats (
  relay_url               text        not null references relay(url) on delete cascade,
  kind                    integer     not null,
  event_count             bigint      not null default 0,
  first_event_created_at  bigint,
  last_event_created_at   bigint,
  primary key (relay_url, kind)
)
```

## 8.4 `pubkey_stats`

```sql
pubkey_stats (
  pubkey                  bytea       primary key,
  event_count             bigint      not null default 0,
  kind_count              integer     not null default 0,
  relay_count             integer     not null default 0,
  first_event_created_at  bigint,
  last_event_created_at   bigint,
  events_last_24h         bigint      not null default 0,
  events_last_7d          bigint      not null default 0,
  events_last_30d         bigint      not null default 0,
  regular_count           bigint      not null default 0,
  replaceable_count       bigint      not null default 0,
  ephemeral_count         bigint      not null default 0,
  addressable_count       bigint      not null default 0
)
```

## 8.5 `kind_stats`

```sql
kind_stats (
  kind                    integer     primary key,
  event_count             bigint      not null default 0,
  pubkey_count            integer     not null default 0,
  relay_count             integer     not null default 0,
  first_event_created_at  bigint,
  last_event_created_at   bigint,
  events_last_24h         bigint      not null default 0,
  events_last_7d          bigint      not null default 0,
  events_last_30d         bigint      not null default 0
)
```

## 8.6 `relay_stats`

```sql
relay_stats (
  relay_url               text          primary key references relay(url) on delete cascade,
  event_count             bigint        not null default 0,
  pubkey_count            integer       not null default 0,
  kind_count              integer       not null default 0,
  first_event_created_at  bigint,
  last_event_created_at   bigint,
  events_last_24h         bigint        not null default 0,
  events_last_7d          bigint        not null default 0,
  events_last_30d         bigint        not null default 0,
  regular_count           bigint        not null default 0,
  replaceable_count       bigint        not null default 0,
  ephemeral_count         bigint        not null default 0,
  addressable_count       bigint        not null default 0,
  avg_rtt_open            numeric(10,2),
  avg_rtt_read            numeric(10,2),
  avg_rtt_write           numeric(10,2)
)
```

## 8.7 `daily_counts`

```sql
daily_counts (
  day                     date        primary key,
  event_count             bigint      not null,
  pubkey_count            bigint      not null,
  kind_count              bigint      not null
)
```

### Why these names

The future convention is:

- `event_count` means raw event rows counted;
- `pubkey_count`, `kind_count`, `relay_count` mean distinct entity counts in
  that summary context.

This is cleaner than mixing short names with `unique_*_count`.

---

## 9. Shared Interaction Tables

These tables store shared canonical interaction facts, not algorithm outputs.

## 9.1 `pubkey_interaction_stats`

```sql
pubkey_interaction_stats (
  pubkey                  bytea       primary key,
  post_count              bigint      not null default 0,
  reply_count             bigint      not null default 0,
  reaction_sent_count     bigint      not null default 0,
  reaction_received_count bigint      not null default 0,
  repost_sent_count       bigint      not null default 0,
  repost_received_count   bigint      not null default 0,
  report_sent_count       bigint      not null default 0,
  report_received_count   bigint      not null default 0,
  zap_sent_count          bigint      not null default 0,
  zap_received_count      bigint      not null default 0,
  zap_sent_amount         bigint      not null default 0,
  zap_received_amount     bigint      not null default 0,
  first_created_at        bigint,
  activity_hours          integer[24] not null default array_fill(0, array[24]),
  topic_counts            jsonb       not null default '{}'::jsonb,
  follower_count          bigint      not null default 0,
  following_count         bigint      not null default 0
)
```

## 9.2 `event_interaction_stats`

```sql
event_interaction_stats (
  event_id                bytea       primary key references event(id) on delete cascade,
  comment_count           bigint      not null default 0,
  quote_count             bigint      not null default 0,
  repost_count            bigint      not null default 0,
  reaction_count          bigint      not null default 0,
  zap_count               bigint      not null default 0,
  zap_amount              bigint      not null default 0
)
```

## 9.3 `addressable_interaction_stats`

```sql
addressable_interaction_stats (
  pubkey                  bytea       not null,
  kind                    integer     not null,
  d_value                 text        not null,
  comment_count           bigint      not null default 0,
  quote_count             bigint      not null default 0,
  repost_count            bigint      not null default 0,
  reaction_count          bigint      not null default 0,
  zap_count               bigint      not null default 0,
  zap_amount              bigint      not null default 0,
  primary key (pubkey, kind, d_value)
)
```

## 9.4 `identifier_interaction_stats`

```sql
identifier_interaction_stats (
  identifier              text        primary key,
  comment_count           bigint      not null default 0,
  reaction_count          bigint      not null default 0,
  k_tags                  text[]      not null default '{}'::text[]
)
```

### Why score is not mixed into these tables

These tables are shared facts.

Scores are downstream algorithm outputs and should remain separate.

---

## 10. Public Score Output Tables

If the shared DB stores public scoring outputs, the minimal target shape is:

## 10.1 `pubkey_score`

```sql
pubkey_score (
  pubkey                  bytea       primary key,
  score                   double precision not null
)
```

## 10.2 `event_score`

```sql
event_score (
  event_id                bytea       primary key references event(id) on delete cascade,
  score                   double precision not null
)
```

## 10.3 `addressable_score`

```sql
addressable_score (
  pubkey                  bytea       not null,
  kind                    integer     not null,
  d_value                 text        not null,
  score                   double precision not null,
  primary key (pubkey, kind, d_value)
)
```

## 10.4 `identifier_score`

```sql
identifier_score (
  identifier              text        primary key,
  score                   double precision not null
)
```

### Why this is minimal

- score is the essential persisted output;
- ordinal rank position is derivable;
- run metadata belongs to private compute state or operational state, not to
  mandatory shared schema tables.

---

## 11. Views And Read-Projections

The following are strong default view candidates:

```sql
replaceable_event_current_v
addressable_event_current_v
relay_document_current_v
contact_edge_current_v
relay_software_counts_v
supported_nip_counts_v
```

### Why these are views by default

They are mainly convenience or reporting shapes.

They should become stored only if they later prove:

- strong shared hot-path value;
- clear performance payoff;
- acceptable refresh cost.

---

## 12. Partitioning And Indexing Guidance

## 12.1 Partitioning

Recommended partition candidates:

- `event`
- `event_observation`
- possibly `relay_document`
- revisit `document` only if volume justifies it

Default non-partition candidates:

- `relay`
- `service_state`
- narrow current tables;
- most shared derived tables.

### Why

Partitioning should be used where archive volume demands it, not applied to
everything by default.

## 12.2 Important index direction

Important index categories include:

- event timeline indexes;
- event-by-kind and event-by-pubkey indexes;
- GIN on `event.tagvalues`;
- current-table winner lookup indexes;
- `relay_document` current-history ordering indexes;
- summary-table PK and common lookup indexes;
- protocol/read-layer indexes for bounded pagination paths.

---

## 13. Maintenance Model

## 13.1 Canonical upstream sources

Derived tables do not all read the same cursor.

They read deltas from their own canonical upstream source, for example:

- event-driven deltas from `event`;
- observation-driven deltas from `event_observation`;
- relay-document deltas from `relay_document`.

## 13.2 Incremental by default

The normal path is:

- consume new upstream rows in chunks;
- update derived tables incrementally;
- persist cursors in `service_state`.

## 13.3 Rebuild after destructive storage changes

If storage rows are deleted or rewritten in a way that breaks incremental
correctness, the affected derivations should be rebuilt from scratch.

This is deliberate.

The design is not trying to be magically delete-safe for every possible change.

## 13.4 Heavy derivations must be chunkable

Any derivation that is naturally heavier must be designed to run:

- in bounded chunks;
- with resumable progress;
- outside the hot path;
- without requiring full archive scans as the normal runtime case.

---

## 14. Final Shared Schema In One Page

### Canonical storage

- `relay`
- `event`
- `event_observation`
- `document`
- `relay_document`

### Shared operational state

- `service_state`

### Narrow current tables

- `replaceable_event_current`
- `addressable_event_current`
- `relay_document_current`

### Shared analytics

- `pubkey_kind_stats`
- `pubkey_relay_stats`
- `relay_kind_stats`
- `pubkey_stats`
- `kind_stats`
- `relay_stats`
- `daily_counts`

### Shared interaction facts

- `pubkey_interaction_stats`
- `event_interaction_stats`
- `addressable_interaction_stats`
- `identifier_interaction_stats`

### Public score outputs

- `pubkey_score`
- `event_score`
- `addressable_score`
- `identifier_score`

### Views and projections

- `replaceable_event_current_v`
- `addressable_event_current_v`
- `relay_document_current_v`
- `contact_edge_current_v`
- `relay_software_counts_v`
- `supported_nip_counts_v`

This is the target shared schema that the redesign should converge toward.
