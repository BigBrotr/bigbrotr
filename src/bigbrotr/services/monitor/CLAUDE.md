# monitor — Relay Health Monitoring

Performs comprehensive health checks on relays (NIP-11 + 6 NIP-66 tests), persists results
as content-addressed metadata, and publishes relay discovery events to the Nostr network.

## Service Class

**`Monitor(ConcurrentStreamMixin, NetworkSemaphoresMixin, GeoReaderMixin, ClientsMixin, BaseService[MonitorConfig])`**

| ClassVar | Value |
|----------|-------|
| `SERVICE_NAME` | `ServiceName.MONITOR` |
| `CONFIG_CLASS` | `MonitorConfig` |

### `__init__(brotr, config=None)`

Creates `Clients` with `config.keys.keys`, `config.networks`, and
`config.processing.allow_insecure`. Stores `_keys` for RTT event signing.

### `run()`

1. `update_geo_databases()` — download/refresh GeoLite2 City + ASN if stale
2. Open geo readers (city if `compute.nip66_geo`, asn if `compute.nip66_net`)
3. `publish_profile()` — Kind 0 if interval elapsed
4. `publish_announcement()` — Kind 10166 if interval elapsed
5. `monitor()` — main health check loop
6. `finally`: `clients.disconnect()`, `geo_readers.close()`

### `cleanup() -> int`

Removes stale checkpoints via `delete_stale_checkpoints(brotr, keep_keys)`.
`keep_keys` includes `"announcement"` and/or `"profile"` based on which
publishing features are enabled in config.

### `monitor() -> int`

1. Get enabled networks, compute `monitored_before = int(time() - discovery.interval)`
2. `count_relays_to_monitor()` → set `total` gauge
3. Pagination loop (`chunk_size`, `max_relays` budget):
   - `fetch_relays_to_monitor()` for next batch
   - `_iter_concurrent(relays, _monitor_worker)` — async stream results
   - Classify: `chunk_successful` (`list[tuple[Relay, CheckResult]]`), `chunk_failed` (`list[Relay]`)
   - `collect_metadata(successful, store)` → `insert_relay_metadata()`
   - `upsert_monitor_checkpoints(all_checked, now)`
   - Update `succeeded`/`failed` gauges, log chunk progress
4. Returns `succeeded + failed`

### `_monitor_worker(relay) -> AsyncGenerator[tuple[Relay, CheckResult | None], None]`

Worker for `_iter_concurrent`. Yields exactly once per relay:

1. Acquire per-network semaphore (if `None` → yield `(relay, None)`, return)
2. `check_relay(relay)` → if not `has_data` → yield `(relay, None)`, return
3. `publish_discovery(relay, result)` for successful checks
4. yield `(relay, result)`
5. Exception boundary: yield `(relay, None)` — protects TaskGroup

### `check_relay(relay) -> CheckResult`

Per-relay health check orchestrator:

1. **NIP-11 fetch** first (via `retry_fetch` with lambda coroutine factory)
2. **NIP-66 RTT** (applies `min_pow_difficulty` from NIP-11 if present)
3. **`_build_parallel_checks()`** → `asyncio.gather()` for SSL, DNS, Geo, Net, HTTP
4. Returns `CheckResult` with all results; catches `TimeoutError`/`OSError` → empty result

### `_build_parallel_checks(relay, compute, timeout, proxy_url) -> dict[str, Any]`

Builds retry-wrapped coroutines for each enabled check. Clearnet-only for
SSL, DNS, Geo, Net. HTTP for all networks. Geo requires `geo_readers.city`,
Net requires `geo_readers.asn`. All checks receive `timeout` from the network config.

### Event Publishing

| Method | Kind | Trigger | Checkpoint |
|--------|------|---------|------------|
| `publish_profile()` | 0 | `is_publish_due("profile", interval)` | `upsert_publish_checkpoints(["profile"])` |
| `publish_relay_list()` | 10002 | `is_publish_due("relay_list", interval)` | `upsert_publish_checkpoints(["relay_list"])` |
| `publish_announcement()` | 10166 | `is_publish_due("announcement", interval)` | `upsert_publish_checkpoints(["announcement"])` |
| `publish_discovery(relay, result)` | 30166 | Per successful health check | None |

