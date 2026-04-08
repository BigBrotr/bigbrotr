# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [6.6.8] - 2026-04-08

### Changed

- **Remove jemalloc workaround**: `shutdown_client()` (v6.6.6) addresses the nostr-sdk memory leak at the source — jemalloc is no longer needed as an allocator workaround
- **Remove `gc.collect()` workaround**: PyO3 objects do not form reference cycles, so CPython's reference counting frees them immediately on `del`. Forced GC collection was unnecessary

## [6.6.7] - 2026-04-08

### Fixed

- **Complete `shutdown_client()` adoption**: DVM `__aexit__` now uses `shutdown_client()` instead of direct `client.shutdown()`. Synchronizer worker removes redundant `client.disconnect()` before `shutdown_client()` — `force_remove_all_relays()` already disconnects

## [6.6.6] - 2026-04-08

### Fixed

- **nostr-sdk Client memory leak**: `Client.shutdown()` does not release the internal event database, active subscriptions, or relay connection state on the Rust side. New `shutdown_client()` helper performs `unsubscribe_all()` + `force_remove_all_relays()` + `database().wipe()` before `shutdown()`. Replaces all 7 direct `shutdown()` calls across protocol, synchronizer, monitor client pool, and NIP-66 RTT. Local benchmark confirms RSS stabilizes with zero growth over 100 iterations

## [6.6.5] - 2026-04-08

### Fixed

- **Rust FFI memory fragmentation**: glibc malloc retains per-thread arenas from nostr-sdk Tokio threads and never returns pages to the OS, causing monotonic RSS growth (15 GB in 2 hours). Replaced glibc malloc with jemalloc via `LD_PRELOAD` in the Docker image — jemalloc actively returns freed pages via `madvise(MADV_DONTNEED)`

## [6.6.4] - 2026-04-08

### Changed

- **Schema-agnostic monitoring queries**: all postgres-exporter queries now auto-discover tables, materialized views, and partitioned parents from `pg_catalog` instead of hardcoding names. Adding tables, views, or partitions requires zero monitoring changes

## [6.6.3] - 2026-04-08

### Fixed

- **Monitoring row estimates always 0 for partitioned tables**: `overview` and `row_estimates` queries read `pg_class.reltuples` from partitioned parent tables (`event`, `event_relay`), which PostgreSQL never auto-analyzes. Now aggregates `SUM(child.reltuples)` from partitions via `pg_inherits`, same pattern already used by `table_sizes` since v6.6.0
- **Monitoring index usage and dead tuples showed individual partitions**: `index_usage` reported 32 separate partition entries instead of aggregated parent tables. New `dead_tuples` custom query replaces built-in `pg_stat_user_tables_n_dead_tup` with partition-aggregated version. Both use `COALESCE(parent.relname, s.relname)` + `GROUP BY` to merge partition stats under the parent name

## [6.6.2] - 2026-04-08

### Fixed

- **Event model FFI memory leak**: the `Event` dataclass retained a reference to `nostr_sdk.Event` (Rust FFI / PyO3) for the lifetime of each instance, invisible to Python's garbage collector. With thousands of events flowing through the synchronizer pipeline, Rust-side memory accumulated to 54 GB RSS in production within 11 hours. The v6.6.1 fix addressed `Client` and `EventStream` cleanup but missed `NostrEvent` references inside `Event` wrappers. The model now uses `InitVar` to consume the FFI object during construction and extracts all fields into Python-native types — the Rust reference is never stored on the instance
- **Event model `__getattr__` delegation removed**: replaced magic delegation to the FFI object with explicit domain fields (`id`, `pubkey`, `created_at`, `kind`, `tags`, `content`, `sig`), consistent with `Relay` and `Metadata` models. `_compute_db_params(self)` now reads from `self` fields instead of the FFI object

## [6.6.1] - 2026-04-07

### Fixed

- **nostr-sdk Rust memory leak**: Client and EventStream FFI objects allocated memory on the Rust side invisible to Python's garbage collector, causing the Synchronizer to reach 27 GB RSS. EventStream references are now explicitly deleted after consumption, clients are shut down (not just disconnected) when discarded, and `gc.collect()` is called after each relay in the Synchronizer to trigger PyO3 destructors
- **Inconsistent client cleanup across services**: `connect_relay()` error paths and `is_nostr_relay()` used `disconnect()` (closes WebSocket only) instead of `shutdown()` (releases entire Rust Client). NIP-66 RTT `_cleanup()` had the same issue. All now use `shutdown()` when the client is being discarded

## [6.6.0] - 2026-03-31

### Added

- **HASH partitioning on `event` and `event_relay`**: 16 partitions each, keyed by `id` and `event_id` respectively. Same hash key enables partition-wise joins. Configurable via Jinja2 template variable (`partitions`, default 16). Zero changes to CRUD functions, indexes, matviews, or Python code
- **LZ4 compression**: `event.content`, `event.tags` (bigbrotr), and `metadata.data` (both deployments) use LZ4 instead of the default `pglz` for faster compression at high insert rates
- **Partition monitoring**: new `partition_distribution` Prometheus metric exposing per-partition row estimates; two Grafana dashboard panels showing distribution as percentage
- **7 integration tests**: partition structure, distribution across partitions, event/event_relay co-location

### Fixed

- **Missing matview ownership grants**: `events_replaceable_latest` and `events_addressable_latest` were not granted to the `refresher` role in `98_grants.sh`, preventing `REFRESH MATERIALIZED VIEW CONCURRENTLY` on fresh deployments
- **Table sizes metric showed 0 for partitioned tables**: `pg_total_relation_size` on a partitioned parent returns 0; now aggregates child partition sizes
- **LilBrotr verify script**: corrected matview count (11 to 13) and refresh function count (12 to 14)

### Changed

- **postgresql.conf**: `enable_partitionwise_join` and `enable_partitionwise_aggregate` enabled (both deployments)
- **Monitoring queries**: `table_sizes` excludes individual partitions and aggregates their sizes under the parent; `row_estimates` includes partitioned parent tables (`relkind = 'p'`)
- **Autovacuum tuning**: aggressive settings (`scale_factor = 0.02`, `threshold = 10000`) applied per leaf partition on `event_relay` (cannot be set on partitioned parent)

## [6.5.5] - 2026-03-31

### Fixed

- **Hostname validation too strict**: underscores in DNS labels now accepted per RFC 2181 §11, fixing rejection of real-world relay hostnames (e.g. Coracle room subdomains like `https_2140_wtf.spaces.coracle.social`)
- **Tor subdomains rejected**: `.onion` validation now supports virtual subdomains (RFC 7686 §2), validating the onion hash on the rightmost label and standard hostname rules on subdomain labels (e.g. `relay.hash.onion`)
- **IDN hostnames rejected**: internationalized domain names are now converted to punycode via stdlib IDNA 2003 codec before RFC 3986 parsing (e.g. `wss://cafe.com` -> `wss://xn--caf-dma.com`)
- **Trailing-dot hostnames rejected**: FQDN root labels are now stripped during normalization (e.g. `relay.com.` -> `relay.com`)
- **IPv6 not normalized**: equivalent IPv6 representations now produce the same canonical URL via RFC 5952 compression
- **Port range not validated**: ports outside 1-65535 are now rejected

### Changed

- **PostgreSQL upgraded**: `16-alpine` → `18-alpine`
- **Tor proxy upgraded**: `osminogin/tor-simple` `0.4.8.10` → `0.4.8.16` (fixes SIGSEGV crashes)
- **postgres-exporter upgraded**: `v0.16.0` → `v0.17.0` (fixes goroutine panic during metric collection)
- **Docker image pinning**: all 7 infrastructure images pinned with SHA256 digests for supply chain security
- **Relay hostname validation**: extracted `_is_valid_hostname` and `_is_valid_overlay_hostname` with strict per-network hash validation (Tor v3/v2 base32, I2P b32, Loki), replacing the previous permissive label-only check

## [6.5.4] - 2026-03-28

### Added

- **Configurable `max_event_size`**: synchronizer can now drop events exceeding a configurable JSON size limit via `processing.max_event_size` (default: `None`, no limit). Applied before domain model construction in `stream_events()`

### Fixed

- **Synchronizer crash on oversized tag values**: events with tag values exceeding 2048 characters caused `index row size exceeds maximum for index "idx_event_tagvalues"`. Now rejected at `Event` construction, consistent with `Relay` URL length validation

## [6.5.3] - 2026-03-28

### Added

- **Geohash in announcement**: Kind 10166 now supports an optional `g` tag declaring the monitor's geographic location (NIP-52 geohash). Configurable via `AnnouncementConfig.geohash`, defaults to `None` (omitted)

### Fixed

- **Missing timeout tags for Geo/Net in announcement**: Kind 10166 did not declare `["timeout", "geo", ...]` and `["timeout", "net", ...]` despite both checks now accepting timeout parameters. Refactored tag generation to a data-driven loop

## [6.5.2] - 2026-03-28

### Fixed

- **Announcement included LOCAL/UNKNOWN networks**: `publish_announcement()` iterated over all `NetworkType` enum members; LOCAL and UNKNOWN fell back to clearnet config, causing the Kind 10166 event to declare monitoring of invalid networks. Now uses `get_enabled_networks()` which only returns configured networks (clearnet, tor, i2p, loki)
- **Profile publishing disabled by default**: `ProfileConfig.enabled` was `False` while announcement and relay_list were `True`. All three publishing features now default to enabled

## [6.5.1] - 2026-03-28

Monitor hardening, announcement frequency fix, and dependency cleanup.

### Fixed