Profile/announcement resolve relays from their own config or fall back to
`publishing.relays`. Connect lazily via `clients.get_many()`, build events via
`build_profile_event()` / `build_monitor_announcement()` / `build_relay_discovery()`,
broadcast via `broadcast_events()`.

### `update_geo_databases()`

Downloads GeoLite2 City/ASN databases. Checks if file exists and if
`max_age_days` exceeded. Uses `download_bounded_file()`. Suppresses
`OSError`/`ValueError` so transient failures do not block the monitoring cycle.

## Configuration (`configs.py`)

### `MetadataFlags`

7 boolean fields (all default `True`): `nip11_info`, `nip66_rtt`, `nip66_ssl`,
`nip66_geo`, `nip66_net`, `nip66_dns`, `nip66_http`.

Method `get_missing_from(superset)` returns field names enabled in self but disabled
in superset.

### `RetryConfig`

| Field | Default | Constraints |
|-------|---------|-------------|
| `max_attempts` | `0` | `ge=0, le=10` |
| `initial_delay` | `1.0` | `ge=0.1, le=10.0` |
| `max_delay` | `10.0` | `ge=1.0, le=60.0` |
| `jitter` | `0.5` | `ge=0.0, le=2.0` |

Validator: `max_delay >= initial_delay`.

### `RetriesConfig`

One `RetryConfig` per metadata type: `nip11_info`, `nip66_rtt`, `nip66_ssl`,
`nip66_geo`, `nip66_net`, `nip66_dns`, `nip66_http`.

### `ProcessingConfig`

| Field | Default | Notes |
|-------|---------|-------|
| `chunk_size` | `100` | `ge=10, le=1000` |
| `max_relays` | `None` | `ge=1` if set |
| `allow_insecure` | `False` | |
| `nip11_info_max_size` | `1_048_576` (1 MB) | `ge=1024, le=10_485_760` |
| `retries` | `RetriesConfig()` | |
| `compute` | `MetadataFlags()` | Which checks to run |
| `store` | `MetadataFlags()` | Which results to persist |

### `GeoConfig`

| Field | Default | Notes |
|-------|---------|-------|
| `city_database_path` | `"static/GeoLite2-City.mmdb"` | |
| `asn_database_path` | `"static/GeoLite2-ASN.mmdb"` | |
| `city_download_url` | GitHub P3TERX URL | |
| `asn_download_url` | GitHub P3TERX URL | |
| `max_age_days` | `30` | `ge=1`, `None` = never re-download |
| `max_download_size` | `100_000_000` (100 MB) | `ge=1_000_000, le=500_000_000` |
| `geohash_precision` | `9` | `ge=1, le=12` |

### `PublishingConfig`

`relays: list[Relay]` — default relay list with `BeforeValidator(safe_parse)`.
Fallback for discovery/announcement/profile when their `relays` field is `None`.

### `DiscoveryConfig`

| Field | Default | Notes |
|-------|---------|-------|
| `enabled` | `True` | |
| `interval` | `3600.0` | `ge=60.0, le=604800.0` |
| `include` | `MetadataFlags()` | Which metadata to include in Kind 30166 |
| `relays` | `None` | Override relay list (`None` = use publishing default) |

### `AnnouncementConfig`

| Field | Default | Notes |
|-------|---------|-------|
| `enabled` | `True` | |
| `interval` | `86_400.0` | `ge=60.0, le=604800.0` |
| `include` | `MetadataFlags()` | Which metadata to include in Kind 10166 |
| `relays` | `None` | Override relay list (`None` = use publishing default) |

### `ProfileConfig`

| Field | Default | Notes |
|-------|---------|-------|
| `enabled` | `False` | |
| `interval` | `86_400.0` | `ge=60.0, le=604800.0` |
| `relays` | `None` | Override relay list (`None` = use publishing default) |
| `name` | `"BigBrotr Monitor"` | |
| `about` | `"Nostr relay monitoring service"` | |
| `picture` | `None` | |
| `nip05` | `None` | |
| `website` | `None` | |
| `banner` | `None` | |
| `lud16` | `None` | |

### `MonitorConfig(BaseServiceConfig)`

Embeds: `networks: NetworksConfig`, `keys: KeysConfig`, `processing: ProcessingConfig`,
`geo: GeoConfig`, `publishing: PublishingConfig`, `discovery: DiscoveryConfig`,
`announcement: AnnouncementConfig`, `profile: ProfileConfig`.

**Validators** (all `model_validator(mode="after")`):

| Validator | Constraint |
|-----------|-----------|
| `validate_geo_databases` | Geo/ASN paths must exist or have download URLs |
| `validate_clearnet_only_checks` | SSL/Geo/Net/DNS compute flags require clearnet enabled |
| `validate_store_requires_compute` | `store` flags must be subset of `compute` flags |
| `validate_publish_requires_compute` | `discovery.include` and `announcement.include` must be subset of `compute` |

## Utilities (`utils.py`)

### `CheckResult` (NamedTuple)

Fields: `generated_at=0`, `nip11_info=None`, `nip66_rtt=None`, `nip66_ssl=None`,
`nip66_geo=None`, `nip66_net=None`, `nip66_dns=None`, `nip66_http=None`.

Property `has_data`: `True` if any NIP field is not `None`.

### Helper Functions

| Function | Signature | Purpose |
|----------|-----------|---------|
| `log_success(result)` | `Any -> bool` | Extract success from `BaseLogs.success` or `Nip66RttMultiPhaseLogs.open_success` |
| `log_reason(result)` | `Any -> str \| None` | Extract failure reason from `BaseLogs.reason` or `Nip66RttMultiPhaseLogs.open_reason` |
| `extract_result(results, key)` | `dict, str -> Any` | Return `None` if key absent or value is an exception |
| `collect_metadata(successful, store)` | `list[tuple], MetadataFlags -> list[RelayMetadata]` | Build storable records from check results filtered by store flags |

### `retry_fetch(relay, coro_factory, retry, operation, wait=None) -> T | None`

Standalone utility — no Monitor dependency, uses module-level `logging.getLogger(__name__)`.

- Coroutine factory pattern (Python coroutines are single-use)
- Catches `TimeoutError`/`OSError`, retries with `delay = min(initial * 2^attempt, max) + jitter`
- Optional `wait` callback for shutdown-aware sleep; falls back to `asyncio.sleep`
- Returns result (possibly with `success=False` in logs) or `None` on exception

## Database Queries (`queries.py`)

| Function | Returns | Purpose |
|----------|---------|---------|
| `delete_stale_checkpoints(brotr, keep_keys)` | `int` | Delete CHECKPOINTs where key is not in `keep_keys` and not in relay table |
| `count_relays_to_monitor(brotr, monitored_before, networks)` | `int` | Count relays due for monitoring |
| `fetch_relays_to_monitor(brotr, monitored_before, networks, limit)` | `list[Relay]` | Least-recently-monitored relays (LEFT JOIN service_state, ordered by timestamp ASC, discovered_at ASC) |
| `insert_relay_metadata(brotr, records)` | `int` | Batch insert via `batched_insert` with cascade |
| `upsert_monitor_checkpoints(brotr, relays, now)` | `None` | Create/update CHECKPOINT per relay with `{timestamp: now}` |
| `is_publish_due(brotr, state_key, interval)` | `bool` | Check if interval elapsed since last publish checkpoint; validates key in `_PUBLISH_KEYS` |
| `upsert_publish_checkpoints(brotr, state_keys)` | `None` | Upsert publish checkpoints with current timestamp; validates keys in `_PUBLISH_KEYS` |

### Internal

- `_PUBLISH_KEYS: frozenset[str]` = `frozenset({"announcement", "profile", "relay_list"})`
- `_validate_publish_keys(state_keys) -> None` — raises `ValueError` for keys not in `_PUBLISH_KEYS`
- `_RELAYS_TO_MONITOR_WHERE` — shared SQL fragment for count/fetch queries