- **NIP-66 Geo/Net timeout protection**: `Nip66GeoMetadata.execute()` and `Nip66NetMetadata.execute()` had no timeout — `resolve_host()` and `asyncio.to_thread()` could hang indefinitely. Now wrapped in `asyncio.wait_for()` with `DEFAULT_TIMEOUT` (10s) fallback, and monitor passes network timeout to both checks (#402)
- **Announcement frequency tag**: Kind 10166 `["frequency"]` tag was using the cycle interval (`BaseServiceConfig.interval`) instead of the per-relay monitoring frequency (`DiscoveryConfig.interval`)
- **`build_relay_list_event` missing from `__all__`**: Kind 10002 builder was defined and used but not exported in `event_builders.__all__`

### Changed

- **`cryptography` floor raised to >=46.0.6**: prevents installation of 46.0.5 which has GHSA-m959-cc7f-wv43
- **`nostr-sdk` floor raised to >=0.44.0**: aligns minimum with actual deployed version
- **Removed stale mypy ignores**: `fastapi` and `starlette` no longer need `ignore_missing_imports` (native stubs available)

## [6.5.0] - 2026-03-27

Relay URL validation hardening, `parse_relay_url` factory, and dependency updates.

### Added

- **`parse_relay_url()` factory function**: centralizes URL-to-Relay conversion with logging for invalid URLs, wired into finder, monitor, DVM, and common utils (#400)

### Changed

- **Relay URL sanitization separated from construction**: path validation (character whitelist, segment structure, length limit) extracted into `sanitize_relay_path()` in `utils/parsing.py`, keeping `Relay.__post_init__` focused on structural validation
- **URL length limit enforced**: relay URLs exceeding 2048 characters are rejected at construction, preventing PostgreSQL B-tree index overflow (`index row requires N bytes, maximum size is 8191`)
- **CI actions pinned to commit SHAs**: `actions/checkout`, `actions/setup-python`, `actions/upload-pages-artifact`, `actions/deploy-pages`, `actions/upload-artifact`, and `github/codeql-action` now use full SHA pins instead of version tags
- **`requests` upgraded to 2.33.0**: security update; unfixed Pygments CVE added to `tool.pip-audit.ignore` with tracking link

### Fixed

- **Synchronizer crash on oversized relay URLs**: URLs with long percent-encoded paths (e.g. 29KB) caused `index row requires 29656 bytes, maximum size is 8191` after 5 consecutive failures, stopping the service (#400)

## [6.4.0] - 2026-03-20

Replaceable/addressable event matviews, synchronizer idle timeout fix, and configuration updates.

### Added

- **`events_replaceable_latest` and `events_addressable_latest` materialized views**: track latest replaceable (Kind 0, 3, 10000–19999) and addressable (Kind 30000–39999) events per author, enabling efficient lookups for profile metadata, contact lists, and parameterized replaceable content (#395)

### Changed

- **Default concurrency limits updated**: tuned `max_tasks` defaults across network configurations (#394)
- **Monitor discovery interval**: increased from 1 hour to 4 hours to better match relay update cadence

### Fixed

- **Synchronizer idle timeout**: replaced per-relay deadline with progress-based idle timeout — relays that continuously receive events no longer get prematurely disconnected (#396)

## [6.3.0] - 2026-03-16

NIP-65 relay list publishing, default relay updates, Grafana improvements, and test cleanup.

### Added

- **Kind 10002 relay list publishing** (NIP-65): Monitor publishes its relay list so clients know where to find its events. Configurable via `relay_list` config with interval and relay override (#386)
- **`build_relay_list_event()`**: event builder for Kind 10002 with `["r", url, "write"]` tags
- **`relay.primal.net`**: added to default publishing relays for both Monitor and DVM

### Changed

- **DVM default relays**: `relay.nostr.band` replaced with `relay.mostr.pub`
- **Grafana "Event Scan" card renamed to "Scanned"**: shows both rows and relays scanned
- **Grafana "Total Candidates" card removed**: Database Size restored to full width in overview
- **Grafana "Total Candidates" renamed in Validator section**: clarifies candidate vs relay counts
- **Grafana "Total Relays" renamed in Monitor section**: clarifies monitored relay count

### Fixed

- **RuntimeWarning in cli test**: replaced async `main()` with sync lambda to prevent orphan coroutine when `asyncio.run` is mocked

## [6.2.0] - 2026-03-16

Metrics overhaul, IPv4 DNS fix for Docker containers, and deployment improvements. Service gauges refactored with new `inc_gauge`/`dec_gauge` API, finder and synchronizer metrics redesigned for better observability, and Grafana dashboards updated with new panels.

### Added

- **`inc_gauge()` and `dec_gauge()` methods on BaseService**: native Prometheus gauge increment/decrement without intermediate variables
- **`relays_connected` gauge in synchronizer**: tracks relays that connected successfully via WebSocket, regardless of events (later unified into `relays_seen`)
- **`candidates_found_from_api` and `candidates_found_from_events` gauges in finder**: split candidate tracking by discovery source
- **Total Candidates card in Grafana overview**: shows validator candidate queue size from postgres-exporter
- **Relays/s in Processing Rate panels**: both finder and synchronizer now show relay processing rate alongside rows/events rate
- **`gai.conf` for IPv4 DNS precedence**: mounted in all 8 service containers to force IPv4 over IPv6 (glibc RFC 6724)
- **`backup.sh` in deployment folders**: included in both bigbrotr and lilbrotr deployments with per-deployment database names
- **`data/` and `dumps/` directories**: with `.gitkeep` for deployment folder completeness

### Changed

- **Synchronizer `relays_seen` gauge**: now incremented in worker `finally` block after WebSocket session completes, counting all visited relays (not just those with events)
- **Finder `relays_seen` gauge**: moved to worker `finally` block, counts relays scanned during event discovery
- **Finder dedup removed**: `find_from_api` no longer deduplicates in-memory; `ON CONFLICT DO NOTHING` in `insert_relays_as_candidates` handles it
- **Finder `total_relays` gauge removed**: redundant with `relays_seen`
- **Validator "Total" card renamed to "Total Candidates"** in Grafana
- **Monitor "Total" card renamed to "Total Relays"** in Grafana
- **Services use `inc_gauge` instead of `set_gauge` with counter variables**: synchronizer, finder, validator, and monitor refactored for cleaner metric tracking
- **Default publishing relays**: replaced `relay.nostr.band` with `relay.mostr.pub`
- **Self-hosting guide rewritten**: download deployment folder instead of cloning repo, Docker Hub images, per-deployment storage layout, multi-deployment support (Appendix C)

### Fixed

- **IPv4 DNS precedence in containers**: full `gai.conf` with labels + precedence table for glibc compatibility; single-line version was silently ignored
- **`backup.sh` PGPASSWORD**: use `docker exec -e` to inject password into container instead of shell-level env var

## [6.1.0] - 2026-03-16

Performance optimizations, infrastructure fixes, and CI/CD improvements. Materialized views optimized for significantly faster refresh, Docker networking fixed for IPv6-less hosts, and image publishing migrated from GHCR to Docker Hub.

### Changed

- **Materialized view `relay_stats` optimized**: replaced 2 LATERAL subqueries with CTE ROW_NUMBER() for RTT averages and JOIN on `relay_metadata_latest` for NIP-11 info; `COUNT(DISTINCT)` replaced with `COUNT(*)`; `LEFT JOIN` replaced with `INNER JOIN` on event table (~4-8x speedup) (#378)
- **Materialized view `network_stats` optimized**: relay count computed in separate CTE on relay table; events deduplicated per network before joining event table to avoid processing duplicates (~1.5-3x speedup) (#378)
- **Materialized view `event_daily_counts` optimized**: replaced `to_timestamp()` + timezone conversion with integer arithmetic for faster date grouping (~1.1-1.3x speedup) (#378)
- **Docker image publishing migrated from GHCR to Docker Hub**: GHCR packages defaulted to private under org settings; Docker Hub provides public images with anonymous pull access (#382)
- **Dependabot PRs target `develop`**: all 3 ecosystems (uv, docker, github-actions) now create PRs against `develop` instead of `main` (#381)
- **Streaming verify logs downgraded**: `inconsistent_relay_empty_verify` and `inconsistent_relay_verify_max` changed from `warning` to `debug` — expected during normal operation (#379)

### Fixed

- **Docker IPv6 networking**: disabled IPv6 on Docker bridge networks; containers preferred IPv6 (RFC 6724) but hosts without IPv6 connectivity failed with "Network is unreachable" for relays behind dual-stack CDNs (#380)
- **`event_daily_counts` date arithmetic**: added explicit `::INTEGER` cast for `BIGINT / 86400` — PostgreSQL has no `DATE + BIGINT` operator (#381)

### Security

- **Docker base image hardened**: added `apt-get upgrade` in both Dockerfile stages to patch OS-level vulnerabilities (CVE-2026-0861, glibc heap corruption)

### Docs

- **Self-hosting guide**: added `docs/guides/self-hosting.md` (#379)

### Dependencies

- ruff 0.15.5 → 0.15.6 (#381)
- mkdocs-material 9.7.4 → 9.7.5 (#381)
- astral-sh/setup-uv v7.3.1 → v7.5.0, docker/setup-buildx-action v3.12.0 → v4.0.0, docker/build-push-action v6.19.2 → v7.0.0, docker/setup-qemu-action v3.7.0 → v4.0.0, docker/login-action v3.7.0 → v4.0.0, docker/metadata-action v5.10.0 → v6.0.0, aquasecurity/trivy-action v0.34.1 → v0.35.0, github/codeql-action v4.32.4 → v4.32.6, actions/download-artifact v8.0.0 → v8.0.1 (#381)

## [6.0.0] - 2026-03-15

Service architecture refinements, database index overhaul, and monitoring stack rewrite. Finder service fully restructured with cursor-based pagination, database indexes redesigned for actual query patterns, and Grafana dashboards rewritten from scratch.

### Changed

- **Finder service restructured**: aligned with synchronizer patterns — cursor-based event scanning with `(seen_at, event_id)` composite pagination, streaming relay extraction, and per-relay deadline enforcement (#366, #367)
- **Finder configs tightened**: `scan_size` replaces `batch_size` for DB queries, `max_relay_time` raised to 900s, `max_duration` to 7200s, API source `expression` field no longer has a default (#366, #367)
- **Monitor simplified**: removed `count_relays_to_monitor` query — service now fetches all due relays once and slices in-memory; `_monitoring_worker` renamed to `_monitor_worker` (#372)
- **Refresher interval**: default changed from 1 hour to 24 hours; per-view duration gauge and `time.monotonic()` timing added; counter metrics removed in favor of gauges (#371)
- **Synchronizer configs**: `batch_size` minimum raised from 1 to 100, maximum lowered from 100k to 10k; `limit` minimum raised from 1 to 10; `_sync_worker` renamed to `_synchronize_worker` (#366)
- **Checkpoint defaults**: `Checkpoint.timestamp` defaults to 0; `CandidateCheckpoint` is now `kw_only`; `Cursor` fields default to sentinel values instead of None (#366)
- **Batched operations**: Synchronizer and Monitor queries use shared `batched_insert` and `upsert_service_states` helpers from `services/common/queries` (#366)
- **Grafana dashboards**: complete rewrite for both bigbrotr and lilbrotr deployments with aligned service metrics and panel layout (#372)
- **Postgres-exporter queries**: rewritten to match new metric names and dashboard panels (#372)

### Fixed

- **Database indexes redesigned**: replaced 6 redundant or misaligned indexes with 4 optimized composite indexes — `idx_event_created_at_id` (DESC for timeline), `idx_event_relay_relay_url_seen_at_event_id` (3-column covering index for cursor pagination), removed standalone `idx_event_kind`, `idx_event_relay_relay_url`, `idx_service_state_service_name`, `idx_service_state_service_name_state_type`; fixed candidate network partial index filter to use `state_type = 'checkpoint'` (#370)
- **Materialized view indexes**: added `idx_relay_metadata_latest_relay_url` for relay-level lookups; added `idx_kind_counts_by_relay_relay_url` and `idx_pubkey_counts_by_relay_relay_url`; removed redundant `idx_kind_counts_by_relay_kind` (#370)

### Docs

- **README badges**: improved layout and styling (#374)
- **Documentation drift**: comprehensive fix across configuration, services, architecture, and database pages (#366, #369)

## [5.10.0] - 2026-03-13

API ergonomics and service architecture refinements: simplified public API for library consumers, unified async generator workers, and NIP protocol enhancements.

### Added

- **NIP-11 `attributes` field**: relay self-describing PascalCase attributes, emitted as `W` tags in Kind 30166 discovery events (#361)
- **NIP-66 discovery tags**: `add_dns_tags`, `add_http_tags`, `add_attributes_tags`, `add_requirement_and_type_tags` for richer Kind 30166 events (#361)
- **NIP-32 label tags**: geo (`ISO-3166-1`, `nip66.label.city`, `IANA-tz`) and net (`IANA-asn`, `IANA-asnOrg`) labels in discovery events (#361)

### Changed

- **`build_relay_discovery` simplified**: from 11 primitive parameters to 3 domain objects (`Relay`, `Nip11`, `Nip66`) (#363)
- **`Nip66Dependencies` defaults**: `keys`, `event_builder`, and `read_filter` auto-populated — RTT tests work out-of-the-box (#363)
- **Async generator workers**: Finder, Validator, Monitor, Synchronizer unified with `AsyncGenerator` workers and streaming flush (#362)
- **Semaphore at worker level**: finer-grained concurrency control (#362)
- **Synchronizer configs**: inlined sync worker, simplified configuration (#362)
- **`extract_relays_from_response`**: removed default parameter, expression always explicit (#364)
- **`metadata.type` column**: renamed from `metadata_type` (#360)

### Fixed

- **`relay_metadata.metadata_type` column**: restored correct column name in SQL template (#360)

## [5.9.0] - 2026-03-09

Comprehensive service review, test rewrite, and documentation overhaul. Services restructured for consistency, test suite rewritten for comprehensive coverage, and all documentation audited against current codebase.

### Added

- **`allow_insecure` config**: Validator, Synchronizer, and Dvm services now support `allow_insecure` option for connecting to relays with invalid TLS certificates (#353, #357)
- **CORS and request timeout**: Api service gains configurable CORS middleware and per-request timeout (#357)
- **DVM utilities module**: Extracted DVM utility functions into dedicated `dvm/utils.py` for clearer separation of concerns (#357)

### Fixed

- **`service_state_upsert` return value**: Stored procedure now returns affected row count instead of VOID, enabling callers to verify upsert success (#353)
- **Integration test failures**: Corrected fixture setup and teardown for reliable test execution (#356)

### Changed

- **Service-wide refactoring**: DVM service restructured with extracted utilities; Monitor configs, queries, and utils cleaned up; Validator metrics simplified to three gauges; delete-count queries standardized to CTE + fetchval pattern (#353, #357)
- **Client lifecycle**: `PublishClients` renamed to `Clients` with simplified publish methods; client lifecycle moved to protocol module; dead protocol helpers removed (#353)
- **Monitor alignment**: `monitor()` method aligned to `validate()` pagination pattern; helpers extracted and inlined for clarity (#353)
- **Synchronizer simplification**: Config simplified, streaming module renamed, sync algorithm extracted to utils (#352)
- **Candidate queries**: Insertion queries moved to common module for reuse across services (#352)
- **Pydantic config models**: Added Field descriptions across all config models (#353)
- **Integration fixtures**: Optimized with TRUNCATE instead of DROP/CREATE for faster test cycles (#356)

### Removed

- **Redundant code**: `or 0` guard on `delete_promoted_candidates` (already returns int), dead protocol helpers in Clients class (#353)

### Tests

- **Complete test rewrite**: Unit tests (~2,739) and integration tests (~216) rewritten for comprehensive coverage with consistent patterns (#355, #356)
- **Integration consolidation**: BigBrotr-specific integration tests merged into base test suite (#356)

### Docs

- **PROJECT_SPECIFICATION.md**: Complete rewrite (984→1464 lines) based on deep codebase audit covering all 16 sections (#358)
- **README.md**: Full refresh with accurate architecture diagram, service table, and project data (#358)
- **Documentation site**: Fixed broken Material Design icons, Mermaid diagram syntax, CSS styling; corrected inaccuracies across user guide, how-to, and development docs (#358)
- **Unified descriptions**: Project description aligned across `pyproject.toml`, `__init__.py`, `mkdocs.yml`, `Dockerfile`, and landing page (#358)
- **Stale cross-references**: Fixed broken docstring references after query module relocation (#352)

## [5.8.0] - 2026-03-06

Service quality and correctness release: concurrent processing extracted into shared mixin, error handling normalized across all services, and two production bugs fixed.

### Added

- **`ConcurrentStreamMixin`**: shared mixin extracted from Finder/Validator/Monitor/Synchronizer for concurrent item processing via TaskGroup + Queue streaming (#349)

### Fixed

- **Reason validation**: `BaseLogs` and `Nip66RttMultiPhaseLogs` used truthiness check (`not self.reason`) instead of `self.reason is None`, rejecting empty string reasons with `ValidationError`. Fixed in 4 locations (#350)
- **NULL tagvalue handling**: `extract_relays_from_tagvalues()` crashed on `None` elements in PostgreSQL `text[]` arrays (`None.partition(":")` → `AttributeError`). Added type guard (#350)

### Changed

- Worker exception boundary in Validator upgraded from `warning` to `error` log level, with `error_type` diagnostic field (#350)
- Boundary comments added to all worker `except Exception` blocks (Finder, Monitor, Synchronizer) documenting TaskGroup protection (#350)
- Module-level log messages normalized to `snake_case_event: context` format across common/utils, finder/queries, validator/queries (#350)

### Removed

- Dead `validator/utils.py` module (empty, no imports) (#350)
- Unnecessary `.copy()` in Synchronizer cursor flush (already under lock) (#350)

## [5.7.0] - 2026-03-03

Major service refactoring release: all 8 services restructured with dedicated query modules, typed domain objects, and cleanup lifecycle. Synchronizer gains forward-progression binary split algorithm for complete event synchronization.

### DEPLOYMENT CHANGES

- **ServiceState `updated_at` column removed**: The `service_state` table no longer has an `updated_at` column. SQL init scripts regenerated accordingly. Existing deployments should drop the column if present
- **ServiceState type consolidation**: `CANDIDATE` state type replaced with `CHECKPOINT`; `MONITORING` and `PUBLICATION` types merged back into `CHECKPOINT`. Existing rows must be migrated
- **API route prefix configurable**: Api service now supports `route_prefix` in config YAML (default `/api/v1`)

### Added

- **Forward-progression binary split sync algorithm** (#346): `iter_relay_events()` async generator in Synchronizer guarantees all events are fetched from a relay by splitting time windows when the response hits the limit. Events are yielded in ascending time order for cursor-based resumption
- **`cleanup()` lifecycle hook**: Abstract method on `BaseService` with implementations across all 8 services for stale state removal (orphaned cursors, exhausted candidates, obsolete checkpoints)
- **`cleanup_stale()` shared query**: Common query for service state cleanup by composite key
- **Grafana dashboards**: Dedicated panels (4 stat + 1 timeseries) for Finder, Monitor, Synchronizer services
- **Postgres-exporter queries**: `relay_metadata` and `event_relay` approximate row counts

### Changed

- **Service-specific query modules**: Extracted queries from `common/queries.py` into per-service `queries.py` modules (finder, monitor, synchronizer, validator), decoupling query functions from service instances (#345)
- **Finder restructured**: `find_from_events()` rewritten as async generator with per-relay streaming metrics; API cooldown moved from per-source interval to shared `api.cooldown` config; default `batch_size` lowered from 1000 to 100
- **Monitor simplified**: Inlined `_fetch_nip11_info()` closure, merged `check_chunks()`/`_check_chunk()` into single method, removed redundant gauge updates
- **Synchronizer restructured**: Client lifecycle extracted into `_fetch_and_insert()` method consuming the `iter_relay_events()` generator; cursor tracking returns value to caller for testability; removed `SyncContext` in favor of direct parameters
- **Seeder simplified**: Publicized `batched_insert`, consolidated test structure
- **Validator queries**: Use `batched_insert` pattern, consolidate test file
- **`BaseService.run_forever()` lifecycle logging**: Centralized start/stop/error logging in base class
- **Checkpoint/Cursor types**: Added `ApiCheckpoint`, `EventRelayCursor` typed domain objects replacing raw dicts
- **`parse_relay_url` renamed to `parse_relay`**: Added `parse_relay_row` for database row parsing

### Fixed

- **SQL template drift**: Removed stale `updated_at` column and parameter from SQL generation templates
- **Docstring cross-references**: Updated 6 broken references for query functions moved to service-specific modules
- **Ruff lint errors**: Fixed TC003, PIE804, RUF003, ERA001 across test files
- **Monitor `_check_chunk`**: Properly re-raise `BaseException` (including `CancelledError`)
- **DVM `default_page_size`**: Added missing config field and fixed FFI comment

### Tests

- **Consolidated test structure**: All service tests moved from subdirectories (`tests/unit/services/<service>/`) to flat files (`tests/unit/services/test_<service>.py`) with configs, queries, utils, and service tests in a single file per service (#346)
- **`TestIterRelayEvents`**: 9 tests covering empty relay, single batch, binary split, nested splits, degenerate single-second window, exception propagation, partial completion on error
- **Updated service-level tests**: Synchronizer tests mock `_fetch_and_insert` instead of old `sync_relay_events`

### Docs

- **README**: Removed Resources column from Container Stack table, updated NIP references
- **Docstrings**: Updated cross-references for cleanup lifecycle, service review, and moved query functions
- **`DEFAULT_VIEWS` reference**: Replaced unresolvable mkdocs cross-reference with code literal

## [5.6.0] - 2026-03-01

Observability, code quality, and deployment alignment release.

### DEPLOYMENT CHANGES

- **Renamed `PRIVATE_KEY` to `NOSTR_PRIVATE_KEY`** across all services, Docker Compose files, and `.env.example` templates. Update your `.env` files accordingly (#337)
- **Rewrote `.env.example`** for both bigbrotr and lilbrotr with cleaner format and sections
- **Aligned lilbrotr deployment** with bigbrotr: unified SQL init scripts, config structure, docker-compose topology, and PGBouncer setup (#337)

### Added

- Prometheus counters for all 8 services: relay-level counters (Finder), total_promoted (Validator), check/metadata/publishing counters (Monitor), relay sync/fail counters (Synchronizer), view counters and cycle duration gauge (Refresher), total_jobs_received (Dvm) (#331)
- Grafana dashboard rows for Refresher metrics and candidate queue gauge (#334)

### Fixed

- Resolve ambiguous alias in `filter_new_relays` query (#333)

### Changed

- Extract `CatalogAccessMixin` from Api and Dvm services to share catalog initialization logic (#335)
- Extract `ApiConfig` and `DvmConfig` into dedicated config modules (#335)
- Move `_emit_progress_gauges` into `ChunkProgressMixin` (#335)

### Tests

- Restructure all service tests into uniform 1:1 directory layout (api, dvm, refresher, seeder, validator, finder, synchronizer) (#332)
- Add tests for common types and utils modules (#332)
- Add deterministic time patching to publishing tests, fix mock targets (#332)
- Add Prometheus counter tests for all services (#331)

### Docs

- Comprehensive documentation update for all eight services (#336)
- Add CatalogAccessMixin and catalog.py to architecture docs (#336)
- Clean up ASCII diagrams in README and PROJECT_SPECIFICATION (#338)
- Fix mermaid connection pooling chart in architecture docs (#338)

## [5.5.0] - 2026-03-01

Hardening release: security fixes, configuration constraints, code quality improvements, and deployment changes across all services.

### DEPLOYMENT CHANGES

- **New `refresher` database role** with least-privilege access (SELECT + matview ownership only), replacing the writer role previously used by the Refresher service. Requires new `DB_REFRESHER_PASSWORD` env variable and updated PGBouncer/Docker Compose config (#323)
- **Default-closed table access**: tables now default to `enabled: false` in `TableConfig` — only tables explicitly listed with `enabled: true` in service YAML configs are served by API and DVM. Existing deployments must add explicit `enabled: true` entries for each exposed table (#327)

### Fixed

- Fix 12 JSONB path errors in materialized views (`relay_stats`, `relay_software_counts`, `supported_nip_counts`) that referenced top-level keys instead of the nested `data` envelope, producing NULL columns (#323)
- Prevent stack-trace exposure in API error responses: `ValueError` exceptions in `get_row` handler now return generic message instead of `str(e)` (#329)

### Changed

- **Config constraints hardened** across all 8 services: `min_length=1` on non-empty strings, `ge=0.1` on timeouts, cross-field validators (`max_delay >= initial_delay`, `connect_timeout <= timeout`), relay URL validation on DVM, `le=100` upper bound on `max_consecutive_failures` (#319)
- **Fixed-schedule cycling**: `run_forever()` now starts the next cycle `interval` seconds after the previous started (subtracting elapsed time), preventing drift accumulation (#319)
- **Core defaults tuned**: pool `min_size=1` / `max_size=5` for lighter footprint; refresher interval raised to 3600s (#319)
- Unified `TablePolicy` and `DvmTablePolicy` into single `TableConfig` model with `price` support for both services (#327)
- Regex validation on refresher view names (`^[a-z_][a-z0-9_]*$`) to prevent SQL injection (#328)
- Upper bounds on monitor config fields: publishing timeout `le=300`, discovery/announcement/profile intervals `le=604800` (#328)
- Explicit column list in `scan_event` query replacing `SELECT *` (#328)
- Aligned `insert_metadata` to `_transpose_to_columns` pattern used by all other insert methods (#328)
- Added `asyncio.wait_for` timeout on DNS `asyncio.to_thread` call (#328)
- Replaced all `contextlib.suppress(Exception)` with `try/except` + log DEBUG across cleanup paths (dvm, protocol, transport, rtt) (#328)
- Standardised `logs["reason"]` assignment and log output across NIP-66 modules (ssl, http, geo, dns) (#328)
- Added `CatalogError.client_message` attribute for controlled access to client-safe error strings (#329)

## [5.4.0] - 2026-02-28

Minor release: two new services (Api and Dvm) bring read-only HTTP and Nostr interfaces to the database, backed by a shared schema-driven Catalog query builder. Major refactoring of service queries and state types consolidates raw-dict handling into typed domain objects.

### DEPLOYMENT CHANGES

- **New services**: Api (port 8080) and Dvm containers added to both `bigbrotr` and `lilbrotr` docker-compose stacks. Requires updated `.env` with `NOSTR_NSEC` for Dvm
- **New dependencies**: `fastapi>=0.115`, `uvicorn>=0.34`, `nostr-sdk>=0.39` added to `pyproject.toml`
- **Service configs**: New `config/services/api.yaml` and `config/services/dvm.yaml` in both deployments
- **Prometheus**: Scrape targets added for Api (`:8090/metrics`) and Dvm (`:8091/metrics`)
- **State type migration**: `CHECKPOINT` state type split into `MONITORING` and `PUBLICATION`. Existing `service_state` rows with `state_type = 'CHECKPOINT'` must be migrated or deleted before deploying

### Added

- **Api REST service** (#315): FastAPI-based read-only HTTP server with auto-generated paginated endpoints for all tables, views, and materialized views. Per-table access control via `TableConfig`, configurable CORS, request statistics logging, and Prometheus metrics
- **Dvm NIP-90 service** (#315): Data Vending Machine listening for kind 5050 job requests on configured Nostr relays, executing read-only queries via the Catalog, and publishing kind 6050 result events. Per-table pricing via `TableConfig` with bid/payment-required mechanism
- **Catalog query builder** (#315): Schema introspection engine discovering tables, views, and materialized views at runtime. Builds parameterized queries with whitelist-by-construction validation. Shared by Api and Dvm services
- **`CatalogError`** (#315): Client-safe exception preventing internal database error details from leaking to API/DVM consumers
- **`Candidate` dataclass** (#314): Typed domain object in `services/common/types.py` replacing raw dicts in the validation pipeline
- **`EventRelayCursor` and `EventCursor`** (#314): Cursor dataclasses with invariant enforcement for deterministic pagination in Finder and Synchronizer
- **`scan_event_relay` and `scan_event` queries** (#314): Cursor-typed query functions replacing `fetch_event_tagvalues`
- **Batch-safe query wrappers** (#314): `insert_relay_metadata`, `insert_event_relays`, `upsert_service_states` with automatic chunk splitting

### Refactored

- **Service state types** (#314): Split `CHECKPOINT` into `MONITORING` (health check markers) and `PUBLICATION` (event publish markers) for explicit, independently queryable semantics
- **Query functions return domain objects** (#314): `fetch_all_relays`, `fetch_candidates`, `fetch_relays_to_monitor` now return typed objects (`Relay`, `Candidate`, `ServiceState`) instead of raw dicts
- **Removed `from_db_params`** (#314): Eliminated from all 6 models (Relay, Event, Metadata, ServiceState, EventRelay, RelayMetadata). Consolidated `models_from_db_params` + `models_from_dict` into `safe_parse` utility
- **Centralized batch splitting** (#314): Services pass arbitrarily large lists to query wrappers; chunk management moved into `queries.py` via `_batched_insert` helper
- **Finder cursor** (#314): Replaced single-field `seen_at` cursor with composite `(seen_at, event_id)` for deterministic pagination when multiple rows share the same timestamp
- **Query renames** (#314): `get_all_relays` -> `fetch_all_relays`, `filter_new_relay_urls` -> `filter_new_relays`, `fetch_candidate_chunk` -> `fetch_candidates`, `insert_candidates` -> `insert_relays_as_candidates`, `cleanup_stale_state` -> `cleanup_service_state`
- **`get_enabled_networks()`** (#314): Returns `NetworkType` directly, eliminating manual casts at 4 call sites

### Fixed

- **Api `get_row` error handling**: Catch `CatalogError` alongside `ValueError` in the single-row lookup handler. Previously, invalid primary key values returned 500 instead of 400
- **Catalog error sanitization** (#315): asyncpg error messages sanitized at the Catalog layer; `CatalogError` wraps internal exceptions to prevent leaking database internals
- **`promote_candidates` docstring** (#315): Corrected parameter documentation and added error logging
- **`_publish_if_due` dead timeout** (#315): Removed unused default timeout parameter
- **Synchronizer cursor validation** (#315): `NostrSdkError` caught and cursor parsing hardened against corrupt data
- **Brotr facade access** (#315): Replaced direct pool access with facade method
- **LilBrotr postgres-exporter** (#315): Added missing `LABEL` definitions
- **Monitor retry YAML key** (#315): Renamed to match Pydantic field name
- **`scan_event_relay` columns** (#315): Explicit column enumeration replacing `SELECT *`
- **`conftest` mock fixture**: Corrected stale `procedure` key to `cleanup` in `mock_brotr` TimeoutsConfig
- **Seeder error handling** (#314): Added try/except around DB calls that previously had no graceful error handling
- **Synchronizer silent failures** (#314): Replaced `contextlib.suppress(Exception)` with explicit try/except that logs at DEBUG level
- **Monitor log field** (#314): Renamed `attempts` -> `total_attempts` for consistency with retry-related log conventions
- **`delete_orphan_cursors`** (#314): Changed from `NOT IN` to `NOT EXISTS` for better PostgreSQL performance with large result sets

### Documentation

- **8-service architecture**: Updated all service counts (6 -> 8), architecture diagrams, service tables, and interaction maps across README, PROJECT_SPECIFICATION, CLAUDE.md, guides, and MkDocs
- **Source docstrings**: Fixed cross-references (`utils.transport` -> `utils.protocol`), exception types (`ValueError` -> `CatalogError`), field references (`log_level` -> `metrics`), consumer lists, and column names across 11 source files
- **Deployment configs**: LilBrotr composite index upgrade, missing metrics port variables, singular table names in README, proxy container clarification, postgres-exporter network enum cleanup, bigbrotr role verification in `99_verify.sql`
- **Removed `aiomultiprocess`**: Dead runtime dependency never imported in source code

---

## [5.3.1] - 2026-02-26

Patch release: one bug fix and comprehensive documentation overhaul. Architecture terminology corrected across all documentation, README rewritten, project specification added.

### Fixed

- **`_transpose_to_columns`** (#311): Use `strict=True` in `zip()` to catch row length mismatches that bypass validation. Closes #242

### Documentation

- **Architecture terminology** (#312): Replaced "pipeline" terminology with "independent services" across all documentation, source docstrings, and deployment configs. Renamed `pipeline.md` to `services.md`. Fixed service count (5 -> 6), architecture tiers (5 -> 4), test counts, query function count (14 -> 15), Prometheus ports, alert rules (4 -> 6), and DAG diagram edges
- **README**: Rewritten with comprehensive project overview reflecting current architecture
- **PROJECT_SPECIFICATION.md**: Added full system specification with database schema, service descriptions, deployment variants, and architecture diagrams
- **Removed stale REVIEW.md**: Cleanup of previous review artifact

---

## [5.3.0] - 2026-02-25

Comprehensive codebase hardening: 46 commits across 44 PRs. Finder refactored from kind-specific event parsing to kind-agnostic tagvalues scanning with JMESPath-based configurable API extraction. Extensive bug fixes across all layers (models, core, NIPs, services, deployments), dead code removal, and improved error handling.

### DEPLOYMENT CHANGES

- **SQL template sync**: LilBrotr deployment SQL files updated for batched orphan_event_delete, network_stats direct-join rewrite, supported_nip_counts cast guard, Synchronizer indexes, and corrected file headers. Requires fresh `initdb` or manual execution of updated SQL files (04, 05, 06, 07, 08)
- **Grafana depends_on**: Added `service_healthy` condition to Grafana container's Prometheus dependency

### Added

- **JMESPath API extraction** (#309): `ApiSourceConfig.jmespath` field enables configurable relay URL extraction from diverse JSON API response formats (`[*]`, `data.relays`, `[*].url`, `keys(@)`)
- **`jmespath` dependency**: `jmespath>=1.0.0` (runtime) and `types-jmespath>=1.0.0` (dev type stubs)
- **`cleanup_stale_state` query**: Removes state records for relays no longer in the database, used by Finder, Synchronizer, and Monitor (#309)
- **Finder metrics**: `relays_failed` gauge and `total_api_relays_found` counter (#309)
- **Synchronizer network filtering**: `fetch_relays()` now filters by enabled networks, avoiding unnecessary relay loading (#309)
- **NIP-11 shared session**: `Nip11.fetch_info()` accepts an optional shared `aiohttp.ClientSession` for connection pooling (#307)
- **Event.from_db_params() roundtrip test** (#295)

### Refactored

- **Finder event scanning** (#309): Replaced kind-specific parsing (r-tags, kind 2 content, kind 3 JSON) with kind-agnostic `tagvalues` scanning via `parse_relay_url`. Removed `EventsConfig.kinds` field. Renamed `get_events_with_relay_urls` → `fetch_event_tagvalues` (simpler query selecting only `tagvalues` + `seen_at`)
- **Logger truncation** (#300): Consolidated duplicate value truncation logic to single point in `format_kv_pairs()`
- **Dead code removal**: Removed unused `fetch_relay_events` function (#280), unused dict-based `CertificateExtractor` methods (#306), hardcoded `skipped_events` from Synchronizer (#297), unused `stagger_delay` config (#272), unnecessary `getattr` fallbacks in `run_forever()` (#275)

### Fixed

- **Relay equality** (#287, #289): Excluded `raw_url` from `Relay.__eq__` comparison, preventing false negatives when the same URL is stored with different original casing
- **SSL validation** (#268): Made conditional on successful certificate extraction, preventing false validation errors
- **`_persist_scan_chunk`** (#309): No longer re-raises non-fatal cursor update errors
- **`upsert_service_state`** (#305): Returns confirmed count from database instead of input count
- **`_get_publish_relays`** (#285): Uses `is not None` instead of truthiness check
- **`_publish_if_due`** (#279): Uses `int` timestamp consistently
- **`deep_freeze`** (#284): Returns `tuple` instead of `list` for true immutability
- **`parse_seed_file`** (#292): Widened exception handling to catch all I/O errors
- **`models_from_dict`** (#293): Catches `KeyError` for missing keys
- **`SyncCycleCounters`** (#298, #308): Removed duplicate initialization and stale `skipped_events` reference
- **NIP-11 `supported_nips`** (#291): Deduplicates NIP values during parsing
- **NIP-66 log classes** (#270): Unified reason validation to falsy check
- **NIP-66 DNS** (#269): Catches `tldextract` exceptions
- **NIP-66 GeoIP** (#278): Removed dead exception catch in `_geo()` method
- **`_NostrSdkStderrFilter`** (#299): Added max line safety valve
- **`NetworksConfig`** (#294): Logs warning on fallback to clearnet
- **`parse_fields`** (#277): Cached dispatch dict with `lru_cache`
- **One-shot mode** (#276): Wrapped in service context manager
- **Refresher** (#271): Narrowed exception catch to database errors only
- **`network_stats`** (#274): Computes unique counts at network level with direct join
- **`supported_nip_counts`** (#273): Guards against non-integer NIP values
- **`orphan_event_delete`** (#283): Added batching for large deletions
- **mypy** (#302, #304): Removed blanket `ignore_errors` from `__main__` and `asyncpg` from ignore list
- **Pre-commit mypy hook** (#303): Added missing runtime dependencies
- **LilBrotr SQL** (#282, #286): Fixed file headers and added missing Synchronizer indexes
- **Grafana** (#281): Added health check condition to `depends_on`
- **SQL templates**: Synced with all deployment fixes (batching, joins, cast guards, headers)

### Tests

- Relaxed exact mock call count assertions in Event tests (#296)
- Added 170+ new tests for Finder (JMESPath, stale cursors, metrics), Synchronizer (network filter, stale cursors), queries (`cleanup_stale_state`, `fetch_event_tagvalues`), and transport

### Documentation

- Removed incorrect case-insensitive claim from procedure name docstring (#288)
- Documented `_StderrSuppressor` global scope trade-off (#301)
- Updated service count from five to six in common package docstring (#290)

---

## [5.2.0] - 2026-02-24

Refresher service, rich analytics materialized views, shared deployment SQL, concurrent Finder event scanning, and legacy brotr deployment removal. 8 commits across 6 PRs.

### DEPLOYMENT CHANGES

These changes require deployment updates (Docker Compose, SQL schema, monitoring). No Python API breaking changes.

- **Refresher service container**: New `refresher` container added to both `docker-compose.yaml` files. Requires `DB_WRITER_PASSWORD` environment variable and `config/services/refresher.yaml` config file
- **`deployments/brotr/` removed**: The legacy monolithic deployment has been deleted. Use `bigbrotr` or `lilbrotr` instead
- **Materialized views shared**: All 11 materialized views, 12 refresh functions, and matview indexes are now present in both bigbrotr and lilbrotr (previously only bigbrotr had statistical views). LilBrotr deployments require fresh `initdb` or manual `06_materialized_views.sql` + `07_functions_refresh.sql` + `08_indexes.sql` execution
- **Config class renames**: `PoolLimitsConfig` → `LimitsConfig`, `PoolTimeoutsConfig` → `TimeoutsConfig`, `PoolRetryConfig` → `RetryConfig`, `BrotrTimeoutsConfig` → `TimeoutsConfig`. Old names are removed (no backward compatibility shim)

### Added

- **Refresher service** (`services/refresher/`): Periodically refreshes all 11 materialized views in 3-level dependency order (relay_metadata_latest → independent stats → dependent stats). Per-view logging, timing, error isolation, and Prometheus gauges (`views_refreshed`, `views_failed`) (#207, #208)
- **4 new materialized views**: `network_stats` (per-network relay/event/pubkey/kind counts), `relay_software_counts` (NIP-11 software distribution), `supported_nip_counts` (NIP support frequency), `event_daily_counts` (daily event volume time series) (#206)
- **Concurrent Finder event scanning**: `find_from_events()` uses `asyncio.TaskGroup` + `asyncio.Semaphore` for bounded concurrent relay scanning, replacing the sequential `for` loop. New config field `ConcurrencyConfig.max_parallel_events` (default: 10) (#203)
- **Refresher Docker containers**: Service definitions and Prometheus scrape jobs in both bigbrotr and lilbrotr `docker-compose.yaml` and `prometheus.yaml` (#208)
- **389 Refresher unit tests**: Full coverage of service lifecycle, dependency ordering, error handling, metrics, and configuration validation (#207)
- **Comprehensive codebase review** (`REVIEW.md`): Full project audit covering all source files, tests, deployment configs, SQL, and documentation. 58 findings documented with exact locations and solutions (#208)

### Refactored

- **Materialized views redesigned** (#206): 6 existing BigBrotr stat matviews enriched with `events_per_day`, `unique_kinds`, NIP-11 info columns, NIP-01 category labels, and `HAVING >= 2` anti-explosion filter. `all_statistics_refresh()` updated with 3-level dependency ordering
- **Deployment SQL shared** (#205, #207): Moved matview definitions, refresh functions, and indexes from bigbrotr-specific Jinja2 overrides to shared base templates. Both bigbrotr and lilbrotr now generate identical matview SQL from the same base blocks (`extra_materialized_views`, `extra_refresh_functions`, `extra_matview_indexes`)
- **Deployment base restructured** (#205): `_template` renamed to `brotr` as the reference implementation. Integration tests reorganized by deployment: `base/` (61 tests), `bigbrotr/` (25 tests), `lilbrotr/` (8 tests)
- **Config naming cleaned up** (#204): Removed redundant prefixes from 4 config classes. Slimmed down `__init__.py` exports to public API only, removing 45+ dead re-exports across 6 packages. Removed ~110 decorative comments while preserving ~65 meaningful comments
- **`deployments/brotr/` removed** (#207): 35 files deleted after matview consolidation made brotr and bigbrotr generate identical SQL. `generate_sql.py` updated to produce 20 files instead of 30

### Fixed

- **`BaseService.from_yaml()` return type** (#203): Factory methods `from_yaml()`, `from_dict()`, and `__aenter__()` now return `Self` instead of `"BaseService[ConfigT]"`, giving type checkers the correct subclass return type
- **`ConcurrencyConfig.max_parallel` renamed** (#203): Renamed to `max_parallel_api` for clarity, distinguishing API-based from event-based concurrency

### Documentation

- MkDocs cross-references fixed for removed re-exports (#204)
- README, database.md, architecture.md, configuration.md, custom-deployment.md, sql-templates.md, and new-service.md updated for Refresher service, shared matviews, and deployment changes
- PostgreSQL guide updated for 25 stored functions (was 21)

---

## [5.1.0] - 2026-02-23

Major infrastructure and architecture release: services restructured into packages with clear public APIs, PostgreSQL role isolation with PgBouncer dual-pool routing, full monitoring stack (postgres-exporter + Grafana dashboards), asyncpg/PgBouncer compatibility hardening, and comprehensive audit remediation across all layers. 152 commits across 22 PRs.

### DEPLOYMENT CHANGES

These changes require deployment updates (env vars, Docker Compose, PostgreSQL schema). No Python API breaking changes.

- **`DB_PASSWORD` renamed to `DB_ADMIN_PASSWORD`**: Update `.env` files and Docker Compose environment sections
- **PostgreSQL role isolation**: New `*_writer` and `*_reader` roles replace single-role access. Requires fresh `initdb` or manual `98_grants.sh` execution
- **PgBouncer dual-pool**: Separate `[bigbrotr_writer]` and `[bigbrotr_reader]` pool sections. Update `pgbouncer.ini` and `userlist.txt`
- **`metadata.metadata_type` column renamed to `type`**: SQL schema change across all deployments. Requires fresh `initdb` or manual migration
- **`pg_stat_statements` extension**: Now enabled in all deployments. Requires `shared_preload_libraries` in `postgresql.conf`

### Added

- **PostgreSQL role isolation** (`98_grants.sh`): Separate writer (DML + EXECUTE) and reader (SELECT + EXECUTE + `pg_monitor`) roles with principle of least privilege (#197)
- **PgBouncer dual-pool routing** (`pgbouncer.ini`): Writer and reader pools with independent connection limits, routed by PostgreSQL role (#197)
- **Per-service pool overrides** (`BaseServiceConfig`): Services can override `min_size`, `max_size`, and timeouts in their YAML config (#197)
- **Postgres-exporter** (`monitoring/postgres-exporter/`): Custom SQL queries for materialized view age, event ingestion rates, relay counts, service state health (#196)
- **Grafana dashboard panels**: 35+ panels covering PostgreSQL internals, relay statistics, event pipeline, service health across all deployments (#196, #198)
- **Prometheus metrics for Finder and Synchronizer**: Relay discovery counts, event fetch counters, cursor synchronization progress (#198)
- **`pg_stat_statements`**: Enabled across all deployments (template, bigbrotr, lilbrotr) for query performance analysis (#199)
- **Template schema completeness**: Views, materialized views, refresh functions, and full indexes now included in `_template` deployment (#199)
- **BaseNip abstract hierarchy** (`nips/base.py`): Uniform `BaseNip` → `BaseNipMetadata` → `BaseNipDependencies` class hierarchy for all NIP implementations (#174)
- **Lazy imports** (`bigbrotr/__init__.py`): Deferred import system for faster CLI startup (#162)
- **Integration tests**: Full stored procedure coverage with testcontainers PostgreSQL (#195)
- **SQL generation tooling**: Jinja2 templates (`tools/templates/sql/`) with CI drift check via `generate_sql.py --check` (#162)
- **Bounded file download** (`utils/http.py`): `download_file()` with configurable size cap for GeoLite2 and NIP-11 responses (#174)
- **PgBouncer `query_timeout`**: 300s server-side safety net for abandoned queries (#199)

### Refactored

- **Services package restructure** (#194): All 5 services converted from single modules to packages with explicit public APIs:
  - Each service now exposes granular methods (`seed()`, `find_from_events()`, `validate()`, `fetch_relays()`, etc.)
  - Extracted `GeoReaders`, `NetworkSemaphores`, `ChunkProgress` as standalone classes
  - Split `transport.py` into `transport.py` (low-level WebSocket) + `protocol.py` (Nostr protocol)
  - Extracted `event_builders.py` from Monitor to NIP layer
  - Standardized sub-config naming and field names across all services
- **NIP layer hardening** (#174): `BaseNipMetadata` naming consistency, NIP-66 `execute()` methods return graceful failures instead of raising, response size limits on Finder API and NIP-11 info fetch
- **Brotr simplification** (#192): Removed unused Pool/Brotr methods, aligned `ServiceState` db_params pattern, cleaned up candidate lifecycle
- **Model field alignment** (#163): `ServiceState` promoted to DbParams pattern, SQL columns and stored procedure parameters aligned with Python models
- **Schema cleanup** (#175): `metadata.metadata_type` column renamed to `type`, PgBouncer config improvements
- **Build system** (#170): Migrated from pip/setuptools to uv with `uv.lock`
- **Makefile** (#169): Redesigned for consistency with `pyproject.toml` and CI workflows
- **Documentation** (#164, #165): Consolidated CONTRIBUTING.md, fixed stale docstring references, restructured docs/ into mkdocs-material sections

### Fixed

- **asyncpg prepared statement caching** (#199): Disabled (`statement_cache_size=0`) for PgBouncer transaction mode compatibility — previously caused silent `prepared statement does not exist` errors
- **`statement_timeout` ineffective** (#199): Default changed to 0 because PgBouncer's `ignore_startup_parameters` strips it before it reaches PostgreSQL
- **PgBouncer `userlist.txt` permissions** (#199): `chmod 600` after creation to prevent credential exposure
- **Health check `start_period`** (#199): PostgreSQL 10s→30s, PgBouncer 15s→20s to accommodate init scripts
- **WAL metrics** (#199): `GRANT pg_monitor` to reader role replaces `--no-collector.wal` workaround, re-enabling full WAL collector
- **Reader role permissions** (#199): `GRANT EXECUTE` on all functions + `ALTER DEFAULT PRIVILEGES` for future functions
- **Chunked transfer-encoding** (#196): HTTP response handling in NIP-11 info fetch
- **Monitor completion percentage** (#196): Correct handling on empty batches (division by zero)
- **NIP-42 detection** (#192): Standardized `auth-required` prefix per NIP-01
- **Publisher state type** (#168): Use `CHECKPOINT` state type for publisher timestamps in `MonitorPublisherMixin`
- **Config-driven timeouts** (#167): Graceful shutdown waits and per-network semaphores now configurable
- **Docker image size** (#171, #172): Removed system Python packages and `site-packages` to resolve Trivy findings
- **Shell injection** (#162): Hardened `release.yml` against untrusted input in shell commands
- **SQL hardening** (#177, #178, #191): Cleanup functions batched, views improved, redundant indexes removed, SSL validation tightened
- **Models and core validation** (#191): Empty reason string rejection, NIP-11 parsing deduplication, fail-fast validation improvements
- **Dockerfile HEALTHCHECK** (#162): Corrected port and switched to `console_scripts` entrypoint

### Documentation

- MkDocs Material site restructured with auto-generated API reference
- Database and architecture docs updated for role isolation and schema changes
- Cross-references and broken links fixed after services restructure
- All deployment README and CI workflow documentation updated

---

## [5.0.1] - 2026-02-10

CI/CD infrastructure hardening, automated documentation site, and dependency maintenance.

### Added

- **MkDocs Material documentation site** (`mkdocs.yml`, `docs/reference/`): Auto-generated API reference via mkdocstrings, deployed to GitHub Pages on push to main
- **Release pipeline** (`.github/workflows/release.yml`): 6-job DAG -- validate, build-python, build-docker, publish-pypi (OIDC), publish-ghcr (semver tags), release (GitHub Release with SBOM artifacts)
- **Documentation workflow** (`.github/workflows/docs.yml`): Automatic rebuild on docs/source/config/changelog changes
- **CODEOWNERS** (`.github/CODEOWNERS`): `@BigBrotr/maintainers` for all paths

### Changed

- **CI pipeline overhauled** (`.github/workflows/ci.yml`): Renamed `test` → `unit-test`, added `integration-test` job, `timeout-minutes` on all jobs, `build` added to `ci-success` gate with skipped-allowed logic, Docker cache scoped per deployment
- **Dependabot grouping** (`.github/dependabot.yml`): `github-actions-all` group for major/minor/patch updates
- **Makefile**: Renamed `test` → `test-unit`, added `test-integration`, `docs`, `docs-serve`, `build` targets
- **GitHub Actions pinned by SHA** with `# vX.Y.Z` comments for Dependabot compatibility
- **Dependencies updated**: upload-artifact v4→v6, download-artifact v4→v7, codeql-action and codecov-action SHA updates

### Fixed

- **Codecov upload on Dependabot PRs**: Added `github.actor != 'dependabot[bot]'` condition to skip upload when secrets are unavailable, unblocking all automated dependency PRs
- **Docker GHA cache collision**: Added `scope=${{ matrix.deployment }}` to prevent cache eviction between bigbrotr/lilbrotr matrix jobs
- **docs.yml missing CHANGELOG.md trigger**: Root `CHANGELOG.md` included via pymdownx.snippets but wasn't in the paths filter
- **release.yml coverage overhead**: Removed unused `--cov` flags from validate job

### Documentation

- **MkDocs site**: Home page, 5 user guide sections (Architecture, Configuration, Database, Deployment, Development), Changelog, and 5 API reference modules (Core, Models, NIPs, Utils, Services)
- **README.md**: Updated CI/CD pipeline table and make targets
- **docs/DEVELOPMENT.md**: Updated make targets and test commands
- **CONTRIBUTING.md**: Migrated all commands to `make` targets, added docs section
- **PULL_REQUEST_TEMPLATE.md**: Added integration test checkbox

---

## [5.0.0] - 2026-02-09

Major quality and operational hardening release: exception hierarchy replaces all bare catches, Monitor split into 3 modules, DAG violation fixed, Docker infrastructure hardened with real healthchecks and network segmentation, CI/CD expanded with security scanning, 4 Prometheus alerting rules, and complete documentation rewrite.

### BREAKING CHANGES

- **Exception hierarchy**: All `except Exception` blocks replaced with specific catches from `bigbrotr.core.exceptions` (`BigBrotrError`, `ConfigurationError`, `DatabaseError`, `ConnectionPoolError`, `QueryError`, `ConnectivityError`, `RelayTimeoutError`, `RelaySSLError`, `ProtocolError`, `PublishingError`)
- **Monitor split into 3 modules**: `monitor.py` (~1,000 lines orchestration) + `monitor_publisher.py` (~230 lines Nostr broadcasting) + `monitor_tags.py` (~280 lines NIP-66 tag building). Import `MonitorPublisherMixin` and `MonitorTagsMixin` separately.
- **ServiceState moved**: `ServiceState`, `ServiceStateKey`, `StateType`, `EventKind` moved from `services/common/constants` to `models/service_state.py` (re-exported from constants for backward compatibility)
- **Per-deployment Dockerfiles deleted**: Single parametric `deployments/Dockerfile` with `ARG DEPLOYMENT` replaces 3 separate Dockerfiles
- **Docker networks**: Flat bridge network replaced with `data-network` + `monitoring-network` segmentation
- **SQL functions**: All 22 stored functions now require `SECURITY INVOKER`

### Added

- **Exception hierarchy** (`core/exceptions.py`): 10-class typed exception tree replacing bare `except Exception` across 15 files. Transient errors (`ConnectionPoolError`) distinguished from permanent (`QueryError`) for retry logic
- **Prometheus alerting rules** (`deployments/bigbrotr/monitoring/prometheus/rules/alerts.yml`): 4 alerts -- ServiceDown (critical, 5m), HighFailureRate (warning, 0.1/s over 5m), PoolExhausted (critical, 2m), DatabaseSlow (warning, p99 > 5s)
- **Makefile**: 11 targets -- `lint`, `format`, `typecheck`, `test`, `test-fast`, `coverage`, `ci`, `docker-build`, `docker-up`, `docker-down`, `clean`. Parametric Docker targets via `DEPLOYMENT=` variable
- **CI security scanning**: `pip-audit --strict` for dependency vulnerabilities, Trivy image scanning (CRITICAL/HIGH severity), CodeQL static analysis (`.github/workflows/codeql.yml`), Dependabot for pip/docker/github-actions (`.github/dependabot.yml`)
- **Shared test fixtures** (`tests/fixtures/relays.py`): Canonical relay fixtures (`relay_clearnet`, `relay_tor`, `relay_i2p`, `relay_loki`, `relay_ipv6`, `relay_clearnet_with_port`, `relay_clearnet_ws`) registered as pytest plugin via `pytest_plugins`
- **Pre-commit hooks**: Added `hadolint` (Dockerfile linting), `markdownlint` (with `--fix`), `sqlfluff-fix` (PostgreSQL SQL formatting)
- **Global test timeout**: `--timeout=120` in pytest addopts prevents hanging tests

### Refactored

- **Monitor service split**: Single 1,400+ line `monitor.py` decomposed into 3 modules using mixin pattern -- `MonitorPublisherMixin` (event broadcasting) and `MonitorTagsMixin` (NIP-66 tag building) mixed into `Monitor` class
- **ServiceState extraction**: `ServiceState`, `ServiceStateKey`, `StateType`, `EventKind` moved from `services/common/constants.py` to `models/service_state.py`, fixing DAG violation where `core/brotr.py` had a `TYPE_CHECKING` import from services layer
- **Single parametric Dockerfile**: `deployments/Dockerfile` with `ARG DEPLOYMENT=bigbrotr` replaces 3 per-deployment Dockerfiles. Multi-stage build (builder -> production), non-root execution (UID 1000), `tini` as PID 1 for proper signal handling
- **Docker healthchecks**: Fake `/proc/1/cmdline` checks replaced with real service probes (`pg_isready` for PostgreSQL/PGBouncer, `curl http://localhost:<port>/metrics` for application services)
- **Docker network segmentation**: Single flat bridge split into `data-network` (postgres, pgbouncer, tor, services) and `monitoring-network` (prometheus, grafana, services)
- **Docker resource limits**: CPU and memory limits on all containers (postgres 2 CPU/2 GB, services 1 CPU/512 MB, pgbouncer 0.5 CPU/256 MB)
- **SQL hardening**: `SECURITY INVOKER` on all 22 stored functions, `DISTINCT ON` queries paired with `ORDER BY` for deterministic results, batched cleanup operations

### Changed

- **pyproject.toml**: Version `4.0.0` -> `5.0.0`; coverage `fail_under = 80` (branch coverage); `--timeout=120` in pytest addopts; `pytest-timeout` added to dev dependencies
- **Logger JSON format**: `_format_json()` now emits `timestamp` (ISO 8601), `level`, `service` fields for cloud log aggregation compatibility
- **Metrics config**: `MetricsConfig` with `enabled`, `port`, `host`, `path` fields; `host` defaults to `"127.0.0.1"` (use `"0.0.0.0"` in containers)
- **Docker Compose**: `stop_grace_period: 60s` and `STOPSIGNAL SIGTERM` for graceful shutdown; JSON-file logging driver with size rotation
- **CI pipeline**: Single coverage run for all Python versions (removed duplicate non-coverage step for 3.11); Trivy scan on both BigBrotr and LilBrotr images; Python 3.14 with `allow-prereleases: true`

### Fixed

- **DAG violation**: Removed `TYPE_CHECKING` import of `ServiceState` from services layer in `core/brotr.py`
- **Metadata column naming**: `MetadataDbParams` consistently uses `payload` field matching SQL column `metadata.payload`
- **Grafana dashboards**: Set `editable: false` on provisioned dashboards to prevent drift

### Documentation

- **Complete docs/ rewrite**: All 6 documentation files rewritten from scratch for v5.0.0 accuracy:
  - `docs/ARCHITECTURE.md` (~970 lines): Diamond DAG, all 5 layers, every service flow, data architecture, design patterns
  - `docs/CONFIGURATION.md` (~760 lines): Complete YAML reference for all services with Pydantic models, CLI args, env vars
  - `docs/DATABASE.md` (~620 lines): All 6 tables, 22 stored functions, 7 materialized views, complete index reference
  - `docs/DEPLOYMENT.md` (~515 lines): Docker Compose and manual deployment, monitoring stack, backup/recovery
  - `docs/DEVELOPMENT.md` (~460 lines): Setup, testing, code quality, CI/CD pipeline, contribution guide
  - `docs/README.md` (~33 lines): Documentation index with quick links
- **README.md** (~460 lines): Complete project overview rewritten with verified data from codebase
- **Removed obsolete docs**: `OVERVIEW.md` (redundant with README), `TECHNICAL.md` (redundant with ARCHITECTURE), `V5_PLAN.md` (internal planning)
- **CLAUDE.md**: Updated for v5.0.0 architecture, exception hierarchy, monitor split, ServiceState location

---

## [4.0.0] - 2026-02-09

Major architectural restructuring: all code moved under `bigbrotr` namespace package with diamond DAG dependency graph. Nine design problems resolved. No functional or behavioral changes — pure structural refactor.

### BREAKING CHANGES

- **All imports changed**: `from core.X` / `from models.X` / `from services.X` / `from utils.X` → `from bigbrotr.core.X` / `from bigbrotr.models.X` / `from bigbrotr.services.X` / `from bigbrotr.utils.X`
- **CLI entry point changed**: `python -m services <name>` → `python -m bigbrotr <name>` (or `bigbrotr <name>` via console script)
- **Deployment directories renamed**: `implementations/` → `deployments/`
- **Config directories renamed**: `yaml/core/brotr.yaml` → `config/brotr.yaml` (flattened); `yaml/services/` → `config/services/`
- **NIP models extracted**: `from models.nips.nip11 import Nip11` → `from bigbrotr.nips.nip11 import Nip11`
- **YAML loader moved**: `from utils.yaml import load_yaml` → `from bigbrotr.core.yaml import load_yaml`
- **Dependency files removed**: `requirements.txt` / `requirements-dev.txt` deleted; use `pip install -e .` or `pip install -e ".[dev]"`

### Refactored

- **Namespace package**: All source code moved under `src/bigbrotr/` to eliminate pip namespace collisions from generic top-level names (`core`, `models`, `services`, `utils`)
- **Diamond DAG architecture**: Five-layer dependency graph (`services → {core, nips, utils} → models`) replacing the previous linear four-layer stack
- **NIP extraction**: `models/nips/` (18 files with I/O logic: HTTP, DNS, SSL, WebSocket, GeoIP) extracted to `bigbrotr/nips/` as a separate package, restoring models layer purity
- **YAML loader**: `utils/yaml.py` moved to `core/yaml.py` (resolving upward layer dependency — only consumers were in core)
- **CLI decoupled**: `services/__main__.py` moved to `bigbrotr/__main__.py` with sync `cli()` wrapper for console_scripts entry point
- **Monitoring directories merged**: `grafana/` + `prometheus/` → `monitoring/grafana/` + `monitoring/prometheus/` in each deployment
- **Root cleanup**: Deleted `alembic.ini`, `migrations/`, `requirements*.txt`, `requirements*.in`; moved `generate_sql.py` and `templates/` to `tools/`
- **Deleted `src/__init__.py`**: Removed the 107-line file with 36 re-exports that violated the src-layout pattern

### Changed

- **pyproject.toml**: Version `3.0.4` → `4.0.0`; `known-first-party = ["bigbrotr"]`; `include = ["bigbrotr*"]`; `files = ["src/bigbrotr"]` (mypy); `source = ["src/bigbrotr"]` (coverage); added `[project.scripts] bigbrotr = "bigbrotr.__main__:cli"`
- **100+ source files**: Moved under `src/bigbrotr/` with updated imports
- **40+ test files**: Updated with `bigbrotr`-prefixed imports and ~100 mock patch targets rewritten
- **3 Dockerfiles + 3 docker-compose files**: Updated paths, commands, and volume mounts
- **CI workflow**: Updated for new deployment and source paths
- **12 deployment YAML configs**: Updated `_template/yaml/` → `_template/config/` in comments
- **6 service module docstrings**: Updated example paths from `yaml/` to `config/`

### Fixed

- **Stale NIP class references** (pre-existing, exposed by restructuring):
  - `Nip11FetchMetadata` → `Nip11InfoMetadata` (renamed in v3.1.0 but `__init__.py` not updated; fully completed in v5.1.0)
  - `Nip66RttLogs` → `Nip66RttMultiPhaseLogs`
  - `RttDependencies` → `Nip66RttDependencies`
  - `Nip66TestFlags` → `Nip66Selection` + `Nip66Options`

### Added

- **Console script**: `bigbrotr` command via `[project.scripts]` in pyproject.toml
- **Integration test infrastructure**: `tests/integration/conftest.py` with testcontainers-based ephemeral PostgreSQL; `tests/integration/test_database_roundtrip.py`
- **SQL generation tooling**: `tools/generate_sql.py` + `tools/templates/sql/` (Jinja2 templates for deployment SQL files)

### Documentation

- **README.md**: Version badge, five-layer diamond DAG architecture diagram, updated all paths/commands/project structure tree, test count → 1896
- **All docs/*.md**: Updated for new paths, imports, and architecture (ARCHITECTURE, CONFIGURATION, DATABASE, DEPLOYMENT, DEVELOPMENT, OVERVIEW, TECHNICAL)
- **CLAUDE.md**: Rewritten for bigbrotr namespace and diamond DAG architecture
- **CONTRIBUTING.md**: Updated paths and install commands
- **Agent knowledge base**: All 7 `.claude/agents/bigbrotr-expert/` files updated

---

## [3.0.4] - 2026-02-07

Architecture refinement release: domain logic extracted from core to `services/common/`, three-tier architecture formalized, and comprehensive test and documentation alignment.

### Refactored
- **`services/common/` package**: Extracted domain queries, constants, and mixins from `core/` into a new shared service infrastructure package with three stable modules:
  - `constants.py`: `ServiceName` and `DataType` StrEnum classes replacing all hardcoded service/data-type strings
  - `mixins.py`: `BatchProgressMixin` and `NetworkSemaphoreMixin` (moved from `core/service.py` and `utils/progress.py`)
  - `queries.py`: 13 domain SQL query functions parameterized with enum values (moved from `core/queries.py`)
- **Core layer purified**: `core/` is now a generic infrastructure facade with zero domain logic
  - Renamed `core/service.py` to `core/base_service.py` (contains only `BaseService` and `BaseServiceConfig`)
  - Removed `core/queries.py` (absorbed into `services/common/queries.py`)
  - Removed `BatchProgress`, `NetworkSemaphoreMixin` from core
- **Brotr API simplified**:
  - Removed `retry` parameter from facade methods (retry always handled internally by Pool)
  - Removed `conn` parameter from `_call_procedure` (use `transaction()` instead)
  - Removed `default_query_limit` and `materialized_views` from `BrotrConfig`
  - Simplified `refresh_matview()` injection prevention (regex guard only)
  - Fixed `result or 0` to `result if result is not None else 0` for correct falsy handling
- **Model layer decoupled**: NIP models (`nip11/fetch`, `nip66/*`) now use stdlib `logging` instead of `core.logger`, maintaining zero core dependencies
- **Model caching**: All frozen dataclasses (`Relay`, `EventRelay`, `Metadata`, `RelayMetadata`) now cache `to_db_params()` in `__post_init__`
- **Service registry**: Uses `ServiceEntry` NamedTuple with `ServiceName` enum keys instead of raw tuples
- **`utils/transport.py`**: Decoupled from `core.logger` (stdlib `logging` only)
- **`utils/progress.py`**: Deleted (functionality moved to `services/common/mixins.py`)

### Changed
- **Monitor service**: Aligned `MetadataFlags` and `CheckResult` with `MetadataType` enum values (`nip11` -> `nip11_info`); removed unused `nip66_probe` field
- **Infrastructure**: Removed `CHECK` constraints from `relay_metadata.metadata_type` across all implementations; validation handled in Python enum layer
- **Implementation configs**: Standardized `.env.example`, `docker-compose.yaml`, and `04_functions_cleanup.sql` across template, bigbrotr, and lilbrotr

### Added
- **69 new unit tests** for `services/common/`:
  - `test_constants.py` (15 tests): `ServiceName` and `DataType` StrEnum value and behavior coverage
  - `test_mixins.py` (15 tests): `BatchProgressMixin` and `NetworkSemaphoreMixin` initialization, composition, and edge cases
  - `test_queries.py` (39 tests): All 13 domain SQL query functions with mocked Brotr, SQL fragment verification, and edge cases
- Total test count: **1854** (up from 1776)

### Documentation
- **Three-tier architecture**: Reframed documentation around Foundation (core + models), Active (services + utils), and Implementation tiers
- **All docs updated**: `ARCHITECTURE.md`, `DEVELOPMENT.md`, `TECHNICAL.md`, `README.md`, `CLAUDE.md` reflect renamed files and `services/common/`
- **Agent knowledge base updated**: `AGENT.md`, `core-reference.md`, `architecture-index.md` aligned with new structure
- **YAML template comments**: Fixed `BaseServiceConfig` file path references in all 4 service templates
- Removed deprecated `test_nip11_nip66.ipynb` notebook

### Chore
- Bumped version to 3.0.4
- Updated secrets baseline line numbers
- Added `AUDIT_REPORT.*` pattern to `.gitignore`
- Removed stale `RESTRUCTURING_PLAN.md`

---

## [3.0.3] - 2026-02-06

Documentation-focused release with comprehensive docstring rewrites, standardized file headers, and cleaned up project documentation.

### Documentation
- **Core layer**: Rewrote docstrings for all core modules (pool, brotr, service, metrics, logger)
- **Models layer**: Rewrote docstrings for all data model modules
- **Services layer**: Rewrote docstrings for services and utilities
- **SQL**: Rewrote SQL file headers and function documentation
- **YAML**: Standardized YAML configuration file headers
- **Tests**: Cleaned up test documentation and removed redundant comments
- **Project docs**: Rewrote project documentation and cleaned up markdown files
- **Agents**: Fixed outdated references and cleaned up agent knowledge base

### Chore
- Updated secrets baseline line numbers

---

## [3.0.2] - 2026-02-05

Code quality and maintainability release with FieldSpec pattern, module reorganization, and comprehensive test restructuring.

### Changed
- **FieldSpec pattern**: Consolidated field parsing with `FieldSpec` dataclass for consistent validation and transformation across NIP models
- **Module reorganization**:
  - Logger now at `src/core/logger.py`, imported as `from core.logger import Logger`
  - Renamed `base_service` to `service` and consolidated mixins
  - Added `NetworkSemaphoreMixin` for simplified service code
- **NIP-11 refactoring**:
  - Migrated to FieldSpec pattern for improved type safety
  - Simplified structure with keyword-only arguments in `create` method
- **NIP-66 refactoring**:
  - Migrated to FieldSpec pattern for improved code quality
  - Extracted `GeoExtractor` helper class for geolocation logic
  - Extracted `CertificateExtractor` helper class for SSL certificate parsing
  - Decomposed RTT method into focused phase methods
  - Added keyword-only arguments in `create` method
- **Models**: Added fail-fast validation and unified `from_db_params` API across all models
- **Core**: Improved type safety and simplified database operations
- **Services**: Updated imports for module renames, simplified code structure
- **Utils**: Moved `NetworkType` enum for better organization, improved configuration flexibility

### Refactored
- **Monitor service**: Updated NIP-11 API usage and decomposed tag building logic
- **Test structure**:
  - Renamed `test_cli.py` to `test_main.py`
  - Renamed `test_base_service.py` to `test_service.py`
  - Moved `test_logger.py` to `tests/unit/core/` to match `src/core/logger.py` location
  - Restructured NIP-11 tests into focused modules (`test_nip11.py`, `test_data.py`, `test_logs.py`, `test_fetch.py`)
  - Restructured NIP-66 tests into focused modules (`test_nip66.py`, `test_rtt.py`, `test_ssl.py`, `test_geo.py`, `test_net.py`, `test_dns.py`, `test_http.py`, `test_logs.py`)
  - Added comprehensive tests for `base.py` and `parsing.py`
  - Updated tests for fail-fast validation and simplified return types

### Style
- Reordered imports per isort conventions
- Combined nested if statements per ruff SIM102

### Chore
- Added EditorConfig for consistent coding styles
- Cleaned up project configuration
- Removed versioned release notes from repository
- Removed auto-generated footer from agents README

---

## [3.0.1] - 2026-02-04

Major refactoring release with new NIP models architecture, Python-side hash computation, and comprehensive documentation alignment.

### Added
- **NIP-11 subpackage** (`src/models/nips/nip11/`):
  - `Nip11` main class with database serialization
  - `Nip11InfoData` with relay info document structure (originally `Nip11FetchData`)
  - `Nip11InfoLogs` for info retrieval status tracking (originally `Nip11FetchLogs`)
  - HTTP fetch implementation with SSL fallback
- **NIP-66 subpackage** (`src/models/nips/nip66/`):
  - `Nip66` aggregate class with database serialization
  - `Nip66RttMetadata` with WebSocket probe testing
  - `Nip66SslMetadata` with certificate validation
  - `Nip66GeoMetadata` with MaxMind GeoLite2 lookup
  - `Nip66NetMetadata` with ASN lookup
  - `Nip66DnsMetadata` with comprehensive record lookup
  - `Nip66HttpMetadata` from WebSocket handshake
  - Data and logs models for all metadata types
- **NIP base classes** (`src/models/nips/base.py`) for content-addressed storage
- **Async DNS utility** (`src/utils/dns.py`) with IPv4/IPv6 support
- **Retry configuration** for all metadata types in Monitor
- `py.typed` markers for nips subpackages

### Changed
- **Hash computation moved to Python**: SHA-256 hashing now performed in Python instead of PostgreSQL for better portability
- **SQL schema updated**: All implementations (bigbrotr, lilbrotr, template) updated for BYTEA metadata id
- **Monitor service refactored** to use new nips metadata classes
- **Brotr updated** for Python-side metadata hash computation
- **Logging standardized** across all models, utils, and services
- **Default max_batch_size reduced** from 10000 to 1000
- **Network config classes separated** to fix partial YAML override inheritance
- **Metrics endpoint secured** with standardized ports

### Fixed
- Runtime imports for Pydantic models restored
- Column name in `relay_metadata_latest` materialized view corrected
- Null byte validation added to Event content
- Logger-related issues resolved (#124, #78, #99, #141, #92)
- Documentation aligned with actual codebase:
  - BigBrotr Expert reference files updated for NIP subpackages
  - Database column name corrected (`metadata.data` → `metadata.metadata`)
  - BaseService constructor signature documented (config is optional)
  - Version references aligned across all files

---

## [3.0.0] - 2026-01-26

Major release with four-layer architecture, expanded NIP-66 compliance, and comprehensive AI-assisted development tooling.

### Breaking Changes
- Service `initializer` renamed to `seeder`
- Service config classes now extend `BaseServiceConfig` instead of `BaseModel`
- Constructor signature changed: `__init__(brotr, config)` instead of `__init__(config, brotr)`
- MetadataType values changed: `nip66_rtt` split into granular types

### Added
- **Four-layer architecture**: Added Utils layer between Core and Services
- **New Utils module** (`src/utils/`):
  - `NetworkConfig` - Multi-network configuration (clearnet, tor, i2p, loki)
  - `KeysConfig` - Nostr keypair configuration from environment
  - `BatchProgress` - Batch processing progress tracking dataclass
  - `transport.py` - Multi-network transport factory (aiohttp/aiohttp-socks)
  - `yaml.py` - YAML configuration loading utilities
  - `parsing.py` - URL and data parsing utilities
- **Prometheus metrics** (`src/core/metrics.py`):
  - `SERVICE_INFO` - Static service metadata
  - `SERVICE_GAUGE` - Point-in-time values with labels
  - `SERVICE_COUNTER` - Cumulative counters with labels
  - `CYCLE_DURATION_SECONDS` - Histogram for cycle duration percentiles
- **MetadataType expanded** from 4 to 7 types:
  - `nip11_info` - NIP-11 relay information document
  - `nip66_rtt` - Round-trip time measurements
  - `nip66_ssl` - SSL certificate information
  - `nip66_geo` - Geolocation data
  - `nip66_net` - Network information (ASN, ISP)
  - `nip66_dns` - DNS resolution data
  - `nip66_http` - HTTP header analysis
- **Validator service** - Streaming relay validation with multi-network support
  - NIP-42 authentication support
  - Probabilistic candidate selection (Efraimidis-Spirakis algorithm)
  - Automatic cleanup of failed candidates (configurable threshold)
- **Full multi-network support** in all services:
  - Clearnet (wss://, ws://)
  - Tor (.onion via SOCKS5 proxy)
  - I2P (.i2p via SOCKS5 proxy)
  - Lokinet (.loki via SOCKS5 proxy)
- **Monitor service restructured**:
  - `BatchProgress` for tracking check progress
  - `CheckResult` for individual relay check results
  - `Nip66RelayMetadata` for NIP-66 compliant output
- **31 AI agents** for development assistance:
  - 29 generic agents (python-pro, security-auditor, etc.)
  - 2 specialized agents (nostr-expert, bigbrotr-expert)
- **3 audit commands** (`/audit-quick`, `/audit-core`, `/audit-full`)
- NIP-42 authentication support in Validator, Monitor, and Synchronizer
- Comprehensive docstrings across all models and services
- Keys model for loading Nostr keypairs from environment variables

### Changed
- **Architecture**: Three-layer → Four-layer (Core, Utils, Services, Implementation)
- **Test structure** reorganized to `tests/unit/{core,models,services,utils}/`
- **Config inheritance**: All service configs now extend `BaseServiceConfig`
- **Constructor order**: `(brotr, config)` instead of `(config, brotr)` for consistency
- Finder now stores candidates in `service_data` table (Validator picks them up)
- Monitor checks use `service_data` checkpoints for efficient scheduling
- Synchronizer uses `relay_metadata_latest` view for faster relay selection
- Improved error handling and logging across all services
- Enhanced test coverage with 411+ unit tests

### Fixed
- Race conditions in Monitor metrics collection (added `asyncio.Lock`)
- Resource leaks in Monitor client shutdown (added `try/finally`)
- Memory optimization in Monitor with chunked relay processing

### Migration Guide

**1. Update service imports:**
```python
# Before (v2.x)
from pydantic import BaseModel
class MyServiceConfig(BaseModel):
    interval: float = 300.0

# After (v3.0.0)
from core import BaseServiceConfig
class MyServiceConfig(BaseServiceConfig):
    # interval is inherited from BaseServiceConfig
    pass
```

**2. Update constructor signatures:**
```python
# Before (v2.x)
def __init__(self, config: MyConfig, brotr: Brotr):
    self._config = config
    self._brotr = brotr

# After (v3.0.0)
def __init__(self, brotr: Brotr, config: MyConfig | None = None):
    super().__init__(brotr=brotr, config=config or MyConfig())
```

**3. Update MetadataType references:**
```python
# Before (v2.x)
type = MetadataType.NIP66_RTT  # Was used for all NIP-66 data

# After (v3.0.0)
type = MetadataType.NIP66_RTT    # Only for RTT measurements
type = MetadataType.NIP66_PROBE  # For connectivity checks
type = MetadataType.NIP66_SSL    # For SSL certificate data
type = MetadataType.NIP66_GEO    # For geolocation
type = MetadataType.NIP66_NET    # For network info
type = MetadataType.NIP66_DNS    # For DNS data
type = MetadataType.NIP66_HTTP   # For HTTP headers
```

---

## [2.0.0] - 2025-12

Complete architectural rewrite from monolithic prototype to modular, enterprise-ready system.

### Added
- Three-layer architecture (Core, Service, Implementation)
- Multiple implementations: BigBrotr (full) and LilBrotr (lightweight)
- Core components: Pool, Brotr, BaseService, Logger
- Services: Seeder, Finder, Monitor, Synchronizer
- Async database driver (asyncpg) with connection pooling
- PGBouncer for connection management
- BYTEA storage for 50% space savings
- Pydantic configuration validation
- YAML-driven configuration
- Service state persistence
- Graceful shutdown handling
- NIP-11 and NIP-66 content deduplication
- 174 unit tests with pytest
- Pre-commit hooks (ruff, mypy)
- Comprehensive documentation (ARCHITECTURE, CONFIGURATION, DATABASE, DEVELOPMENT, DEPLOYMENT)
- GitHub Actions CI pipeline (lint, typecheck, test matrix Python 3.11-3.14, Docker build)
- Issue templates (bug report, feature request)
- Pull request template
- CHANGELOG.md (Keep a Changelog format)
- CONTRIBUTING.md (contribution guidelines)
- SECURITY.md (security policy)
- CODE_OF_CONDUCT.md (Contributor Covenant)

### Changed
- Architecture: Monolithic → Three-layer modular design
- Configuration: Environment variables → YAML + Pydantic
- Database driver: psycopg2 (sync) → asyncpg (async)
- Storage format: CHAR (hex) → BYTEA (binary)
- Service name: syncronizer → synchronizer (fixed typo)
- Multicore: multiprocessing.Pool → aiomultiprocess

### Removed
- pgAdmin (use external tools instead)
- pandas dependency
- secp256k1/bech32 dependencies (using nostr-sdk)

### Fixed
- Connection pooling (was creating new connections per operation)
- State persistence (services now resume from last state)
- Configuration validation (now validates at startup)
- Graceful shutdown (services handle SIGTERM properly)

---

## [1.0.0] - 2025-06

Initial prototype release.

### Added
- Full event archiving from Nostr relays
- Relay monitoring with NIP-11 support
- Connectivity testing (openable, readable, writable)
- RTT measurement for all operations
- Tor support for .onion relays
- Multicore processing with multiprocessing.Pool
- Time-window stack algorithm for large event volumes
- Docker Compose deployment
- PostgreSQL database with stored functions
- 8,865 seed relay URLs

### Known Issues
- No async database (synchronous psycopg2)
- No connection pooling
- Finder service not implemented (stub only)
- No unit tests
- No configuration validation
- No graceful shutdown
- No state persistence
- Typo in service name ("syncronizer")

---

[Unreleased]: https://github.com/bigbrotr/bigbrotr/compare/v5.9.0...HEAD
[5.9.0]: https://github.com/bigbrotr/bigbrotr/compare/v5.8.0...v5.9.0
[5.8.0]: https://github.com/bigbrotr/bigbrotr/compare/v5.7.0...v5.8.0
[5.7.0]: https://github.com/bigbrotr/bigbrotr/compare/v5.6.0...v5.7.0
[5.6.0]: https://github.com/bigbrotr/bigbrotr/compare/v5.5.0...v5.6.0
[5.5.0]: https://github.com/bigbrotr/bigbrotr/compare/v5.4.0...v5.5.0
[5.4.0]: https://github.com/bigbrotr/bigbrotr/compare/v5.3.1...v5.4.0
[5.3.1]: https://github.com/bigbrotr/bigbrotr/compare/v5.3.0...v5.3.1
[5.3.0]: https://github.com/bigbrotr/bigbrotr/compare/v5.2.0...v5.3.0
[5.2.0]: https://github.com/bigbrotr/bigbrotr/compare/v5.1.0...v5.2.0
[5.1.0]: https://github.com/bigbrotr/bigbrotr/compare/v5.0.1...v5.1.0
[5.0.1]: https://github.com/bigbrotr/bigbrotr/compare/v5.0.0...v5.0.1
[5.0.0]: https://github.com/bigbrotr/bigbrotr/compare/v4.0.0...v5.0.0
[4.0.0]: https://github.com/bigbrotr/bigbrotr/compare/v3.0.4...v4.0.0
[3.0.4]: https://github.com/bigbrotr/bigbrotr/compare/v3.0.3...v3.0.4
[3.0.3]: https://github.com/bigbrotr/bigbrotr/compare/v3.0.2...v3.0.3
[3.0.2]: https://github.com/bigbrotr/bigbrotr/compare/v3.0.1...v3.0.2
[3.0.1]: https://github.com/bigbrotr/bigbrotr/compare/v3.0.0...v3.0.1
[3.0.0]: https://github.com/bigbrotr/bigbrotr/compare/v2.0.0...v3.0.0
[2.0.0]: https://github.com/bigbrotr/bigbrotr/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/bigbrotr/bigbrotr/releases/tag/v1.0.0
